"""Analyze pilot timing logs. Usage: python -m pilot.analyze

Reads pilot_logs/*.jsonl and pilot/answers.json. If no sessions have been logged, the report says
"Not measured" and contains no time-savings figure. Nothing is simulated or estimated.

Definitions:
* Task time: seconds from "Start task" to "Submit decision" (covers lookup, evidence checks,
  corrections, documentation, decision).
* Correct decision: Approve / Needs follow-up equals the answer key.
* Fully correct: correct decision AND ledger outcome AND every expected discrepancy marked.
* Missed discrepancy: an expected discrepancy type not marked.
* Correct decisions per hour: correct decisions / total hours spent in that condition.
* Time reduction: (manual - assisted) / manual, on per-reviewer medians averaged across reviewers who
  completed both conditions, and on pooled means.
* Corrections (assisted): submissions where the reviewer changed TaxFlow's pre-filled answer; split into
  corrections that fixed a TaxFlow error vs. changes that introduced one.
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGS = ROOT.parent / "pilot_logs"
REPORTS = ROOT.parent / "reports"


def main() -> None:
    answers = json.loads((ROOT / "answers.json").read_text())
    recs = []
    for p in sorted(LOGS.glob("*.jsonl")) if LOGS.exists() else []:
        recs += [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"pilot-timing-{ts}.md"
    if not recs:
        out.write_text("# Reviewer timing pilot\n\n**Status: Not measured.** No pilot sessions have been logged. "
                       "No time-savings or productivity figure is reported.\n")
        print(f"Not measured (no logs). Wrote {out}")
        return
    rows = []
    for r in recs:
        a = answers[r["task_id"]]
        pre = r.get("prefill") or {}
        decision_ok = r["decision"] == a["expected_decision"]
        missed = sorted(set(a["expected_discrepancies"]) - set(r["discrepancies"]))
        full_ok = decision_ok and r["outcome"] == a["expected_outcome"] and not missed
        prefill_ok = bool(pre) and pre.get("decision") == a["expected_decision"] and pre.get("outcome") == a["expected_outcome"] \
            and not (set(a["expected_discrepancies"]) - set(pre.get("discrepancies", [])))
        rows.append({**r, "decision_ok": decision_ok, "full_ok": full_ok, "missed": missed, "prefill_ok": prefill_ok})
    reviewers = sorted({r["reviewer"] for r in rows})
    L = ["# Reviewer timing pilot", "", f"Generated {ts}. Synthetic tasks (pilot/data); real human reviewers.", "",
         f"**Reviewers:** {len(reviewers)} ({', '.join(reviewers)}) · **Submitted tasks:** {len(rows)}", "",
         "| Condition | Tasks | Mean s | Median s | Correct decisions | Fully correct | Missed discrepancies | Correct decisions / hour |",
         "|---|---|---|---|---|---|---|---|"]
    stats = {}
    for cond in ("manual", "assisted"):
        rs = [r for r in rows if r["condition"] == cond]
        if not rs:
            L.append(f"| {cond} | 0 | — | — | — | — | — | — |")
            continue
        secs = [r["seconds"] for r in rs]
        cd = sum(r["decision_ok"] for r in rs)
        stats[cond] = {"mean": statistics.mean(secs), "median": statistics.median(secs)}
        L.append(f"| {cond} | {len(rs)} | {statistics.mean(secs):.1f} | {statistics.median(secs):.1f} | {cd}/{len(rs)} | "
                 f"{sum(r['full_ok'] for r in rs)}/{len(rs)} | {sum(len(r['missed']) for r in rs)} | "
                 f"{cd / (sum(secs) / 3600):.1f} |")
    both = [rv for rv in reviewers if {r["condition"] for r in rows if r["reviewer"] == rv} == {"manual", "assisted"}]
    if both and "manual" in stats and "assisted" in stats:
        per = []
        for rv in both:
            m = statistics.median(r["seconds"] for r in rows if r["reviewer"] == rv and r["condition"] == "manual")
            a = statistics.median(r["seconds"] for r in rows if r["reviewer"] == rv and r["condition"] == "assisted")
            per.append((m - a) / m)
        L += ["", f"**Time reduction (assisted vs manual):** mean of per-reviewer median reductions "
              f"{100 * statistics.mean(per):.1f}% (n = {len(both)} reviewers with both conditions); pooled mean "
              f"{100 * (stats['manual']['mean'] - stats['assisted']['mean']) / stats['manual']['mean']:.1f}%."]
    else:
        L += ["", "**Time reduction:** not computed (no reviewer has completed both conditions)."]
    ar = [r for r in rows if r["condition"] == "assisted"]
    if ar:
        changed = [r for r in ar if r.get("changed_prefill")]
        fixed = sum(1 for r in changed if not r["prefill_ok"] and r["full_ok"])
        broke = sum(1 for r in changed if r["prefill_ok"] and not r["full_ok"])
        L += ["", f"**Assisted corrections:** {len(changed)}/{len(ar)} submissions changed TaxFlow's pre-filled answer; "
              f"{fixed} fixed a TaxFlow error, {broke} introduced an error. TaxFlow pre-fill fully correct on "
              f"{sum(r['prefill_ok'] for r in ar)}/{len(ar)} assisted submissions."]
    order = {(r["reviewer"], r["block"]): r["condition"] for r in rows}
    L += ["", "**Order:** " + "; ".join(f"{rv}: " + " → ".join(order.get((rv, b), "?") for b in (1, 2)) for rv in reviewers),
          "", "Limitations: small sample; synthetic tasks; reviewers' prior familiarity with TaxFlow varies; "
          "assisted results were recorded live once before the sessions."]
    out.write_text("\n".join(L) + "\n")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
