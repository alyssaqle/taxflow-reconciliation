# Reviewer timing pilot: manual vs TaxFlow-assisted reconciliation

**Goal:** measure real review time and decision accuracy for 3–5 reviewers. No time-savings figure may be
claimed until these sessions have actually run and `python -m pilot.analyze` has produced a report.

## What you need

- 3–5 reviewers with basic accounts-payable or tax-operations familiarity: classmates, colleagues, or a
  study group. Record each reviewer's experience level; don't record their names in the logs.
- One laptop with this repo, the `.venv`, and the Azure settings. The settings are only needed once, to record
  TaxFlow's results; reviewers never need them.
- About 45–60 minutes per reviewer: 20 tasks plus a short briefing.

## One-time setup (coordinator)

```bash
python -m pilot.generate_tasks        # already done; regenerates the same tasks (fixed seed)
python -m pilot.record                # records the real live TaxFlow result for each of the 20 tasks
```

The assisted condition shows these recorded results, so every reviewer sees the same TaxFlow output.

## Assignment (counterbalanced)

Give each reviewer a slot. The slot sets which task set they do first and with which method. Set A and set B
have the same mix of 10 task types, and task order within a block is shuffled per slot.

| Slot | Block 1 | Block 2 |
|---|---|---|
| 1 | Set A · manual | Set B · assisted |
| 2 | Set A · assisted | Set B · manual |
| 3 | Set B · manual | Set A · assisted |
| 4 | Set B · assisted | Set A · manual |
| 5 | Set A · manual | Set B · assisted |

Use slots 1–4 first, so that both set and method order are balanced.

## Briefing script (read aloud, about 3 minutes)

"You'll review 20 synthetic invoices against an accounting ledger. For each one, find the matching ledger
entry, check the vendor, invoice number, date, currency, and total against it, check that the invoice's own
arithmetic adds up, write a short note, and decide either **Approve** or **Needs follow-up**. Approve only if
everything agrees and nothing is missing.

In one block you'll work **manually**, with the invoice and the full ledger table. In the other you'll see
**TaxFlow's report** with the form pre-filled; verify it and correct anything that's wrong.

Accuracy matters as much as speed. The timer starts when you press *Start task* and stops when you press
*Submit decision*, so take breaks only between tasks. You may use any calculator. Please don't discuss the
tasks with other reviewers."

Before timing starts, let each reviewer try one practice invoice in the main app (the "Matched" sample). This
isn't logged.

## Running a session

```bash
python -m streamlit run pilot/pilot_app.py
```

Enter the reviewer ID (`R1`, `R2`, …) and slot, then choose **Start session**. Each submission is appended to
`pilot_logs/<ID>.jsonl`, which is git-ignored. Don't edit the logs.

## After all sessions

```bash
python -m pilot.analyze                # writes reports/pilot-timing-<timestamp>.md
```

The report includes:

- reviewers and completed tasks;
- mean and median time per condition;
- the percentage time reduction;
- correct decisions per hour;
- missed discrepancies;
- assisted corrections (fixed vs. introduced errors).

Report the numbers as they come out, including when assisted is slower or less accurate.

## Validity notes

- **Tasks:** the tasks are synthetic, with a fixed mix; real invoices vary more.
- **Recorded output:** TaxFlow's output was recorded once and doesn't vary between reviewers. Any TaxFlow
  errors are left in place on purpose; catching them is part of the measured review work.
- **Sample size:** 3–5 reviewers is a pilot. Present the result as "in a pilot with N reviewers", not as a
  general productivity claim.
