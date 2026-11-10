"""Build the search index from documents/ into index/.

Run once, and again whenever documents change:  python ingest.py
The app only reads index/, so parsing and embedding never happen at query time.
"""

import shutil
import time
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from parse import to_markdown
from search import INDEX_DIR, open_store

DOCS_DIR = Path(__file__).parent / "documents"
PROSE_MAX_CHARS = 1000  # a longer section mixes topics and its embedding gets blurry
TABLE_MAX_CHARS = 2000  # tables stay whole up to here so totals can see every row

section_splitter = MarkdownHeaderTextSplitter([("#", "h1"), ("##", "h2"), ("###", "h3")])
prose_splitter = RecursiveCharacterTextSplitter(chunk_size=PROSE_MAX_CHARS, chunk_overlap=100)


def chunk(markdown: str, source: str) -> list[Document]:
    """One chunk per Markdown section. Every chunk starts with its file and
    heading path, so a lone table row or paragraph still says where it is from."""
    chunks = []
    intro = document_intro(markdown)
    for section in section_splitter.split_text(markdown):
        headings = [h.replace("**", "").strip() for h in section.metadata.values()]
        label = " > ".join([source, *headings])
        for piece in split_long(section.page_content):
            # A section deep in a document doesn't say what the document is about: the
            # "specs" list of the VoltGrid file never names the X500. The intro says so.
            about = f"(Document: {intro})\n" if intro and intro[:40] not in piece else ""
            chunks.append(Document(
                page_content=f"[{label}]\n{about}{piece}",
                metadata={"source": source, "section": " > ".join(headings)},
            ))
    return chunks


def document_intro(markdown: str, limit: int = 160) -> str:
    """The text between the title and the first section heading, on one line."""
    lines = []
    for line in markdown.splitlines()[1:]:
        if line.startswith("#"):
            break
        if not line.startswith(("|", "Text in figure")):  # tables and chart text are content, not context
            lines.append(line.replace("**", "").strip("-* ").strip())
    intro = " ".join(line for line in lines if line)
    return intro if len(intro) <= limit else intro[:limit].rsplit(" ", 1)[0] + " ..."


def split_long(text: str) -> list[str]:
    lines = text.splitlines()
    first_row = next((i for i, line in enumerate(lines) if line.startswith("|")), None)
    if first_row is None:
        return [text] if len(text) <= PROSE_MAX_CHARS else prose_splitter.split_text(text)
    if len(text) <= TABLE_MAX_CHARS:
        return [text]

    # Big table: repeat the text above it and the header row in every piece.
    head, rows = lines[:first_row + 2], [line for line in lines[first_row + 2:] if line.strip()]
    pieces, current = [], []
    for row in rows:
        if current and len("\n".join(head + current + [row])) > TABLE_MAX_CHARS:
            pieces.append("\n".join(head + current))
            current = []
        current.append(row)
    return pieces + ["\n".join(head + current)]


def main():
    started = time.time()
    shutil.rmtree(INDEX_DIR, ignore_errors=True)
    parsed_dir = INDEX_DIR / "parsed"  # parsed Markdown, kept so parsing can be audited

    chunks, ids = [], []
    for path in sorted(p for p in DOCS_DIR.rglob("*") if p.is_file()):
        source = path.relative_to(DOCS_DIR).as_posix()
        markdown = to_markdown(path)
        out = parsed_dir / f"{source}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        doc_chunks = chunk(markdown, source)
        chunks += doc_chunks
        ids += [f"{source}#{i}" for i in range(len(doc_chunks))]
        print(f"{source:55} {len(doc_chunks):3} chunks")

    print(f"Embedding {len(chunks)} chunks...")
    open_store().add_documents(chunks, ids=ids)
    print(f"Indexed {len(chunks)} chunks in {time.time() - started:.0f}s -> {INDEX_DIR}")


if __name__ == "__main__":
    main()
