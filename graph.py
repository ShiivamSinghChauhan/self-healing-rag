"""Self-healing RAG as a LangGraph loop with chat memory.

    plan -> retrieve -> grade --(enough evidence)--> generate -> verify --(ok)--> finish
              ^           | not enough                             | risky answer
              +--------- rewrite <---------------------------------+

plan:     makes a follow-up standalone, routes the question (Jev): a lookup, an
          aggregation over a table (retrieve whole tables) or multi-hop, and writes
          sub-queries for every fact the answer needs
grade:    Jev keeps only the useful passages and judges whether they answer the question
verify:   Jev checks the answer against the passages; a risky answer triggers a new search
finish:   says "I don't have enough information" when no answer got past the critic,
          and saves the turn to the chat history

Jev makes every yes/no call, so the LLM only writes answers and search queries.
Each chat thread is saved in memory.db by LangGraph's SQLite checkpointer.
"""

import operator
import sqlite3
import uuid
from functools import cache
from pathlib import Path
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from groq import BadRequestError
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

import checks
from search import HybridSearch

load_dotenv()

MAX_ATTEMPTS = 3  # retrieval rounds, including the first
TOP_K = 10
NOT_FOUND = "I couldn't find that in the HelioVolt documents."
NOT_ENOUGH_INFO = ("I don't have enough information in the HelioVolt documents to answer that reliably. "
                   "The closest passages I found are listed under Sources.")
MEMORY_DB = Path(__file__).parent / "memory.db"

# "medium" reasoning: "low" skipped table rows when summing sales orders
answer_llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0, reasoning_effort="medium", max_retries=8)
helper_llm = ChatGroq(model="openai/gpt-oss-20b", temperature=0, reasoning_effort="low", max_retries=8)

answer_chain = ChatPromptTemplate.from_messages([
    ("system",
     "You answer questions from HelioVolt employees using only the numbered passages "
     "from internal documents.\n"
     "- Give the exact values (numbers, names, dates, IDs) as written in the passages.\n"
     "- For totals, counts or other calculations, go through every table row, list each number "
     "you used and show the arithmetic.\n"
     "- If a record is identified only by an ID or code (such as an org slug), answer with that code.\n"
     "- 'Text in figure' lines are OCR from charts; each label ends with its position [at x,y] "
     "(0-100 from the left and from the top), which is not a value. "
     "Pair a number with the nearest label and check it against the caption.\n"
     "- When the question asks what to do or which items, include every step, condition or item "
     "the passages give.\n"
     "- If the question names a product, version, person or place the passages never mention, "
     "say you couldn't find it instead of answering about something similar. A name counts as "
     "mentioned when it appears with extra words: 'X500' matches 'VoltGrid Controller X500'.\n"
     "- Cite passages like [2] or [1][3].\n"
     "- If the passages do not contain the answer, say you couldn't find it in the documents "
     "and name what is missing. Never guess.\n"
     "Keep the answer short."),
    ("human", "Passages:\n{context}\n\nQuestion: {question}{feedback}"),
]) | answer_llm | StrOutputParser()


class SearchQueries(BaseModel):
    queries: list[str] = Field(description="1 to 3 short search queries")


rewrite_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You write search queries for a search engine over HelioVolt's internal documents: "
     "policies, manuals, product specs, sales records, invoices, meeting notes and the org chart."),
    ("human",
     "Question: {question}\n\nPassages found so far:\n{found}\n\nQueries already tried: {tried}\n\n"
     "Write 1 to 3 new search queries for the facts that are still missing. When one fact is "
     "needed to look up another (for example a person's email after finding their name), use "
     "what the passages already say. Use words likely to appear in the documents; no file names "
     "and no quotes."),
])
# Strict JSON keeps gpt-oss-20b from wrapping the answer in the schema; when it still answers
# in prose, a tool call usually works.
rewrite_chain = rewrite_prompt | helper_llm.with_structured_output(SearchQueries, method="json_schema", strict=True) \
    .with_fallbacks([helper_llm.with_structured_output(SearchQueries, method="function_calling")])

condense_chain = ChatPromptTemplate.from_messages([
    ("human",
     "Conversation so far:\n{history}\n\nFollow-up: {question}\n\nRewrite the follow-up as a "
     "standalone question: replace words like 'it', 'their' or 'that policy' with the names they "
     "refer to in the conversation. Reply with the question only."),
]) | helper_llm | StrOutputParser()


class State(TypedDict, total=False):
    message: str  # what the user typed this turn
    history: Annotated[list[dict], operator.add]  # all turns of the thread: {"role", "content"}
    question: str  # the message as a standalone question
    route: str  # lookup | aggregate | multi_hop
    queries: list[str]
    tried: list[str]
    candidates: list[Document]
    evidence: list[Document]  # chunks Jev judged useful, kept across attempts
    p_answerable: float
    answer: str
    risk: float
    attempts: int
    jev_tokens: int


@cache
def search() -> HybridSearch:
    return HybridSearch()


def numbered(passages: list[Document]) -> str:
    return "\n\n".join(f"[{i}] {doc.page_content}" for i, doc in enumerate(passages, 1))


def find_queries(question: str, evidence: list[Document], tried: list[str]) -> list[str]:
    try:
        result = rewrite_chain.invoke({"question": question, "found": numbered(evidence) or "(nothing yet)",
                                       "tried": "; ".join(tried) or "(none)"})
    except BadRequestError:  # the helper model gave unparseable output twice: search with the question
        return []
    return result.queries[:3]


def plan(state: State) -> dict:
    """Start a turn: resolve references to earlier turns, then pick a retrieval route."""
    question, history = state["message"], state.get("history", [])[-6:]
    if history and checks.needs_history(question, history):
        turns = "\n".join(f"{turn['role']}: {turn['content']}" for turn in history)
        question = condense_chain.invoke({"history": turns, "question": question}).strip()
    route, tokens = checks.route(question)
    # Search for every fact the answer needs at once ("the backup commander" and "who the
    # CTO reports to"), instead of finding the second hop in a later round, or never.
    queries = [question] + find_queries(question, [], [])
    return {"question": question, "route": route, "queries": queries, "tried": [], "evidence": [],
            "answer": "", "risk": 0.0, "attempts": 1, "jev_tokens": tokens}


def retrieve(state: State) -> dict:
    found = search().search(state["queries"], k=TOP_K)
    if state["route"] == "aggregate":  # totals need every row, not just the chunks that matched
        found += [chunk for doc in found if "|---" in doc.page_content
                  for chunk in search().chunks_of(doc.metadata["source"])]
    # Chunks rejected in an earlier round are graded again: the new searches may make
    # them relevant (a name found in round one turns an org-chart row into evidence).
    kept, seen, candidates = {doc.id for doc in state["evidence"]}, set(), []
    for doc in found:
        if doc.id not in kept and doc.id not in seen:
            seen.add(doc.id)
            candidates.append(doc)
    return {"candidates": candidates, "tried": state["tried"] + state["queries"]}


def grade(state: State) -> dict:
    scores, tokens = checks.grade_passages(state["question"], state["queries"], state["candidates"])
    kept = [doc for doc, p in zip(state["candidates"], scores) if p >= checks.USEFUL_MIN]
    evidence = state["evidence"] + kept
    p_answerable = 0.0
    if evidence:
        p_answerable, more_tokens = checks.answerable(state["question"], evidence)
        tokens += more_tokens
    return {"evidence": evidence, "p_answerable": p_answerable, "jev_tokens": state["jev_tokens"] + tokens}


def rewrite(state: State) -> dict:
    queries = find_queries(state["question"], state["evidence"], state["tried"])
    return {"queries": queries or [state["question"]], "attempts": state["attempts"] + 1}


def generate(state: State) -> dict:
    if not state["evidence"]:
        return {"answer": NOT_FOUND}
    feedback = ""
    if state["answer"]:  # the previous answer failed verification
        feedback = (f"\n\nA previous answer was not supported by the passages: {state['answer']!r}. "
                    "Answer again using only what the passages state.")
    answer = answer_chain.invoke({"context": numbered(state["evidence"]), "question": state["question"],
                                  "feedback": feedback})
    return {"answer": answer.strip()}


def verify(state: State) -> dict:
    if not state["evidence"]:
        return {"risk": 0.0}
    evidence = state["evidence"]
    if state["route"] == "aggregate":
        # A total is checked against the table it was computed from; unrelated passages
        # next to it made Jev doubt a correct sum.
        evidence = [doc for doc in evidence if "|---" in doc.page_content] or evidence
    risk, tokens = checks.answer_risk(state["question"], evidence, state["answer"], state["p_answerable"])
    return {"risk": risk, "jev_tokens": state["jev_tokens"] + tokens}


def finish(state: State) -> dict:
    # The critic still rejects the answer after every retry: say so instead of making things up.
    answer = NOT_ENOUGH_INFO if state["risk"] >= checks.RISK_MAX else state["answer"]
    return {"answer": answer, "history": [{"role": "user", "content": state["message"]},
                                          {"role": "assistant", "content": answer}]}


def after_grade(state: State) -> str:
    if state["p_answerable"] >= checks.ANSWERABLE_MIN or state["attempts"] >= MAX_ATTEMPTS:
        return "generate"
    return "rewrite"


def after_verify(state: State) -> str:
    if state["risk"] < checks.RISK_MAX or state["attempts"] >= MAX_ATTEMPTS:
        return "finish"
    return "rewrite"


builder = (
    StateGraph(State)
    .add_node(plan)
    .add_node(retrieve)
    .add_node(grade)
    .add_node(rewrite)
    .add_node(generate)
    .add_node(verify)
    .add_node(finish)
    .add_edge(START, "plan")
    .add_edge("plan", "retrieve")
    .add_edge("retrieve", "grade")
    .add_conditional_edges("grade", after_grade, ["generate", "rewrite"])
    .add_edge("rewrite", "retrieve")
    .add_edge("generate", "verify")
    .add_conditional_edges("verify", after_verify, ["rewrite", "finish"])
    .add_edge("finish", END)
)
graph = builder.compile(checkpointer=SqliteSaver(sqlite3.connect(MEMORY_DB, check_same_thread=False)))


def thread_config(thread_id: str | None = None, **config) -> dict:
    return {**config, "configurable": {"thread_id": thread_id or uuid.uuid4().hex}}


def ask(message: str, thread_id: str | None = None, config: dict | None = None) -> State:
    """Answer one message. Messages sent with the same thread_id share chat history."""
    return graph.invoke({"message": message}, thread_config(thread_id, **(config or {})))


if __name__ == "__main__":
    import sys

    result = ask(" ".join(sys.argv[1:]) or "What is the hotel cap in Berlin?")
    print(result["answer"])
    print("\nSources:", sorted({doc.metadata["source"] for doc in result["evidence"]}))
    print(f"route={result['route']}  attempts={result['attempts']}  risk={result['risk']:.2f}")
