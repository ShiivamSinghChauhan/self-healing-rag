"""Yes/no judgments made by Jev (TypeSafe's System One model) instead of an LLM.

Jev returns a calibrated probability for each question; the thresholds below
turn those probabilities into decisions. Question wording and thresholds live
together in this file so they are reviewed and tuned in one place.
"""

from functools import cache

from langchain_core.documents import Document
from typesafe_sdk import Choice, Noul, NoulCriteria, TypeSafeClient

MODEL = "jev-1.14.0"  # pinned: thresholds are calibrated for this version

USEFUL_MIN = 0.3  # keep a passage unless Jev is fairly sure it is useless (multi-hop steps score 0.4-0.6)
ANSWERABLE_MIN = 0.5  # generate only when the kept passages probably hold the answer
RISK_MAX = 0.3  # accept the generated answer below this risk
UNKNOWN_MIN = 0.9  # the question names something the passages never mention: don't answer

USEFUL_CRITERIA = NoulCriteria(
    true="the passage states the answer or part of it, or a step on the way to it, such as who "
    "holds a role, which plan a customer is on, or which record the question refers to",
    false="the passage is about something else, or only shares words with the question "
    "without stating any fact the answer depends on",
)

ANSWERABLE = Noul(
    instructions="Do the `passages` state every fact needed to answer `question`?",
    criteria=NoulCriteria(
        true="each fact the answer needs is stated in the passages, or can be computed from "
        "numbers stated in them",
        false="at least one fact the answer needs is not in the passages",
    ),
)

DECLINES = Noul(
    instructions="Does `answer` decline to answer, or say the documents do not contain the information?",
    criteria=NoulCriteria(
        true="the answer says it could not find the information or cannot answer",
        false="the answer gives an answer",
    ),
)

SUPPORTED = Noul(
    instructions="Following the `passages` step by step from `question`, do you arrive at `answer`?",
    criteria=NoulCriteria(
        true="every fact, name and number in the answer is stated in the passages or computed "
        "from numbers stated in them",
        false="the answer contains a fact, name or number that the passages do not support",
    ),
)

UNKNOWN_SUBJECT = Noul(
    instructions="Does `question` ask about a specific product, model, version, document, person or place "
    "that the `passages` never mention by that name or number?",
    criteria=NoulCriteria(
        true="the question names something, such as a model number or version, that appears nowhere in the passages",
        false="everything the question names appears in the passages, or the question names nothing specific",
    ),
)

NEEDS_HISTORY = Noul(
    instructions="Does `question` refer to something that is only named in `history`, "
    "for example with 'it', 'that', 'they' or 'the same'?",
)

ROUTE = Choice(
    instructions="What does answering `question` take?",
    criteria={
        "lookup": "Finding one or a few facts that are stated in one place.",
        "aggregate": "Adding up, counting, averaging, ranking or comparing many rows of a table.",
        "multi_hop": "Finding one fact first and then using it to look up another, for example "
                     "the email of the person who wrote a report.",
    },
)


@cache
def client() -> TypeSafeClient:
    return TypeSafeClient(model=MODEL)


def route(question: str) -> tuple[str, int]:
    response = client().system_one(state={"question": question}, questions={"route": ROUTE})
    return response.choices["route"].choice, response.usage.input_tokens or 0


def ask(state: dict, questions: dict) -> tuple[dict[str, float], int]:
    response = client().system_one(state=state, questions=questions)
    return {key: response.nouls[key].noul for key in questions}, response.usage.input_tokens or 0


def numbered(passages: list[Document]) -> dict:
    return {f"p{i}": doc.page_content for i, doc in enumerate(passages, 1)}


def grade_passages(question: str, searches: list[str], passages: list[Document]) -> tuple[list[float], int]:
    """P(useful) for every passage in one request. Jev answers each question on its
    own, so a passage is never judged next to the other retrieved passages.

    `searches` matter for multi-hop questions: "Priya Desai email" finds a passage
    that never mentions the quarterly report but still completes the answer."""
    questions = {
        f"p{i}": Noul(
            instructions="Does this passage state a fact needed to answer `question`, either the "
            "answer itself or a step toward it, or a fact that one of the `searches` looks for?"
            f"\n\nPassage:\n{doc.page_content}",
            criteria=USEFUL_CRITERIA,
        )
        for i, doc in enumerate(passages)
    }
    if not questions:
        return [], 0
    probs, tokens = ask({"question": question, "searches": searches}, questions)
    return [probs[f"p{i}"] for i in range(len(passages))], tokens


def answerable(question: str, passages: list[Document]) -> tuple[float, int]:
    probs, tokens = ask({"question": question, "passages": numbered(passages)}, {"answerable": ANSWERABLE})
    return probs["answerable"], tokens


def answer_risk(question: str, passages: list[Document], answer: str, p_answerable: float) -> tuple[float, int]:
    """Chance the answer is wrong. A refusal is risky when the passages do hold the
    answer; an answer is risky when the passages don't lead to it, or when the question
    is about something the passages never name (the X600 answered with the X500's warranty)."""
    state = {"question": question, "passages": numbered(passages), "answer": answer}
    probs, tokens = ask(state, {"declines": DECLINES, "supported": SUPPORTED, "unknown": UNKNOWN_SUBJECT})
    if probs["declines"] >= 0.5:
        return p_answerable, tokens
    if probs["unknown"] >= UNKNOWN_MIN:
        return 1.0, tokens
    return 1 - probs["supported"], tokens


def needs_history(question: str, history: list[dict]) -> bool:
    probs, _ = ask({"question": question, "history": history}, {"needs_history": NEEDS_HISTORY})
    return probs["needs_history"] >= 0.5
