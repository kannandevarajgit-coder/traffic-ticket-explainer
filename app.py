"""Traffic Ticket Explainer: Streamlit front end for the agentic document Q&A system."""
from __future__ import annotations

import html
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from docqa.agents import answer_question
from docqa.config import SUPPORTED_EXTENSIONS, settings
from docqa.guardrails import DISCLAIMER
from docqa.ingest import IngestionError, load_document
from docqa.library import (
    SAMPLE,
    JURISDICTIONS,
    clear_user_documents,
    index_state_library,
    index_user_sections,
    jurisdiction_chain,
    library_states,
    save_law_file,
    scope_filter,
    state_label,
)
from docqa.llm import LLMError
from docqa.store import VectorStore
from docqa.ticket import TicketInfo, calendar_file, days_left, deadline_label, extract_ticket, parse_date

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")
st.set_page_config(page_title="Traffic Ticket Explainer", page_icon="🚦", layout="wide")

# Streamlit Community Cloud keeps secrets in st.secrets; copy the key into the environment for the SDK.
try:
    if "ANTHROPIC_API_KEY" in st.secrets and not os.getenv("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass

SAMPLE_TICKET = Path(__file__).parent / "sample_docs" / "sample_ticket.pdf"
SHORT_LABELS = {"CA": "California", "NJ": "New Jersey", "NY": "New York State", "NYC": "New York City",
                "VT": "Vermont", "SAMPLE": "🧪 Sample State"}
AGENT_ICONS = {"Guardrail": "🛡️", "Planner": "🧭", "Retriever": "🔎", "Reasoner": "✍️",
               "Validator": "✅", "Finalize": "📦"}
NEXT_STEP = {"Guardrail": "Planning your question…", "Planner": "Searching the law documents…",
             "Retriever": "Writing a cited answer…", "Reasoner": "Fact-checking every claim…",
             "Validator": "Finishing up…"}
STATUS = {
    "answered": ("Verified against sources", "green", ":material/verified:"),
    "partial": ("Partly confirmed", "orange", ":material/warning:"),
    "not_found": ("Not found in the documents", "gray", ":material/search_off:"),
    "refused": ("Declined", "red", ":material/block:"),
    "blocked": ("Blocked by safety checks", "red", ":material/gpp_bad:"),
    "error": ("Something went wrong", "red", ":material/error:"),
}
Q_EXPLAIN = "What does my ticket mean, what will it cost, how many points is it, and what are my options?"
Q_SPEEDING = "How much is a speeding ticket and how many points does it add?"
Q_COMPARE = ("Compare my options (pay the fine, go to traffic school, or contest the ticket) in a table "
             "showing the cost, the points and what happens next for each.")
Q_POINTS = "How many points would this add to my licence, how long do they stay, and when could my licence be suspended?"
Q_DEADLINE = "What happens if I miss the due date on my ticket?"
FOLLOW_UPS = [Q_COMPARE, "Will this raise my insurance?", Q_DEADLINE,
              "Can I pay in instalments if I can't afford the fine?", "Can I go to traffic school for this?", Q_POINTS]

CSS = """
<style>
.block-container {max-width: 1120px; padding-top: 4.2rem; padding-bottom: 6rem;}
[data-testid="stChatMessage"] h1, [data-testid="stChatMessage"] h2 {font-size: 1.3rem; margin-top: .9rem;}
[data-testid="stChatMessage"] h3, [data-testid="stChatMessage"] h4 {font-size: 1.08rem; margin-top: .7rem;}
[data-testid="stChatMessage"] table {font-size: .92rem;}
.docs {font-size: .84rem; opacity: .8; line-height: 1.7; word-break: break-all;}
.hero {position: relative; overflow: hidden; border-radius: 1.25rem; padding: 2.1rem 2.4rem 1.8rem;
  color: #fff; background: linear-gradient(130deg, #1E3A8A 0%, #2563EB 55%, #0EA5E9 100%);
  box-shadow: 0 18px 40px -22px rgba(37, 99, 235, .65);}
.hero .eyebrow {display: inline-flex; align-items: center; gap: .45rem; font-weight: 600; font-size: .82rem;
  letter-spacing: .02em; background: rgba(255,255,255,.16); padding: .3rem .8rem; border-radius: 999px;}
.hero h1 {color: #fff; font-size: 2.35rem; line-height: 1.12; font-weight: 800; letter-spacing: -.025em;
  margin: .8rem 0 .55rem; padding: 0;}
.hero p {color: rgba(255,255,255,.9); font-size: 1.04rem; line-height: 1.55; max-width: 44rem; margin: 0;}
.hero .chips {display: flex; flex-wrap: wrap; gap: .5rem; margin-top: 1.25rem;}
.hero .chips span {background: rgba(255,255,255,.13); border: 1px solid rgba(255,255,255,.28);
  padding: .32rem .8rem; border-radius: 999px; font-size: .84rem; font-weight: 500;}
.hero .art {position: absolute; right: 1.6rem; top: 50%; transform: translateY(-50%) rotate(-8deg);
  font-size: 7.5rem; opacity: .22; filter: saturate(1.4);}
.hero.slim {padding: 1rem 1.5rem;}
.hero.slim h1 {font-size: 1.35rem; margin: 0;}
.hero.slim .art {font-size: 3.2rem; right: 1.2rem;}
.step {font-size: .72rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: #3B82F6;
  margin-bottom: .1rem;}
.muted {opacity: .72; font-size: .88rem;}
.pipeline {display: flex; flex-direction: column; gap: .35rem; font-size: .88rem;}
.pipeline div {display: flex; gap: .55rem; align-items: baseline;}
.pipeline b {white-space: nowrap;}
@media (max-width: 640px) {
  .hero {padding: 1.4rem 1.3rem;} .hero h1 {font-size: 1.65rem;} .hero .art {display: none;}
  .block-container {padding-top: 3.6rem;}
}
</style>
"""


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
ss.setdefault("ticket", None)
ss.setdefault("ticket_name", "")
ss.setdefault("uploader_key", 0)


# ---------- helpers ----------

def md(text: str) -> str:
    """Escape $ so amounts like '$238 to $490' are not rendered as maths."""
    return (text or "").replace("$", "\\$")


def ask(question: str) -> None:
    ss.pending = question


def use_sample() -> None:
    ss.state = SAMPLE
    ss.load_sample = True


def new_conversation() -> None:
    ss.messages = []


def remove_uploads() -> None:
    clear_user_documents(store, ss.session_id)
    ss.uploads, ss.ticket, ss.ticket_name = [], None, ""
    ss.uploader_key += 1


def has_laws(code: str, with_library: list[str]) -> bool:
    return any(j in with_library for j in jurisdiction_chain(code))


def add_ticket(name: str, data: bytes, state: str) -> None:
    meta = {"kind": "ticket", "state": state, "session": ss.session_id}
    try:
        with st.spinner(f"Reading {name}…"):
            sections = load_document(name, data, meta)
            index_user_sections(store, sections, ss.session_id)
    except IngestionError as exc:
        st.error(str(exc))
        return
    ss.ticket_name = name
    ss.ticket = None
    try:
        with st.spinner("Pulling out the key facts…"):
            ss.ticket = extract_ticket("\n".join(s.text for s in sections)).model_dump()
    except LLMError as exc:
        st.warning(f"Your ticket was added, but the summary card could not be made: {exc}")


def log_feedback(i: int) -> None:
    rating = ss.get(f"fb_{i}")
    if rating is None:
        return
    record = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "rating": "up" if rating == 1 else "down",
              "state": ss.messages[i].get("state", ""),
              "question": ss.messages[i - 1]["content"] if i else "",
              "status": ss.messages[i]["result"].get("status")}
    try:
        with open(settings.data_dir / "feedback.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        log.exception("Could not save feedback")


def answer_as_markdown(question: str, res: dict, where: str) -> str:
    lines = ["# Traffic ticket answer", "",
             f"**Where:** {where}  ", f"**Saved:** {datetime.now():%B %d, %Y}", "",
             "## Question", "", question, "", "## Answer", "", res.get("answer", ""), ""]
    if res.get("citations"):
        lines += ["## Sources", ""]
        for c in res["citations"]:
            excerpt = " ".join(c["text"].split())[:500]
            lines += [f"**[{c['n']}] {c['source']}**", "", f"> {excerpt}…", ""]
    lines += ["---", "", f"_{DISCLAIMER}_", "", "Made with Traffic Ticket Explainer."]
    return "\n".join(lines)


# ---------- rendering ----------

def render_hero(slim: bool) -> None:
    if slim:
        st.html('<div class="hero slim"><h1>🚦 Traffic Ticket Explainer</h1><div class="art">🚦</div></div>')
        return
    st.html("""
<div class="hero">
  <div class="eyebrow">🚦 Traffic Ticket Explainer</div>
  <h1>Understand your traffic ticket<br>in plain English.</h1>
  <p>Pick where you got it, add a photo or PDF of your ticket, and ask anything. Every answer comes from
  official law documents, shows its sources and is fact-checked by an AI validator before you see it.</p>
  <div class="chips"><span>📚 Official law documents</span><span>🔎 Every fact cited</span>
  <span>✅ AI fact-checked</span><span>🔒 Your ticket stays private</span></div>
  <div class="art">🚦</div>
</div>""")


def render_ticket(info: dict) -> None:
    with st.container(border=True, key="ticket_card"):
        if not info.get("is_ticket"):
            st.markdown(f"**📄 {ss.ticket_name}**")
            st.caption("This file doesn't look like a ticket, so there's no summary card. "
                       "You can still ask questions about it.")
            return
        head, badge_col = st.columns([3, 1.4], vertical_alignment="center")
        head.markdown("#### 🎫 Your ticket")
        head.caption(f"Read from {ss.ticket_name}. Points, totals and options come from the law documents when you ask.")
        due = parse_date(info.get("due_date", ""))
        if due:
            label, color = deadline_label(days_left(due))
            badge_col.badge(label, icon=":material/schedule:", color=color, width="stretch")

        for v in info.get("violations") or []:
            c1, c2, c3 = st.columns([1.3, 4, 1.2], vertical_alignment="center")
            c1.badge(v.get("code") or "No code", color="blue")
            c2.markdown(md(v.get("description") or "—"))
            c3.markdown(f"**{md(v['fine'])}**" if v.get("fine") else ":gray[fine not printed]")

        violated = parse_date(info.get("violation_date", ""))
        facts = [("Date of violation", f"{violated:%b %d, %Y}" if violated else "—"),
                 ("Respond by", f"{due:%b %d, %Y}" if due else "Not printed"),
                 ("Total due", info.get("total_due") or "Not printed")]
        for col, (label, value) in zip(st.columns(3), facts):
            col.caption(label)
            col.markdown(f"**{md(value)}**")
        if info.get("court"):
            st.caption(f"🏛️ {info['court']}")
        if info.get("must_appear"):
            st.warning("Your ticket says you **must appear in court**. Paying online may not be enough.",
                       icon=":material/gavel:")

        with st.container(horizontal=True, gap="small"):
            st.button("Explain my ticket", icon=":material/auto_awesome:", type="primary",
                      on_click=ask, args=(Q_EXPLAIN,), key="ticket_explain")
            st.button("Compare my options", icon=":material/compare_arrows:", on_click=ask, args=(Q_COMPARE,),
                      key="ticket_compare")
            if due:
                st.download_button("Add due date to calendar", calendar_file(due, TicketInfo(**info)),
                                   file_name="ticket-due-date.ics", mime="text/calendar",
                                   icon=":material/event:", on_click="ignore", key="ticket_ics")


def render_quick_actions(state: str) -> None:
    st.markdown("#### What do you want to know?")
    cards = [
        ("🎫", "Explain my ticket", "What it means, the cost, the points and your options.",
         Q_EXPLAIN if ss.ticket else Q_SPEEDING),
        ("⚖️", "Compare my options", "Pay, traffic school or contest, side by side.", Q_COMPARE),
        ("📈", "Points and my licence", "How many points, how long they stay, when you'd be suspended.", Q_POINTS),
        ("⏰", "Missed the deadline?", "What happens if you're late, and what to do now.", Q_DEADLINE),
    ]
    if not ss.ticket:
        cards[0] = ("🚗", "Speeding tickets", "Typical fines and points for speeding here.", Q_SPEEDING)
    for row in (cards[:2], cards[2:]):
        for col, (icon, title, blurb, q) in zip(st.columns(2), row):
            with col.container(border=True):
                st.markdown(f"**{icon} {title}**")
                st.caption(blurb)
                st.button("Ask", key=f"qa_{title}", on_click=ask, args=(q,), icon=":material/arrow_forward:",
                          type="tertiary")


def render_result(res: dict, i: int, question: str, where: str, last: bool) -> None:
    label, color, icon = STATUS.get(res.get("status"), ("", "", ""))
    if label:
        meta = f" · {res['seconds']:.0f}s" if res.get("seconds") else ""
        st.badge(label + meta, icon=icon, color=color)
    st.markdown(md(res["answer"]))

    if res.get("citations"):
        with st.expander(f"📚 Sources ({len(res['citations'])})"):
            for c in res["citations"]:
                with st.container(border=True):
                    st.markdown(f"**[{c['n']}]** {md(c['source'])}")
                    excerpt = " ".join(c["text"].split())
                    st.caption(md(excerpt[:700] + ("…" if len(excerpt) > 700 else "")))
    if res.get("trace"):
        with st.expander("🤖 How the agents worked"):
            for t in res["trace"]:
                st.markdown(f"{AGENT_ICONS.get(t['agent'], '•')} **{t['agent']}** — {md(t['summary'])}")
                if t.get("detail", {}).get("queries"):
                    st.caption("Searched: " + md(" · ".join(t["detail"]["queries"])))

    if res.get("status") in {"answered", "partial", "not_found"}:
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.download_button("Save answer", answer_as_markdown(question, res, where),
                               file_name=f"ticket-answer-{i}.md", mime="text/markdown",
                               icon=":material/download:", type="tertiary", on_click="ignore", key=f"dl_{i}")
            st.feedback("thumbs", key=f"fb_{i}", on_change=log_feedback, args=(i,))

    if last and res.get("status") in {"answered", "partial", "not_found"}:
        asked = {m["content"] for m in ss.messages if m["role"] == "user"}
        options = [q for q in FOLLOW_UPS if q not in asked][:3]
        if options:
            st.caption("Ask next")
            with st.container(horizontal=True, gap="small"):
                for j, q in enumerate(options):
                    short = q if len(q) <= 60 else q.split("(")[0].strip()
                    st.button(short, key=f"fu_{i}_{j}", on_click=ask, args=(q,), icon=":material/chat_bubble:")


# ---------- page ----------

st.html(CSS)
render_hero(slim=bool(ss.messages))
st.space("small")

with_library = library_states()
setup_left, setup_right = st.columns([1.15, 1], gap="medium")
with setup_left.container(border=True):
    st.html('<div class="step">Step 1</div>')
    st.markdown("**Where did you get the ticket?**")
    state = st.pills("Where", list(JURISDICTIONS), key="state", label_visibility="collapsed",
                     format_func=lambda c: SHORT_LABELS.get(c, c) + ("" if has_laws(c, with_library) else " · no docs"))
    if state:
        if has_laws(state, with_library):
            with st.spinner(f"Loading {state_label(state)} law documents… (first time can take a minute)"):
                report = ensure_library(state, ss.lib_version)
            for err in report["errors"]:
                st.warning(err)
            n_docs = len(store.sources({"$and": [{"kind": "law"}, {"state": {"$in": jurisdiction_chain(state)}}]}))
            extra = ", including New York State law" if state == "NYC" else ""
            st.caption(f":material/library_books: {n_docs} law document{'s' if n_docs != 1 else ''} loaded{extra}.")
        else:
            st.warning(f"No law documents for {state_label(state)} yet, so answers can only describe your ticket.")
        if state == SAMPLE:
            st.caption(":material/science: Sample State is made-up data for trying the app. It is not real law.")
    else:
        st.caption("Answers only use that state's laws, so California rules never leak into a New Jersey answer.")

with setup_right.container(border=True):
    st.html('<div class="step">Step 2 · optional</div>')
    st.markdown("**Add your ticket**")
    exts = sorted(e.lstrip(".") for e in SUPPORTED_EXTENSIONS)
    upload = st.file_uploader("Photo, PDF, text, CSV or Excel", type=exts, disabled=not state,
                              key=f"ticket_upload_{ss.uploader_key}", label_visibility="collapsed")
    if upload and state and upload.file_id not in ss.uploads:
        ss.uploads.append(upload.file_id)
        add_ticket(upload.name, upload.getvalue(), state)
    if not ss.ticket_name:
        st.button("No ticket handy? Try a sample", icon=":material/science:", type="tertiary", on_click=use_sample)
    st.caption(":material/lock: Only you can see your upload. Remove it any time from the sidebar.")

if ss.pop("load_sample", False) and SAMPLE_TICKET.exists() and "sample" not in ss.uploads:
    ss.uploads.append("sample")
    add_ticket(SAMPLE_TICKET.name, SAMPLE_TICKET.read_bytes(), SAMPLE)

if ss.ticket:
    render_ticket(ss.ticket)

placeholder = "Ask anything about your ticket or a driving rule…" if state else "First choose where you got the ticket"
question = st.chat_input(placeholder, disabled=not state)
question = question or ss.pop("pending", None)

if state and not ss.messages and not question:
    render_quick_actions(state)

for i, m in enumerate(ss.messages):
    if m["role"] == "user":
        with st.chat_message("user", avatar=":material/person:"):
            st.markdown(md(m["content"]))
    else:
        with st.chat_message("assistant", avatar="🚦"):
            render_result(m["result"], i, ss.messages[i - 1]["content"] if i else "", m.get("state", ""),
                          last=i == len(ss.messages) - 1)

if question and state:
    where = state_label(state)
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(md(question))
    with st.chat_message("assistant", avatar="🚦"):
        progress = st.status("Checking your question…", expanded=True)
        started = time.time()

        def on_step(step: dict) -> None:
            progress.write(f"{AGENT_ICONS.get(step['agent'], '•')} **{step['agent']}** — {md(step['summary'])}")
            progress.update(label=NEXT_STEP.get(step["agent"], "Working…"))

        history = [{"role": m["role"], "content": m.get("content", "")} for m in ss.messages]
        res = answer_question(store, question, history, where=scope_filter(state, ss.session_id),
                              state_name=where, on_step=on_step)
        res["seconds"] = time.time() - started
        progress.update(label=f"Done in {res['seconds']:.0f}s", expanded=False,
                        state="error" if res.get("status") == "error" else "complete")
    ss.messages += [{"role": "user", "content": question},
                    {"role": "assistant", "content": res["answer"], "result": res, "state": where}]
    st.rerun()

# ---------- sidebar ----------
with st.sidebar:
    st.markdown("### 🚦 Ticket Explainer")
    st.button("New conversation", icon=":material/add_comment:", on_click=new_conversation, width="stretch",
              disabled=not ss.messages)

    st.markdown("#### How it works")
    st.html("""<div class="pipeline">
<div>🛡️ <span><b>Guardrail</b> blocks unsafe or manipulative questions.</span></div>
<div>🧭 <span><b>Planner</b> works out what you're asking and what to search.</span></div>
<div>🔎 <span><b>Retriever</b> searches your state's law documents and your ticket.</span></div>
<div>✍️ <span><b>Reasoner</b> writes the answer, citing every fact.</span></div>
<div>✅ <span><b>Validator</b> fact-checks each claim and sends it back if needed.</span></div>
</div>""")

    if state:
        st.markdown(f"#### Law library · {SHORT_LABELS.get(state, state)}")
        docs = store.sources({"$and": [{"kind": "law"}, {"state": {"$in": jurisdiction_chain(state)}}]})
        if docs:
            st.html('<div class="docs">' + "<br>".join(f"📄 {html.escape(d)}" for d in docs) + "</div>")
        else:
            st.caption("No documents yet.")
        with st.expander("Add official documents"):
            st.caption("Handbooks, vehicle code sections or fine schedules for this state.")
            law_files = st.file_uploader("Law documents", type=[e for e in exts if e not in {"jpg", "jpeg", "png", "webp"}],
                                         accept_multiple_files=True, key="law_upload", label_visibility="collapsed")
            if law_files and st.button(f"Add to {state_label(state)}", width="stretch"):
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

    if ss.uploads:
        st.markdown("#### Your uploads")
        if ss.ticket_name:
            st.caption(f":material/receipt_long: {ss.ticket_name}")
        st.button("Remove my uploads", icon=":material/delete:", on_click=remove_uploads, width="stretch")

    st.divider()
    st.caption("Built with Claude, LangGraph and Chroma · "
               "[Source code](https://github.com/kannandevarajgit-coder/traffic-ticket-explainer)")

st.caption(f"⚖️ {DISCLAIMER}")
