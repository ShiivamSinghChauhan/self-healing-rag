"""Turn company documents into Markdown with each format's own parser.

Markdown keeps headings and tables intact, so the chunker can split on
sections and the LLM sees table rows next to their column names.
"""

import csv
import json
import re
from pathlib import Path

import docx
from docx.table import Table

# "1. EMPLOYMENT BASICS" or "Q3: LumenSense battery drains ..." in the .txt files
TXT_HEADING = re.compile(r"^(\d+\.\s+[A-Z]{2,}\b.*|Q\d+:.*)$")


def to_markdown(path: Path) -> str:
    parsers = {
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
