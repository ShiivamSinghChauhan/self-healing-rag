from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    MarkdownHeaderTextSplitter,
    RecursiveJsonSplitter
    )
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document
from pathlib import Path
import os
from functools import lru_cache

current_dir = Path.cwd()

DOCUMENTS_DIR = current_dir / 'handle_database'/ 'documents'
DATABASE_DIR = current_dir / 'handle_database'/ 'database'
COLLECTION_NAME = 'HelioVolt_db'

# =========================== utility ===============================

@lru_cache
def get_all_files(documents_dir: Path) -> dict[str, list]:
    """
    takes documents folder Path object, and return all files in it in their format groups"""

    if documents_dir.exists():
        all_files = [
            file.relative_to(documents_dir)
            for file in documents_dir.rglob("*")
            if file.is_file()
        ]

        total_formats = set(map(lambda x: x.name.split('.')[-1], all_files))

        grouped_formats = {fmt: [] for fmt in total_formats}
        for file in all_files:
            grouped_formats[file.name.split('.')[-1]].append(file)

        return grouped_formats

    else:
        raise Exception('Wrong document folder')

@lru_cache
def get_markdown_splitter():
    pass

@lru_cache
def get_vector_store() -> Chroma:

    embedder = OllamaEmbeddings(
        model='hf.co/Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0'
    )

    vector_store = Chroma(
        collection_name=COLLECTION_NAME,
        persist_directory=str(DATABASE_DIR),
        embedding_function=embedder,
        collection_configuration={
            'hnsw': {
                'space': 'cosine'
            }
        }
    )

    return vector_store

# ===================================================================


def save_txts():

    text_files = get_all_files(DOCUMENTS_DIR).get('txt')
    if text_files:
        for path in text_files:
            doc = Document(path.read_text(encoding="utf-8"))
            doc.metadata = {'source': path}

            splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
            docs = splitter.split_documents(doc)

            vector_store = get_vector_store()
            vector_store.add_documents(docs)





def save_pdfs():
    import pymupdf4llm
    text_files = get_all_files(DOCUMENTS_DIR).get('txt')
    if text_files:
        pass

def save_jsons():
    text_files = get_all_files(DOCUMENTS_DIR).get('txt')
    if text_files:
        pass

def save_csv_xlsxs():
    text_files = get_all_files(DOCUMENTS_DIR).get('txt')
    if text_files:
        pass





