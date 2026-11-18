"""Chat UI for the HelioVolt document assistant.  Run: streamlit run app.py"""

import uuid

import streamlit as st

import checks
import graph

st.set_page_config(page_title="HelioVolt docs assistant", page_icon=":material/bolt:")
st.title("HelioVolt docs assistant")
st.caption("Answers come only from HelioVolt's internal documents. Every answer is checked "
           "against its sources, and the search is retried when the evidence falls short.")

with st.spinner("Loading the search index..."):
    graph.search()

if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.thread_id = uuid.uuid4().hex  # chat memory lives in memory.db under this id


def show_sources(passages):
    with st.expander(f"Sources ({len(passages)})", icon=":material/description:"):
        for i, doc in enumerate(passages, 1):
            st.markdown(f"**[{i}]** `{doc.metadata['source']}`")
            st.text(doc.page_content.split("\n", 1)[-1])


def describe(node: str, update: dict) -> str | None:
    if node == "plan":
        return f"Question: {update['question']} (route: {update['route'].replace('_', '-')})"
    if node == "retrieve":
        return f"Found {len(update['candidates'])} passages to check"
    if node == "grade":
        return f"Jev judged the new passages; {len(update['evidence'])} useful so far"
    if node == "rewrite":
        return f"Not enough evidence yet, searching again: {'; '.join(update['queries'])}"
    if node == "generate":
        return "Wrote an answer from the useful passages"
    if node == "verify":
        return f"Jev checked the answer against the passages (risk {update.get('risk', 0):.2f})"
    return None


for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("sources"):
            show_sources(message["sources"])

if question := st.chat_input("Ask about policies, products, sales, IT...", submit_mode="disable"):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        result = {}
        with st.status(":shimmer[Searching the documents]", type="compact") as status:
            config = graph.thread_config(st.session_state.thread_id)
            for mode, chunk in graph.graph.stream({"message": question}, config, stream_mode=["updates", "values"]):
                if mode == "values":
                    result = chunk
                    continue
                for node, update in chunk.items():
                    if step := describe(node, update or {}):
                        st.write(step)
            verified = result.get("risk", 1) < checks.RISK_MAX
            status.update(label=f"{'Verified' if verified else 'Not fully verified'}, "
                                f"{result['attempts']} search round(s)", state="complete")
        st.markdown(result["answer"])  # an unverified answer ends with a caveat (graph.finish)
        show_sources(result["evidence"])

    st.session_state.messages.append(
        {"role": "assistant", "content": result["answer"], "sources": result["evidence"]})
