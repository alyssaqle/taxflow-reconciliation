"""Reviewer timing pilot: manual vs TaxFlow-assisted reconciliation.

Run locally (not part of the public demo):   python -m streamlit run pilot/pilot_app.py

Each reviewer completes 20 tasks: one set (A or B) manually and the other assisted, in a
counterbalanced order (see SCHEDULE). The timer starts when the reviewer presses "Start task" and
stops on "Submit decision", so it covers lookup, evidence checks, corrections, documentation, and the
decision. Logs are appended to pilot_logs/<reviewer>.jsonl (git-ignored). Answers are never shown.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import random
import sys
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from taxflow.models import RunResult  # noqa: E402

DATA = ROOT / "data"
LOGS = ROOT.parent / "pilot_logs"
OUTCOMES = ["Matched", "Discrepancy found", "No matching entry", "Ambiguous match", "Needs clarification"]
DISCREPANCIES = ["amount", "currency", "date", "arithmetic", "ambiguous", "no_entry", "missing_field"]
# Reviewer slot -> [(set, condition), (set, condition)]: balances set and method order.
SCHEDULE = {
    1: [("A", "manual"), ("B", "assisted")],
    2: [("A", "assisted"), ("B", "manual")],
    3: [("B", "manual"), ("A", "assisted")],
    4: [("B", "assisted"), ("A", "manual")],
    5: [("A", "manual"), ("B", "assisted")],
    6: [("B", "assisted"), ("A", "manual")],
}

st.set_page_config(page_title="TaxFlow pilot", layout="wide")


def plan(slot: int) -> list[dict]:
    tasks = json.loads((DATA / "tasks.json").read_text())
    rng = random.Random(1000 + slot)
    out = []
    for block, (set_name, cond) in enumerate(SCHEDULE[slot], 1):
        ids = [t["task_id"] for t in tasks if t["set"] == set_name]
        rng.shuffle(ids)
        out += [{"task_id": i, "set": set_name, "condition": cond, "block": block} for i in ids]
    return out


def log(reviewer: str, rec: dict) -> None:
    LOGS.mkdir(exist_ok=True)
    with (LOGS / f"{reviewer}.jsonl").open("a") as f:
        f.write(json.dumps(rec) + "\n")


def ledger_rows():
    import csv
    with (DATA / "pilot_ledger.csv").open() as f:
        return list(csv.DictReader(f))


def show_invoice(task_id: str) -> None:
    text = (DATA / "invoices" / f"{task_id}.txt").read_text()
    st.markdown("**Invoice**")
    st.code(text, language=None)


def show_taxflow(task_id: str) -> RunResult | None:
    p = ROOT / "recorded" / f"{task_id}.json"
    if not p.exists():
        st.error("No TaxFlow result recorded for this task. Run `python -m pilot.record` first.")
        return None
    r = RunResult.model_validate_json(p.read_text())
    st.markdown(f"**TaxFlow report** · ledger: **{r.reconciliation_outcome}** · arithmetic: **{r.arithmetic_status}** · "
                f"processing: {r.workflow_status}")
    d = r.extracted_fields
    if d:
        st.dataframe([{"Field": f, "Value": d.scalar(f).value, "Source quote": d.scalar(f).evidence.quote if d.scalar(f).evidence else "",
                       "Source": (f"L{d.scalar(f).evidence.line_start} ({d.scalar(f).evidence.status})" if d.scalar(f).evidence else "")}
                      for f in ("vendor_name", "invoice_number", "invoice_date", "currency", "total", "subtotal", "tax")],
                     hide_index=True, width="stretch")
    if r.ledger_entry:
        st.write(f"Compared ledger entry: **{r.ledger_entry.ledger_entry_id}** (CSV row {r.ledger_entry.row_number})")
    if r.ledger_candidates and not r.ledger_entry:
        st.write("Candidates: " + ", ".join(c.ledger_entry_id for c in r.ledger_candidates))
    if r.comparison:
        st.dataframe([{"Field": c.field, "Invoice": c.invoice_value, "Ledger": c.ledger_value, "Result": c.status,
                       "Difference": c.difference or ""} for c in r.comparison], hide_index=True, width="stretch")
    for f in r.findings:
        st.markdown(f"- {'BLOCKING' if f.blocking else 'NOTE'} `{html.escape(f.code)}` {html.escape(f.message)}")
    return r


def prefill(r: RunResult | None) -> dict:
    if r is None:
        return {}
    codes = {f.code for f in r.findings}
    disc = [k for k, c in (("amount", "LEDGER_AMOUNT_MISMATCH"), ("currency", "LEDGER_CURRENCY_MISMATCH"),
                           ("date", "LEDGER_DATE_MISMATCH"), ("ambiguous", "LEDGER_AMBIGUOUS"), ("no_entry", "LEDGER_NO_MATCH"),
                           ("missing_field", "MISSING_FIELD")) if c in codes]
    if codes & {"ITEM_MISMATCH", "SUBTOTAL_MISMATCH", "TOTAL_MISMATCH"}:
        disc.append("arithmetic")
    return {"entry": r.ledger_entry.ledger_entry_id if r.ledger_entry else "", "outcome": r.reconciliation_outcome,
            "discrepancies": disc, "decision": "Approve" if r.can_approve else "Needs follow-up"}


def main() -> None:
    st.title("TaxFlow reviewer pilot")
    s = st.session_state
    if "plan" not in s:
        st.markdown("Enter the reviewer ID and slot given by the pilot coordinator. Work at a normal pace; "
                    "accuracy matters as much as speed. Do not discuss tasks with other reviewers.")
        rid = st.text_input("Reviewer ID (e.g. R1)")
        slot = st.selectbox("Slot", list(SCHEDULE))
        if st.button("Start session", disabled=not rid.strip()):
            s.reviewer, s.slot, s.plan, s.i, s.started = rid.strip(), slot, plan(slot), 0, None
            st.rerun()
        return
    if s.i >= len(s.plan):
        st.success("All tasks complete. Thank you! Please tell the coordinator.")
        return
    task = s.plan[s.i]
    st.caption(f"Reviewer {s.reviewer} · task {s.i + 1} of {len(s.plan)} · block {task['block']} · "
               f"method: **{task['condition'].upper()}**")
    if s.started is None:
        st.info("Manual: use the invoice and the ledger table; any calculator is fine.\n\n"
                "Assisted: TaxFlow's report is shown and the form is pre-filled; verify and correct it as needed.")
        if st.button("Start task", type="primary"):
            s.started = time.time()
            s.started_iso = dt.datetime.now(dt.timezone.utc).isoformat()
            st.rerun()
        return
    left, right = st.columns([1, 1.3], gap="large")
    with left:
        show_invoice(task["task_id"])
    with right:
        r = show_taxflow(task["task_id"]) if task["condition"] == "assisted" else None
        st.markdown("**Accounting ledger** (search with the table's search icon)")
        st.dataframe(ledger_rows(), hide_index=True, width="stretch", height=260)
    pre = prefill(r) if task["condition"] == "assisted" else {}
    with st.form(f"f-{s.i}"):
        entry = st.text_input("Matched ledger entry ID (blank if none or ambiguous)", value=pre.get("entry", ""))
        outcome = st.selectbox("Ledger outcome", OUTCOMES,
                               index=OUTCOMES.index(pre["outcome"]) if pre.get("outcome") in OUTCOMES else 0)
        disc = st.multiselect("Discrepancies / issues found", DISCREPANCIES, default=pre.get("discrepancies", []))
        decision = st.radio("Decision", ["Approve", "Needs follow-up"], horizontal=True,
                            index=["Approve", "Needs follow-up"].index(pre["decision"]) if pre.get("decision") else 1)
        note = st.text_area("Note (document your findings)")
        if st.form_submit_button("Submit decision", type="primary"):
            end = time.time()
            log(s.reviewer, {"reviewer": s.reviewer, "slot": s.slot, "position": s.i + 1, **task,
                             "started_at": s.started_iso, "seconds": round(end - s.started, 2),
                             "entry_id": entry.strip() or None, "outcome": outcome, "discrepancies": sorted(disc),
                             "decision": decision, "note": note, "prefill": pre or None,
                             "changed_prefill": bool(pre) and (entry.strip() != pre.get("entry", "") or outcome != pre.get("outcome")
                                                               or sorted(disc) != sorted(pre.get("discrepancies", []))
                                                               or decision != pre.get("decision"))})
            s.i += 1
            s.started = None
            st.rerun()


main()
