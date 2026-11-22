"""Runs the evaluation questions against the real Claude API and writes evaluation/results.md.

Usage:  python -m evaluation.run_eval            (needs ANTHROPIC_API_KEY; costs a few dollars)
        python -m evaluation.run_eval --only S1 NY1
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

from docqa.agents import answer_question
from docqa.library import add_user_document, clear_user_documents, index_state_library, scope_filter, state_label
from docqa.store import VectorStore

HERE = Path(__file__).parent
ROOT = HERE.parent


def check(item: dict, res: dict) -> list[str]:
    """Return the reasons a result failed (empty list = pass)."""
    problems = []
    answer = res.get("answer", "").lower()
    if res.get("status") not in item["status"]:
        problems.append(f"status {res.get('status')} not in {item['status']}")
    for group in item.get("must_include", []):
        if not any(word.lower() in answer for word in group):
            problems.append(f"missing one of {group}")
    for bad in item.get("must_not_include", []):
        if bad.lower() in answer:
            problems.append(f"contains '{bad}'")
    if res.get("status") == "answered" and not res.get("citations"):
        problems.append("answered without citations")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="Question ids to run")
    args = parser.parse_args()

    items = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    if args.only:
        items = [i for i in items if i["id"] in args.only]
    store = VectorStore()
    rows, details = [], []
    for item in items:
        index_state_library(store, item["state"])
        session = None
        if item.get("ticket"):
            session = uuid.uuid4().hex
            path = ROOT / "sample_docs" / item["ticket"]
            add_user_document(store, path.name, path.read_bytes(), item["state"], session)
        started = time.time()
        res = answer_question(store, item["question"], where=scope_filter(item["state"], session),
                              state_name=state_label(item["state"]))
        seconds = time.time() - started
        if session:
            clear_user_documents(store, session)
        problems = check(item, res)
        passed = not problems
        print(f"{'PASS' if passed else 'FAIL'}  {item['id']:<5} {res.get('status'):<10} {seconds:5.1f}s  "
              f"{'; '.join(problems)}", flush=True)
        retried = sum(1 for t in res.get("trace", []) if t["agent"] == "Retriever") > 1
        rows.append({**item, "result": res.get("status"), "passed": passed, "problems": problems,
                     "seconds": seconds, "citations": len(res.get("citations", [])), "retried": retried})
        details.append((item, res))

    write_report(rows, details)


def write_report(rows: list[dict], details: list) -> None:
    passed = sum(r["passed"] for r in rows)
    avg = sum(r["seconds"] for r in rows) / max(len(rows), 1)
    lines = [
        "# Evaluation results", "",
        f"Run on {datetime.now():%Y-%m-%d %H:%M} against the real Claude API "
        f"(`python -m evaluation.run_eval`). Questions and expected facts: `evaluation/questions.json`.", "",
        f"**{passed} of {len(rows)} passed** · average {avg:.0f} s per question · "
        f"{sum(r['retried'] for r in rows)} answers used the validator's second retrieval round.", "",
        "A question passes when the status is one of the expected ones, every group of key facts appears in "
        "the answer (any one word from each group), and answered questions carry citations.", "",
        "| ID | Group | State | Question | Expected | Got | Citations | Time | Result |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        result = "✅ Pass" if r["passed"] else "❌ " + "; ".join(r["problems"])
        lines.append(f"| {r['id']} | {r['group']} | {r['state']} | {r['question']} | {' / '.join(r['status'])} | "
                     f"{r['result']} | {r['citations']} | {r['seconds']:.0f}s | {result} |")
    lines += ["", "## Answers", ""]
    for item, res in details:
        lines += [f"### {item['id']}: {item['question']}", "",
                  f"Status: **{res.get('status')}**" + (f" · ticket: `{item['ticket']}`" if item.get("ticket") else ""),
                  "", res.get("answer", "").strip(), ""]
    (HERE / "results.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{passed}/{len(rows)} passed. Report: evaluation/results.md")


if __name__ == "__main__":
    main()
