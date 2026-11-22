"""LangGraph workflow: guard -> planner -> retriever -> reasoner -> validator -> finalize.

Each agent is a graph node. The retriever is a tool-using agent; the validator can send the
flow back to the retriever once more when the draft is not grounded.
"""
from __future__ import annotations

import json
import logging
import operator
from typing import Annotated, Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from . import llm, prompts
from .chunking import cite
from .config import settings
from .guardrails import (
    DISCLAIMER,
    GuardrailViolation,
    check_question,
    looks_like_injection,
    strip_invalid_citations,
)
from .store import Hit, VectorStore

log = logging.getLogger(__name__)


# ---------- structured outputs ----------

class Plan(BaseModel):
    intent: Literal["documents", "greeting", "out_of_scope", "unsafe"]
    standalone_question: str = Field(description="The question rewritten to make sense without chat history")
    queries: list[str] = Field(description="1 to 4 search queries; empty unless intent is documents")
    reply: str = Field(description="Short reply to the user when intent is not documents; empty otherwise")


class Validation(BaseModel):
    verdict: Literal["grounded", "partial", "unsupported"]
    unsupported_claims: list[str]
    followup_queries: list[str]
    unsafe: bool


# ---------- state ----------

class State(TypedDict, total=False):
    question: str
    jurisdiction: str
    history: list[dict]
    plan: dict
    hits: dict  # chunk id -> {"text", "metadata", "distance"}
    queries_run: Annotated[list[str], operator.add]
    draft: str
    validation: dict
    attempts: int
    answer: str
    citations: list[dict]
    status: str  # answered | partial | not_found | refused | blocked | error | chat
    trace: Annotated[list[dict], operator.add]


def _step(agent: str, summary: str, detail: dict | None = None) -> dict:
    return {"agent": agent, "summary": summary, "detail": detail or {}}


# ---------- nodes ----------

def guard_node(state: State) -> State:
    try:
        q = check_question(state["question"])
    except GuardrailViolation as exc:
        return {"status": "blocked", "answer": str(exc), "trace": [_step("Guardrail", f"Blocked: {exc}")]}
    return {"question": q, "attempts": 0, "hits": {}, "trace": [_step("Guardrail", "Question passed input checks")]}


def planner_node(state: State) -> State:
    history = state.get("history") or []
    convo = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in history[-4:])
    prompt = (f"<history>\n{convo}\n</history>\n\n" if convo else "") + _where(state) + f"<question>\n{state['question']}\n</question>"
    plan = llm.structured(prompts.PLANNER, prompt, Plan, effort="low", max_tokens=4000)
    queries = [q.strip() for q in plan.queries if q.strip()][:4]
    if plan.intent == "documents" and not queries:
        queries = [plan.standalone_question or state["question"]]
    out: State = {
        "plan": {**plan.model_dump(), "queries": queries},
        "trace": [_step("Planner", f"Intent: {plan.intent}" + (f"; {len(queries)} search queries" if queries else ""),
                        {"queries": queries, "standalone_question": plan.standalone_question})],
    }
    if plan.intent != "documents":
        out["status"] = "refused" if plan.intent == "unsafe" else "chat"
        out["answer"] = plan.reply or "I can only help with questions about traffic tickets and driving rules."
    return out


SEARCH_TOOL = {
    "name": "search_documents",
    "description": "Semantic search over the uploaded driving-law documents. Returns the most similar passages with their source.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for, in plain words or a code/section number"},
            "source": {"type": "string", "description": "Optional exact file name to search only that file"},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    "strict": True,
}
LIST_TOOL = {
    "name": "list_documents",
    "description": "List the file names currently loaded.",
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}
MAX_TOOL_ROUNDS = 4


def make_retriever(store: VectorStore, where: dict | None = None):
    def run_search(query: str, source: str | None, hits: dict) -> tuple[str, int]:
        flt = where
        if source:
            flt = {"$and": [where, {"source": source}]} if where else {"source": source}
        found = [h for h in store.search(query, settings.top_k, flt) if h.distance <= settings.max_distance]
        new = 0
        lines = []
        for h in found:
            if h.id not in hits or h.distance < hits[h.id]["distance"]:
                new += h.id not in hits
                hits[h.id] = {"text": h.text, "metadata": h.metadata, "distance": h.distance}
            lines.append(f"- ({cite(h.metadata)}; distance {h.distance:.2f}) {h.text[:400]}")
        return ("\n".join(lines) if lines else "No relevant passages found."), new

    def retriever_node(state: State) -> State:
        hits = dict(state.get("hits") or {})
        attempt = state.get("attempts", 0) + 1
        plan = state["plan"]
        if attempt == 1:
            queries = plan["queries"]
            task = f"Question: {plan.get('standalone_question') or state['question']}\nPlanned queries:\n" + \
                "\n".join(f"- {q}" for q in queries)
        else:
            v = state.get("validation") or {}
            queries = v.get("followup_queries") or [state["question"]]
            task = (f"Question: {plan.get('standalone_question') or state['question']}\n"
                    f"A fact check found gaps: {json.dumps(v.get('unsupported_claims', []))}\n"
                    "Search for the missing facts with these queries and any better ones:\n" +
                    "\n".join(f"- {q}" for q in queries))

        # Always run the planned queries directly, so retrieval works even if the agent stops early.
        ran = []
        for q in queries:
            run_search(q, None, hits)
            ran.append(q)

        messages = [{"role": "user", "content": task + "\n\nThese queries were already run; their results are in your first tool results if you repeat them. Look for anything still missing."}]
        try:
            for _ in range(MAX_TOOL_ROUNDS):
                resp = llm.tool_turn(prompts.RETRIEVER, messages, [SEARCH_TOOL, LIST_TOOL], effort="low")
                messages.append({"role": "assistant", "content": resp.content})
                calls = [b for b in resp.content if b.type == "tool_use"]
                if not calls:
                    break
                results = []
                for call in calls:
                    if call.name == "search_documents":
                        args = call.input if isinstance(call.input, dict) else {}
                        query = str(args.get("query", ""))[:300]
                        out, _ = run_search(query, args.get("source"), hits)
                        ran.append(query)
                    elif call.name == "list_documents":
                        out = "\n".join(store.sources(where)) or "No documents loaded."
                    else:
                        out = f"Unknown tool {call.name}"
                    results.append({"type": "tool_result", "tool_use_id": call.id, "content": out})
                messages.append({"role": "user", "content": results})
        except llm.LLMError as exc:
            # Retrieval agent failing is not fatal: the planned queries already ran.
            log.warning("Retriever agent stopped early: %s", exc)

        summary = f"Attempt {attempt}: ran {len(ran)} searches, holding {len(hits)} relevant passages"
        return {"hits": hits, "attempts": attempt, "queries_run": ran,
                "trace": [_step("Retriever", summary, {"queries": ran})]}

    return retriever_node


def _where(state: State) -> str:
    j = state.get("jurisdiction")
    return f"<jurisdiction>{j}</jurisdiction>\n" if j else ""


def _ranked(hits: dict) -> list[dict]:
    """Best passages first; cap context to keep cost and noise down.

    No single document may fill more than two thirds of the slots, so a 200-page manual cannot crowd out
    a short, precise source such as a points table (found by the evaluation: NJ red-light camera points).
    """
    limit = max(settings.top_k * 2, 8)
    per_source = max(limit * 2 // 3, 1)
    picked, overflow, counts = [], [], {}
    for h in sorted(hits.values(), key=lambda h: h["distance"]):
        source = h["metadata"].get("source")
        if counts.get(source, 0) < per_source:
            picked.append(h)
            counts[source] = counts.get(source, 0) + 1
        else:
            overflow.append(h)
        if len(picked) == limit:
            break
    picked += overflow[: limit - len(picked)]
    return sorted(picked, key=lambda h: h["distance"])


def _context_block(passages: list[dict]) -> str:
    parts = []
    for i, p in enumerate(passages, 1):
        text = p["text"]
        if looks_like_injection(text):
            text = "[passage withheld: it contained instructions aimed at the assistant]"
        kind = "user's ticket" if p["metadata"].get("kind") == "ticket" else "law"
        parts.append(f'<passage n="{i}" kind="{kind}" source="{cite(p["metadata"])}">\n{text}\n</passage>')
    return "<context>\n" + "\n".join(parts) + "\n</context>"


def reasoner_node(state: State) -> State:
    passages = _ranked(state["hits"])
    question = state["plan"].get("standalone_question") or state["question"]
    prompt = f"{_context_block(passages)}\n\n{_where(state)}<question>\n{question}\n</question>"
    v = state.get("validation")
    if v and v.get("unsupported_claims"):
        prompt += ("\n\nA previous draft made these unsupported claims; do not repeat them unless the passages now "
                   "support them:\n" + "\n".join(f"- {c}" for c in v["unsupported_claims"]))
    draft = llm.text(prompts.REASONER, prompt)
    return {"draft": draft, "trace": [_step("Reasoner", f"Drafted an answer from {len(passages)} passages")]}


def validator_node(state: State) -> State:
    passages = _ranked(state["hits"])
    prompt = f"{_context_block(passages)}\n\n<question>\n{state['question']}\n</question>\n\n<draft>\n{state['draft']}\n</draft>"
    v = llm.structured(prompts.VALIDATOR, prompt, Validation, effort="low", max_tokens=4000)
    return {"validation": v.model_dump(),
            "trace": [_step("Validator", f"Verdict: {v.verdict}" + (f"; {len(v.unsupported_claims)} unsupported claims" if v.unsupported_claims else ""),
                            v.model_dump())]}


def finalize_node(state: State) -> State:
    if state.get("status") in {"blocked", "refused", "chat", "error"}:
        return {}
    if not state.get("hits"):
        return {"status": "not_found",
                "answer": "I couldn't find anything about this in the loaded documents. "
                          "Try different words, the exact code printed on your ticket, or upload the relevant handbook or fine schedule.",
                "citations": [], "trace": [_step("Finalize", "No relevant passages")]}
    v = state.get("validation") or {}
    if v.get("unsafe"):
        return {"status": "refused", "answer": "I can't help with that.", "citations": [],
                "trace": [_step("Finalize", "Validator flagged the draft as unsafe")]}
    passages = _ranked(state["hits"])
    answer, used = strip_invalid_citations(state.get("draft", ""), len(passages))
    citations = [{"n": n, "source": cite(passages[n - 1]["metadata"]), "text": passages[n - 1]["text"]} for n in used]
    verdict = v.get("verdict", "unsupported")
    if verdict == "unsupported":
        status = "not_found"
        answer = ("I found related passages but could not confirm an answer from them, so I won't guess. "
                  "Check the cited sources below or the official vehicle code.")
    elif verdict == "partial":
        status = "partial"
        answer += "\n\n_Note: parts of this answer could not be fully confirmed from the documents._"
    else:
        status = "answered"
    return {"status": status, "answer": answer, "citations": citations,
            "trace": [_step("Finalize", f"Status: {status}; {len(citations)} citations")]}


# ---------- routing ----------

def after_guard(state: State) -> str:
    return "finalize" if state.get("status") == "blocked" else "planner"


def after_planner(state: State) -> str:
    return "retriever" if state["plan"]["intent"] == "documents" else "finalize"


def after_retriever(state: State) -> str:
    return "reasoner" if state.get("hits") else "finalize"


def after_validator(state: State) -> str:
    v = state.get("validation") or {}
    if v.get("verdict") != "grounded" and not v.get("unsafe") and state.get("attempts", 0) < settings.max_retrievals:
        return "retriever"
    return "finalize"


def build_graph(store: VectorStore, where: dict | None = None):
    g = StateGraph(State)
    g.add_node("guard", guard_node)
    g.add_node("planner", planner_node)
    g.add_node("retriever", make_retriever(store, where))
    g.add_node("reasoner", reasoner_node)
    g.add_node("validator", validator_node)
    g.add_node("finalize", finalize_node)
    g.add_edge(START, "guard")
    g.add_conditional_edges("guard", after_guard, ["planner", "finalize"])
    g.add_conditional_edges("planner", after_planner, ["retriever", "finalize"])
    g.add_conditional_edges("retriever", after_retriever, ["reasoner", "finalize"])
    g.add_edge("reasoner", "validator")
    g.add_conditional_edges("validator", after_validator, ["retriever", "finalize"])
    g.add_edge("finalize", END)
    return g.compile()


def answer_question(store: VectorStore, question: str, history: list[dict] | None = None,
                    where: dict | None = None, state_name: str | None = None,
                    on_step: Callable[[dict], None] | None = None) -> dict:
    """Run the full agent graph. Never raises for model/API problems; returns status 'error' instead.

    `where` limits retrieval (for example to one state's laws plus the user's ticket).
    `on_step` is called with each trace step as soon as its agent finishes (for live progress in the UI).
    """
    graph = build_graph(store, where)
    inputs = {"question": question, "history": history or [], "trace": [], "queries_run": [],
              "jurisdiction": state_name or ""}
    try:
        result = None
        for mode, chunk in graph.stream(inputs, {"recursion_limit": 25}, stream_mode=["updates", "values"]):
            if mode == "values":
                result = chunk
            elif on_step:
                for update in chunk.values():
                    for step in (update or {}).get("trace", []):
                        try:
                            on_step(step)
                        except Exception:  # a display problem must never stop the answer
                            log.exception("on_step callback failed")
        if result is None:
            raise RuntimeError("Agent graph produced no state")
    except llm.Refused:
        return {"status": "refused", "answer": "I can't help with that request.", "citations": [], "trace": []}
    except llm.LLMError as exc:
        return {"status": "error", "answer": str(exc), "citations": [], "trace": []}
    except Exception:  # never show a stack trace to the user
        log.exception("Agent graph failed")
        return {"status": "error", "answer": "Something went wrong while answering. Please try again.",
                "citations": [], "trace": []}
    result.setdefault("citations", [])
    result["disclaimer"] = DISCLAIMER
    return result
