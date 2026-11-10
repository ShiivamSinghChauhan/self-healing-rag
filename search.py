"""Chroma vector store over the prebuilt index (Qwen3-Embedding-0.6B, on CPU)."""

from functools import cache
from pathlib import Path

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

INDEX_DIR = Path(__file__).parent / "index"
COLLECTION = "heliovolt"
EMBED_MODEL = "Qwen/Qwen3-Embedding-0.6B"


@cache
def embeddings() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(
        model_name=EMBED_MODEL,
        # bfloat16 (the checkpoint default) is ~8x slower on CPUs without bf16 support
        model_kwargs={"device": "cpu", "model_kwargs": {"dtype": "float32"}},
        encode_kwargs={"normalize_embeddings": True},
        query_encode_kwargs={"normalize_embeddings": True, "prompt_name": "query"},
    )


def open_store() -> Chroma:
    return Chroma(
        collection_name=COLLECTION,
        embedding_function=embeddings(),
        persist_directory=str(INDEX_DIR / "chroma"),
        collection_metadata={"hnsw:space": "cosine"},
    )
