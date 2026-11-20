"""Run the golden set through the pipeline and grade the answers with JevEval.

    python evaluate.py                    # full self-healing pipeline
    python evaluate.py --baseline         # plain RAG: top-10 chunks straight to the LLM
    python evaluate.py --only multi none  # just the ids starting with these prefixes

Rows are appended to eval/results/<run>.jsonl as they finish, so an interrupted
run picks up where it stopped (use --fresh to start over).
"""

import argparse
import json
import os
import statistics
import time
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")  # must be set before deepeval is imported

from deepeval.metrics import JevEval
from deepeval.metrics.jev_eval import Noul
from deepeval.test_case import LLMTestCase, SingleTurnParams
from groq import RateLimitError
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_groq import ChatGroq
from pydantic import BaseModel

import graph

EVAL_DIR = Path(__file__).parent / "eval"

# USD per 1M tokens (input, output): Groq list prices and TypeSafe's Jev price, Oct 2026
PRICES = {"openai/gpt-oss-120b": (0.15, 0.60), "openai/gpt-oss-20b": (0.075, 0.30), "jev": (0.042, 0.0)}

correctness = JevEval(
    name="Correctness",
    evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT],
    questions=[Noul(
        "Does `test_case.actual_output` give the same answer to `test_case.input` as "
        "`test_case.expected_output`?",
        true="every value, name or fact the question asks for matches the expected output (other "
        "wording, citations and extra detail are fine, and so is leaving out context in parentheses "
        "that the question did not ask for); or both say the documents do not have the answer",
        false="a value, name or fact the question asks for is missing or different; or one of them "
        "says the documents do not have the answer and the other gives an answer",
    )],
    async_mode=False,
)


class Verdict(BaseModel):
    correct: bool
    reason: str


# Second opinion, only for the answers Jev is unsure about.
referee = ChatGroq(model="openai/gpt-oss-20b", temperature=0, reasoning_effort="medium", max_retries=8) \
    .with_structured_output(Verdict, method="function_calling").with_retry(stop_after_attempt=3)


def grade(row: dict, answer: str) -> tuple[bool, float, str]:
    case = LLMTestCase(input=row["question"], actual_output=answer, expected_output=row["answer"])
    score = correctness.measure(case, _show_indicator=False)
    if 0.2 < score < 0.8:
        verdict = referee.invoke(
            "Grade a company Q&A assistant against a reference answer. It is correct when every "
            "value, name or fact the question asks for matches the reference. Extra detail is fine, "
            "and so is leaving out context in parentheses that the question did not ask for. If the "
            "reference says the documents don't contain the answer, the answer is correct only if "
            "it also says so.\n\n"
            f"Question: {row['question']}\nReference: {row['answer']}\nAnswer: {answer}")
        return verdict.correct, score, "referee"
    return score >= 0.5, score, "jev"


def run_baseline(question: str, config: dict) -> dict:
    passages = graph.search().search([question], k=graph.TOP_K)
    answer = graph.answer_chain.invoke(
        {"context": graph.numbered(passages), "question": question, "feedback": ""}, config)
    return {"answer": answer.strip(), "evidence": passages, "attempts": 1, "risk": None, "jev_tokens": 0}


def evaluate_one(row: dict, baseline: bool) -> dict:
    usage = UsageMetadataCallbackHandler()
    config = {"callbacks": [usage]}
    started = time.time()
    result = run_baseline(row["question"], config) if baseline else graph.ask(row["question"], config=config)
    seconds = time.time() - started
    correct, score, judge = grade(row, result["answer"])
    sources = sorted({doc.metadata["source"] for doc in result["evidence"]})
    return {
        "id": row["id"], "type": row["type"], "question": row["question"], "expected": row["answer"],
        "answer": result["answer"], "correct": correct, "jev_score": round(score, 3), "judge": judge,
        "source_hit": bool(set(sources) & set(row["sources"])) if row["sources"] else None,
        "sources": sources, "context_chunks": len(result["evidence"]), "attempts": result["attempts"],
        "risk": result["risk"], "seconds": round(seconds, 2),
        "llm_tokens": {model: [u["input_tokens"], u["output_tokens"]] for model, u in usage.usage_metadata.items()},
        "jev_tokens": result.get("jev_tokens", 0),
    }


def cost(row: dict) -> float:
    total = row["jev_tokens"] * PRICES["jev"][0]
    for model, (tokens_in, tokens_out) in row["llm_tokens"].items():
        price_in, price_out = PRICES.get(model, (0, 0))
        total += tokens_in * price_in + tokens_out * price_out
    return total / 1e6


def summarize(rows: list[dict]) -> dict:
    by_type = defaultdict(list)
    for row in rows:
        by_type[row["type"]].append(row["correct"])
    hits = [row["source_hit"] for row in rows if row["source_hit"] is not None]
    answer_in = [row["llm_tokens"].get("openai/gpt-oss-120b", [0, 0])[0] for row in rows]
    seconds = sorted(row["seconds"] for row in rows)
    return {
        "questions": len(rows),
        "accuracy": round(sum(row["correct"] for row in rows) / len(rows), 4),
        "accuracy_by_type": {t: f"{sum(v)}/{len(v)}" for t, v in sorted(by_type.items())},
        "source_recall": round(sum(hits) / len(hits), 4) if hits else None,
        "first_attempt": round(sum(row["attempts"] == 1 for row in rows) / len(rows), 4),
        "avg_context_chunks": round(statistics.mean(row["context_chunks"] for row in rows), 2),
        "avg_answer_llm_input_tokens": round(statistics.mean(answer_in)),
        "avg_jev_tokens": round(statistics.mean(row["jev_tokens"] for row in rows)),
        "cost_per_1k_questions_usd": round(1000 * statistics.mean(cost(row) for row in rows), 3),
        "latency_p50_s": seconds[len(seconds) // 2],
        "latency_p95_s": seconds[int(len(seconds) * 0.95) - 1],
        "referee_calls": sum(row["judge"] == "referee" for row in rows),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true", help="plain top-k RAG, no Jev checks")
    parser.add_argument("--only", nargs="*", help="id prefixes to run, e.g. multi none")
    parser.add_argument("--run", help="results file name (default: pipeline or baseline)")
    parser.add_argument("--fresh", action="store_true", help="ignore earlier results for this run")
    parser.add_argument("--regrade", action="store_true", help="re-score saved answers, no pipeline calls")
    args = parser.parse_args()

    golden = [json.loads(line) for line in (EVAL_DIR / "golden.jsonl").open(encoding="utf-8")]
    if args.only:
        golden = [row for row in golden if row["id"].startswith(tuple(args.only))]

    out = EVAL_DIR / "results" / f"{args.run or ('baseline' if args.baseline else 'pipeline')}.jsonl"
    out.parent.mkdir(exist_ok=True)
    if args.fresh:
        out.unlink(missing_ok=True)
    done = {json.loads(line)["id"]: json.loads(line) for line in out.open(encoding="utf-8")} if out.exists() else {}
    if args.regrade:
        by_id = {row["id"]: row for row in golden}
        for row in done.values():
            if row["id"] in by_id:
                row["correct"], row["jev_score"], row["judge"] = grade(by_id[row["id"]], row["answer"])
        out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in done.values()),
                       encoding="utf-8")
        golden = [row for row in golden if row["id"] in done]

    with out.open("a", encoding="utf-8") as f:
        for i, row in enumerate(golden, 1):
            if row["id"] in done:
                continue
            try:
                result = evaluate_one(row, args.baseline)
            except RateLimitError as error:  # free tier: 200k tokens/day for gpt-oss-120b
                print(f"Groq rate limit; rerun later to continue from {row['id']}. {error.message[:120]}")
                break
            done[row["id"]] = result
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
            f.flush()
            mark = "ok " if result["correct"] else "BAD"
            print(f"[{i}/{len(golden)}] {mark} {row['id']:12} attempts={result['attempts']} "
                  f"{result['seconds']:5.1f}s  {result['answer'][:90]!r}")

    rows = [done[row["id"]] for row in golden if row["id"] in done]
    summary = summarize(rows)
    print(json.dumps(summary, indent=2))
    for row in rows:
        if not row["correct"]:
            print(f"\nWRONG {row['id']}: {row['question']}\n  expected: {row['expected']}\n  got:      {row['answer']}")
    out.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
