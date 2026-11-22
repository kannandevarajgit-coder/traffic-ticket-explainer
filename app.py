"""Traffic Ticket Explainer: Streamlit front end for the agentic document Q&A system."""
from __future__ import annotations

import logging
import uuid

import streamlit as st

from docqa.agents import answer_question
from docqa.config import SUPPORTED_EXTENSIONS, settings
from docqa.guardrails import DISCLAIMER
from docqa.ingest import IngestionError
from docqa.library import (
    SAMPLE,
    JURISDICTIONS,
    jurisdiction_chain,
    add_user_document,
    clear_user_documents,
    index_state_library,
    library_states,
    save_law_file,
    scope_filter,
    state_label,
)
from docqa.store import VectorStore

logging.basicConfig(level=logging.INFO)
st.set_page_config(page_title="Traffic Ticket Explainer", page_icon="🚦", layout="wide")

# Streamlit Community Cloud keeps secrets in st.secrets; copy the key into the environment for the SDK.
try:
    import os
    if "ANTHROPIC_API_KEY" in st.secrets and not os.getenv("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass


@st.cache_resource
def get_store() -> VectorStore:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return VectorStore()


@st.cache_resource(show_spinner=False)
def ensure_library(state: str, _version: int) -> dict:
    return index_state_library(get_store(), state)


store = get_store()
ss = st.session_state
ss.setdefault("session_id", uuid.uuid4().hex)
ss.setdefault("messages", [])
ss.setdefault("uploads", [])
ss.setdefault("lib_version", 0)

# ---------- sidebar: state, ticket upload, law library ----------
with st.sidebar:
    st.header("1. Choose where you got the ticket")
    with_library = library_states()
    options = list(JURISDICTIONS)
    state = st.selectbox(
        "State or city",
        options,
        format_func=lambda c: state_label(c) + ("" if any(j in with_library for j in jurisdiction_chain(c)) else "  (no laws loaded yet)"),
        index=None,
        placeholder="Select a state",
    )
    if state:
        if any(j in with_library for j in jurisdiction_chain(state)):
            with st.spinner(f"Loading {state_label(state)} laws..."):
                report = ensure_library(state, ss.lib_version)
            for err in report["errors"]:
                st.warning(err)
            n_docs = len(store.sources({"$and": [{"kind": "law"}, {"state": {"$in": jurisdiction_chain(state)}}]}))
            st.caption(f"Law library: {n_docs} document(s)" + (" incl. New York State law" if state == "NYC" else "") + ".")
        else:
            st.warning(f"No law documents for {state_label(state)} yet. Add official ones under 'Law library' below, "
                       "or answers can only describe your ticket.")
        if state == SAMPLE:
            st.info("Sample State is made-up data for trying the app. It is not real law.")

    st.header("2. Upload your ticket (optional)")
    exts = sorted(e.lstrip(".") for e in SUPPORTED_EXTENSIONS)
    ticket = st.file_uploader("PDF, photo, text, CSV or Excel", type=exts, disabled=not state, key="ticket_upload")
    if ticket and state and ticket.file_id not in ss.uploads:
        try:
            with st.spinner("Reading your ticket..."):
                n = add_user_document(store, ticket.name, ticket.getvalue(), state, ss.session_id)
            ss.uploads.append(ticket.file_id)
            st.success(f"Added {ticket.name} ({n} sections).")
        except IngestionError as exc:
            st.error(str(exc))
    if ss.uploads and st.button("Remove my uploads"):
        clear_user_documents(store, ss.session_id)
        ss.uploads = []
        st.rerun()

    with st.expander("Law library (admin)"):
        st.caption("Add official handbooks, vehicle code sections or fine schedules for the selected state.")
        law_files = st.file_uploader("Law documents", type=[e for e in exts if e not in {"jpg", "jpeg", "png", "webp"}],
                                     accept_multiple_files=True, disabled=not state, key="law_upload")
        if law_files and state and st.button(f"Add to {state_label(state)}"):
            for f in law_files:
                try:
                    save_law_file(state, f.name, f.getvalue())
                except IngestionError as exc:
                    st.error(str(exc))
            ss.lib_version += 1
            report = ensure_library(state, ss.lib_version)
            st.success("Indexed: " + (", ".join(report["indexed"]) or "nothing new"))
            for err in report["errors"]:
                st.warning(err)

    if st.button("Clear chat"):
        ss.messages = []
        st.rerun()

# ---------- main: chat ----------
st.title("🚦 Traffic Ticket Explainer")
st.write("Pick your state, upload your ticket if you have it, then ask in plain words. "
         "Answers come only from the loaded documents and show where each fact came from.")
st.caption(DISCLAIMER)

if not state:
    st.info("Start by choosing your state in the sidebar.")


def render_result(res: dict) -> None:
    st.markdown(res["answer"])
    badge = {"answered": "✅ Checked against sources", "partial": "⚠️ Partly confirmed",
             "not_found": "🔍 Not found in documents", "refused": "⛔ Declined",
             "blocked": "⛔ Blocked by input checks", "error": "❗ Error", "chat": ""}.get(res.get("status"), "")
    if badge:
        st.caption(badge)
    if res.get("citations"):
        with st.expander(f"Sources ({len(res['citations'])})"):
            for c in res["citations"]:
                st.markdown(f"**[{c['n']}] {c['source']}**")
                st.text(c["text"][:1200])
    if res.get("trace"):
        with st.expander("How the agents worked"):
            for t in res["trace"]:
                st.markdown(f"**{t['agent']}**: {t['summary']}")
                if t.get("detail", {}).get("queries"):
                    st.caption("Searches: " + " | ".join(t["detail"]["queries"]))


for m in ss.messages:
    with st.chat_message(m["role"]):
        if m["role"] == "assistant" and "result" in m:
            render_result(m["result"])
        else:
            st.markdown(m["content"])

examples = ["What does my ticket mean and what are my options?",
            "How many points is a red light ticket?",
            "What happens if I miss the due date?"]
if state and not ss.messages:
    cols = st.columns(len(examples))
    for col, ex in zip(cols, examples):
        if col.button(ex):
            ss.pending = ex
            st.rerun()

question = st.chat_input("Ask about your ticket or a driving rule", disabled=not state)
question = question or ss.pop("pending", None)
if question and state:
    ss.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Planning, searching, drafting and fact-checking..."):
            history = [{"role": m["role"], "content": m.get("content", "")} for m in ss.messages[:-1]]
            res = answer_question(store, question, history, where=scope_filter(state, ss.session_id),
                                  state_name=state_label(state))
        render_result(res)
    ss.messages.append({"role": "assistant", "content": res["answer"], "result": res})
