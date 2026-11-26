# self-healing-rag

A question-answering bot over messy company documents (PDF, scanned PDF, DOCX, CSV, JSON, Markdown) that **checks its own work**. If the passages it found don't answer the question, or the answer isn't supported by them, it rewrites the search and tries again. If it still can't, it says so instead of guessing.

## Built with

Python 3.13 · LangGraph (with SQLite chat memory) · Chroma + BM25 + a cross-encoder reranker · Qwen3-Embedding · pymupdf4llm, python-docx and RapidOCR for parsing · Jev (TypeSafe) for decisions · gpt-oss-120b on Groq for answers · Streamlit

## What makes it different

- **Self-healing loop:** plan -> retrieve -> grade -> generate -> verify, with a rewrite step that sends it back to search when evidence is weak or the answer looks risky.
- **Jev makes the yes/no calls** (is this passage useful, is there enough evidence, is the answer supported) as calibrated probabilities with thresholds. The LLM only writes queries and answers.
- **Documents are parsed properly.** Every format becomes Markdown with headings and tables intact, chart labels are read with their positions, and scans are OCR'd after fill-in rules are erased.
- **Hybrid search** (vectors + BM25 fused with RRF, then reranked), because exact IDs like `SO-2025-002` get blurred by embeddings alone.
- **Handles harder questions:** follow-ups, multi-hop, totals over tables, and questions the documents can't answer.
- **Evaluated on a 320-question golden set.** Compared with plain top-10 RAG, the pipeline reaches ~98% accuracy while giving the answer model about 3 passages instead of 10 (972 vs 2,156 input tokens).

## Run it

```bash
uv sync
# .env: GROQ_API_KEY, TYPESAFE_API_KEY
uv run python ingest.py               # build the index from documents/
uv run streamlit run app.py           # chat UI
uv run python evaluate.py             # full pipeline (--baseline for plain RAG)
```
