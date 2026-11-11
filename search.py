"""Hybrid search over the prebuilt index: Chroma vectors + BM25 fused with RRF,
then a cross-encoder reranks the candidates.

BM25 matters here because many questions hinge on exact tokens such as
"SO-2025-002", "HV-0311" or "E-14" that embeddings tend to blur.
"""

import re
from collections import defaultdict
from functools import cache
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

INDEX_DIR = Path(__file__).parent / "index"
COLLECTION = "heliovolt"
EMBED_MODEL = "Qwen/Qwen3-Embedding-0.6B"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"

# Rare filler like the "s" in "HelioVolt's" otherwise outweighs real terms such as "EIN".
STOPWORDS = set("a an and are as at be by can do does for from how i in is it of on or s the "
                "to was what when where which who why with my our".split())


@cache
def embeddings() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(
        model_name=EMBED_MODEL,
        # bfloat16 (the checkpoint default) is ~8x slower on CPUs without bf16 support
        model_kwargs={"device": "cpu", "model_kwargs": {"dtype": "float32"}},
        encode_kwargs={"normalize_embeddings": True},
        query_encode_kwargs={"normalize_embeddings": True, "prompt_name": "query"},
    )


@cache
def reranker() -> CrossEncoder:
    # On the 300 answerable golden questions it lifts recall@10 from 99.7% to 100%
    # and recall@5 from 97.3% to 98.7%.
    return CrossEncoder(RERANK_MODEL, device="cpu")


def open_store() -> Chroma:
    return Chroma(
        collection_name=COLLECTION,
        embedding_function=embeddings(),
        persist_directory=str(INDEX_DIR / "chroma"),
        collection_metadata={"hnsw:space": "cosine"},
    )


def tokenize(text: str) -> list[str]:
    """Lowercase words, keeping IDs like "so-2025-002" whole and also adding their parts."""
    tokens = []
    for token in re.findall(r"[a-z0-9]+(?:[-./:][a-z0-9]+)*", text.lower()):
        if token in STOPWORDS:
            continue
        tokens.append(token)
        parts = re.split(r"[-./:]", token)
        if len(parts) > 1:
            tokens.extend(parts)
    return tokens


class HybridSearch:
    def __init__(self):
        self.store = open_store()
        data = self.store.get()
        self.chunks = {
            chunk_id: Document(id=chunk_id, page_content=text, metadata=meta)
            for chunk_id, text, meta in zip(data["ids"], data["documents"], data["metadatas"])
        }
        if not self.chunks:
            raise RuntimeError(f"Index is empty. Run `python ingest.py` first ({INDEX_DIR}).")
        self.ids = list(self.chunks)
        self.bm25 = BM25Okapi([tokenize(self.chunks[i].page_content) for i in self.ids])

    def chunks_of(self, source: str) -> list[Document]:
        """Every chunk of one file in order, e.g. all row groups of a large table."""
        chunks = [chunk for chunk in self.chunks.values() if chunk.metadata["source"] == source]
        return sorted(chunks, key=lambda chunk: int(chunk.id.rsplit("#", 1)[1]))

    def search(self, queries: list[str], k: int = 10, pool: int = 20) -> list[Document]:
        """Fuse a dense and a BM25 ranking per query (RRF), then let the cross-encoder
        reorder the best `pool` candidates and keep `k`."""
        scores = defaultdict(float)
        for query in queries:
            dense = [doc.id for doc in self.store.similarity_search(query, k=pool)]
            bm25 = self.bm25.get_scores(tokenize(query))
            sparse = [self.ids[i] for i in bm25.argsort()[::-1][:pool] if bm25[i] > 0]
            for ranking in (dense, sparse):
                for rank, chunk_id in enumerate(ranking):
                    scores[chunk_id] += 1 / (60 + rank)
        candidates = [self.chunks[chunk_id] for chunk_id in sorted(scores, key=scores.get, reverse=True)[:pool]]
        # A chunk only needs to match one of the queries (multi-hop asks for different facts).
        relevance = reranker().predict([(q, doc.page_content) for q in queries for doc in candidates])
        best = relevance.reshape(len(queries), len(candidates)).max(axis=0)
        return [doc for _, doc in sorted(zip(best, candidates), key=lambda pair: -pair[0])][:k]
