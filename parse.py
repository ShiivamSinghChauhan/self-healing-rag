"""Turn company documents into Markdown with each format's own parser.

Markdown keeps headings and tables intact, so the chunker can split on
sections and the LLM sees table rows next to their column names.
"""

import csv
import json
import logging
import re
from functools import cache
from pathlib import Path

import cv2
import docx
import numpy as np
import pymupdf
import pymupdf4llm
from docx.table import Table
from rapidocr import RapidOCR

pymupdf.set_messages(pylogging=True, pylogging_level=logging.INFO)  # keep OCR chatter quiet

# "1. EMPLOYMENT BASICS" or "Q3: LumenSense battery drains ..." in the .txt files
# "2210 units", "$4.82M", "19.5%": a number with at most a short unit
CHART_VALUE = re.compile(r"^[$€]?\d[\d.,]*\s*(%|[A-Za-z]{1,6})?$")
TXT_HEADING = re.compile(r"^(\d+\.\s+[A-Z]{2,}\b.*|Q\d+:.*)$")


def to_markdown(path: Path) -> str:
    parsers = {
        ".pdf": pdf_to_markdown,
        ".docx": docx_to_markdown,
        ".csv": csv_to_markdown,
        ".json": json_to_markdown,
        ".txt": txt_to_markdown,
        ".md": lambda p: p.read_text(encoding="utf-8"),
    }
    parser = parsers.get(path.suffix.lower())
    if parser is None:
        raise ValueError(f"no parser for {path.name}")
    return parser(path).strip()


def pdf_to_markdown(path: Path) -> str:
    with pymupdf.open(path) as pdf:
        if not any(page.get_text().strip() for page in pdf):
            return scanned_to_markdown(pdf)
    # pymupdf4llm runs layout analysis (tables, headings) and RapidOCR on text
    # inside charts.
    md = pymupdf4llm.to_markdown(str(path), ocr_dpi=300)
    # pymupdf4llm reads chart labels row by row, so a pie chart's left and right
    # labels get glued together ("EcoPulse 5400 units"). Re-read each figure with
    # label positions instead, in the same order the figures appear.
    figures = iter(figure_texts(path))
    md = re.sub(r"<!-- Start of picture text -->.*?<!-- End of picture text -->",
                lambda m: f"Text in figure: {next(figures, '')}", md, flags=re.S)
    md = re.sub(r"(?m)^Page \d+\s*$", "", md)
    # "**3. Encryption:** TLS 1.2+ ..." is a section heading set in bold; make it one
    md = re.sub(r"(?m)^\*\*(\d+\.\s*[^*\n]+?):?\*\*:?\s*", r"## \1\n\n", md)
    return re.sub(r"\n{3,}", "\n\n", md)


@cache
def ocr_engine() -> RapidOCR:
    return RapidOCR()


def scanned_to_markdown(pdf: pymupdf.Document) -> str:
    """OCR a scanned document at 300 dpi (150 dpi garbles the small print), one
    paragraph per text line, after erasing fill-in rules such as "Supervisor: ____".
    Left in, the rule under a signature is read as letters: "Aisha Khan" became "Aisha Khann"."""
    lines = []
    for page in pdf:
        pix = page.get_pixmap(dpi=300, colorspace=pymupdf.csGRAY)
        gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
        result = ocr_engine()(cv2.imencode(".png", erase_fill_in_rules(gray))[1].tobytes())
        if not result.txts:
            continue
        # boxes on the same line (vertical centres within half a line height) are joined left to right
        boxes = sorted((box[:, 1].mean(), box[:, 0].min(), np.ptp(box[:, 1]), text)
                       for box, text in zip(result.boxes, result.txts))
        row = [boxes[0]]
        for box in boxes[1:]:
            if box[0] - row[0][0] < row[0][2] / 2:
                row.append(box)
            else:
                lines.append(" ".join(text for *_, text in sorted(row, key=lambda b: b[1])))
                row = [box]
        lines.append(" ".join(text for *_, text in sorted(row, key=lambda b: b[1])))
    return "\n\n".join(lines)


def erase_fill_in_rules(gray: np.ndarray) -> np.ndarray:
    """Paint white over runs of thin horizontal strokes ("______" or a solid rule)."""
    ink = (gray < 160).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    boxes = stats[1:, :4]  # x, y, width, height of every ink blob
    tall = boxes[:, 3][boxes[:, 3] > 8]
    line_height = float(np.median(tall)) if len(tall) else 20.0
    strokes = sorted((b for b in boxes if b[3] <= 0.2 * line_height and b[2] >= 2 * b[3]),
                     key=lambda b: (round(b[1] / (0.3 * line_height)), b[0]))
    out, runs, run = gray.copy(), [], []
    for b in strokes:
        same_line = run and abs(b[1] - run[-1][1]) <= 0.15 * line_height
        if same_line and b[0] - (run[-1][0] + run[-1][2]) <= 3 * max(b[2], run[-1][2]):
            run.append(b)
        else:
            runs.append(run)
            run = [b]
    runs.append(run)
    for run in runs:
        if len(run) >= 4 or (len(run) == 1 and run[0][2] >= 3 * line_height):
            for x, y, w, h in run:
                out[max(y - 1, 0):y + h + 1, max(x - 1, 0):x + w + 1] = 255
    return out


def figure_texts(path: Path) -> list[str]:
    texts = []
    with pymupdf.open(path) as pdf:
        for page in pdf:
            if not page.get_text().strip():
                continue  # scanned page: pymupdf4llm already OCRs the whole page
            for xref, *_ in page.get_images(full=True):
                image = pymupdf.Pixmap(pdf, xref)
                result = ocr_engine()(image.tobytes("png"))
                if not result.txts:
                    continue
                # Each label gets its position, 0-100 from the left and from the top.
                # Without it a pie chart's "19.5%" can't be told apart from "23.4%";
                # with it the LLM pairs every number with the nearest label.
                labels = []
                for box, text in zip(result.boxes, result.txts):
                    x = round(box[:, 0].mean() / image.width * 100)
                    y = round(box[:, 1].mean() / image.height * 100)
                    labels.append((y, x, f"{text} [at {x},{y}]"))
                text = " | ".join(label for *_, label in sorted(labels))
                if pairs := stacked_pairs(result.boxes, result.txts):
                    text += "\nLabels with the value printed right under them: " + "; ".join(pairs)
                texts.append(text)
    return texts


def stacked_pairs(boxes, texts) -> list[str]:
    """A chart label with a number directly beneath it ("EcoPulse" over "2210 units") is
    one data point. Read row by row, the pie chart's "EcoPulse" sits on the same line as
    LumenSense's "5400 units", and the model paired those two."""
    spans = [(b[:, 0].min(), b[:, 0].max(), b[:, 1].min(), b[:, 1].max(), t) for b, t in zip(boxes, texts)]
    pairs = []
    for x0, x1, y0, y1, label in spans:
        if CHART_VALUE.match(label):
            continue
        below = [(vy0 - y1, value) for vx0, vx1, vy0, vy1, value in spans
                 if CHART_VALUE.match(value) and 0 <= vy0 - y1 < 0.5 * (y1 - y0)
                 and min(x1, vx1) - max(x0, vx0) > 0.5 * min(x1 - x0, vx1 - vx0)]
        if below:
            pairs.append(f"{label}: {min(below)[1]}")
    return pairs


def docx_to_markdown(path: Path) -> str:
    blocks = []
    for block in docx.Document(path).iter_inner_content():
        if isinstance(block, Table):
            blocks.append(markdown_table([[cell.text for cell in row.cells] for row in block.rows]))
            continue
        text = block.text.strip()
        if not text:
            continue
        style = block.style.name if block.style else ""
        if style == "Title":
            blocks.append(f"# {text}")
        elif style.startswith("Heading"):
            level = int(style.split()[-1]) if style.split()[-1].isdigit() else 1
            blocks.append(f"{'#' * (level + 1)} {text}")
        elif style.startswith("List"):
            blocks.append(f"- {text}")
        else:
            blocks.append(text)
    return "\n\n".join(blocks)


def csv_to_markdown(path: Path) -> str:
    with path.open(newline="", encoding="utf-8") as f:
        rows = [row for row in csv.reader(f) if any(cell.strip() for cell in row)]
    return f"# {title_from_name(path)}\n\n{markdown_table(rows)}"


def json_to_markdown(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    return f"# {title_from_name(path)}\n\n" + "\n".join(render_json(data, level=2))


def title_from_name(path: Path) -> str:
    return path.stem.replace("_", " ")


def render_json(value, level: int) -> list[str]:
    """Scalars become "- key: value" lines, lists of objects become tables and
    nested objects become sub-sections. Scalars go first so they never end up
    under a sub-heading they don't belong to."""
    if not isinstance(value, dict):
        return [f"- {format_value(value)}"]

    lines, sections = [], []
    for key, item in value.items():
        key = key.replace("_", " ")  # "CTO_reports_to" reads (and embeds) better as words
        if isinstance(item, list) and item and all(isinstance(x, dict) for x in item):
            columns = list(dict.fromkeys(k for row in item for k in row))
            rows = [columns] + [[format_value(row.get(c, "")) for c in columns] for row in item]
            sections += ["", f"{'#' * level} {key}", "", markdown_table(rows)]
        elif isinstance(item, dict):
            sections += ["", f"{'#' * level} {key}", "", *render_json(item, level + 1)]
        else:
            lines.append(f"- {key}: {format_value(item)}")
    return lines + sections


def format_value(value) -> str:
    if isinstance(value, list):
        return ", ".join(format_value(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {format_value(v)}" for k, v in value.items())
    return str(value)


def txt_to_markdown(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    out = [f"# {lines[0].strip()}"]
    for line in lines[1:]:
        stripped = line.strip()
        out.append(f"## {stripped}" if len(stripped) < 100 and TXT_HEADING.match(stripped) else line)
    return "\n".join(out)


def markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    clean = [[cell.replace("|", "\\|").replace("\n", " ").strip() for cell in row] + [""] * (width - len(row))
             for row in rows]
    header, *body = clean
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)
