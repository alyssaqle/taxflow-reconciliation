# TaxFlow: Invoice-to-Ledger Reconciliation Agent

A tax or finance analyst receives a client's invoices and an accounting spreadsheet. They need to confirm
that **each invoice agrees with its accounting entry** and find any discrepancies that need follow-up.

TaxFlow reads the invoice and extracts its key fields, citing the source line for each value. It then finds the
matching ledger entry, compares the two in Python, and checks the invoice's own arithmetic. The result is an
**evidence-backed exception report. A person makes the review decision.**

> Portfolio prototype built for a Tax Technology and Transformation analyst application. It is independent, with
> no affiliation with any firm implied, and uses synthetic data only. TaxFlow does not file taxes, calculate tax
> liability, pay invoices, post journal entries, certify compliance, or send messages.

**The key distinction.** An invoice states subtotal 800.00, tax 80.00, total **950.00**, and the ledger records
a gross amount of **950.00**. TaxFlow reports:

- **Ledger reconciliation: Matched.** The stated total agrees with the gross amount.
- **Invoice arithmetic: Inconsistent.** 800.00 + 80.00 = 880.00, so the stated total is 70.00 too high
  (`TOTAL_MISMATCH`, blocking).

The stated total is never silently replaced by the calculated one. Approval stays disabled, and the recommended
decision is *Needs follow-up*.

## Status

| Requirement | Implemented | Offline tests | Live verified | Deployed |
|---|---|---|---|---|
| v1 invoice intake (tag `v1-invoice-intake`) | ✅ | ✅ | ✅ Azure OpenAI `gpt-4.1-mini` | ⏳ |
| v2 ledger CSV validation, template, sample ledger | ✅ | ✅ | ✅ | ⏳ |
| v2 matching, comparison, outcomes, separate arithmetic check | ✅ | ✅ | ✅ 11 dev samples, recorded | ⏳ |
| v2 agent with 5 tools, outcome-dependent required tools, 8-request budget | ✅ | ✅ | ✅ | n/a (public demo is replay only) |
| v2 reconciliation UI, review decision, JSON/CSV export | ✅ | ✅ | ✅ | ⏳ |
| v2 29-case held-out benchmark | ✅ | ✅ | ✅ first run saved | n/a |

## Workflow

1. Choose a synthetic invoice and the sample ledger. In local live mode you can instead upload a TXT invoice and
   an accounting CSV.
2. The agent extracts **vendor, invoice number, invoice date, currency, and stated total**, plus subtotal, tax,
   and line items for the arithmetic check. Each value cites a page, line range, and exact quote, all verified
   in Python.
3. Python searches the ledger for candidates, compares the invoice with the single match, and checks the
   invoice's arithmetic.
4. The report shows the extracted fields, the ledger entry with its ID and CSV row, a side-by-side comparison,
   exceptions, and policy-referenced follow-up.
5. The analyst adds a note, chooses **Approve** or **Needs follow-up**, and downloads JSON or CSV.

### Four separate statuses

| Status | Values | Meaning |
|---|---|---|
| Processing | Complete · Failed · Incomplete | Did the run finish? Execution failures are never shown as results. |
| Ledger reconciliation | Matched · Discrepancy found · No matching entry · Ambiguous match · Needs clarification · Unsupported document · Incomplete | What the ledger comparison found |
| Invoice arithmetic | Consistent · Inconsistent · Partially checked · Not checked | The invoice's own math, separate from the ledger |
| Human review | Unreviewed · Approved · Needs follow-up | The analyst's decision. A note never removes a finding. |

**Approve** is enabled only when processing is Complete and there are no blocking exceptions. A new invoice,
a new ledger, or a re-run resets the decision.

## Accounting CSV

```
ledger_entry_id,invoice_number,vendor_name,invoice_date,currency,gross_amount
```

Download the template and the fictional sample ledger in the app, or use
[samples/ledger/](samples/ledger/). A file is checked before any processing and rejected as a whole if any check
fails:

- exact column names, with no duplicates or extras;
- `YYYY-MM-DD` dates;
- supported ISO 4217 currencies (maintained list from `pycountry`, excluding metals, test codes, and fund codes);
- nonnegative `gross_amount` with at most 2 decimals and no thousands separators;
- unique `ledger_entry_id`, and non-empty invoice number and vendor;
- UTF-8, at most 2 MB and 5,000 rows.

`gross_amount` includes tax. MVP assumption: one entry per invoice. Split postings and credit notes are out of
scope; a credit note is routed as an unsupported document.

## Matching and comparison rules ([taxflow/matching.py](taxflow/matching.py))

- **Candidates**: entries whose invoice number **and** vendor name equal the invoice's, after trimming,
  collapsing whitespace, and ignoring case. Nothing else is normalized (no punctuation stripping) and nothing is
  fuzzy-matched. **An equal amount never selects a record.** All candidates are returned.
- **One candidate:** compare **currency first** (never converted). If the currencies differ, the amounts are
  not compared, and the mismatch is a blocking discrepancy. Otherwise compare the stated total with
  `gross_amount` using `Decimal`, with a 0.01 tolerance (|difference| ≤ 0.01 agrees), then compare the dates.
- **Matched** requires all three comparisons to complete and agree. An incomplete comparison (for example a
  missing invoice date) gives *Needs clarification*, never *Matched*.
- **Several candidates** gives *Ambiguous match* (none selected). **None** gives *No matching entry*. A
  **missing invoice number or vendor** gives *Needs clarification* (the ledger is not searched).

### Required fields and blocking

- **Required fields:** vendor, invoice number, invoice date, an explicitly stated supported currency (a "$"
  alone is not enough), and the stated total. A missing required field is blocking.
- **Arithmetic inputs:** when subtotal, tax, or line items are missing, the arithmetic is *Not checked* or
  *Partially checked* and a non-blocking `ARITHMETIC_NOT_CHECKED` note appears in the report and the export.
  Discounts, shipping, and similar adjustments add a non-blocking `UNSUPPORTED_STRUCTURE` note.
- **All other exceptions are blocking:** ledger exceptions, arithmetic mismatches, invalid or ambiguous values,
  and unverified evidence. Follow-up text comes from
  [policies/reconciliation_policy.md](policies/reconciliation_policy.md), a fictional policy with stable
  `TF-POL-xxx` IDs.

## Agent and tools

```
 invoice TXT ─► parsing (pages, numbered lines) ─► Azure OpenAI extraction (strict json_schema) ─► evidence verification
 ledger CSV  ─► ledger validation ───────────────────────────────────────────────┐
                                                                                 ▼
  model function calls ─► Python tools (allowlisted, session-scoped, read server-side state only)
    validate_intake         required fields, ISO currency, dates, amounts, evidence
    reconcile_invoice       invoice arithmetic (separate check)
    find_ledger_candidates  exact invoice number + vendor → all candidates
    compare_to_ledger       only for the single candidate Python returned
    build_review_checklist  outcome + policy-referenced follow-up from Python findings
                                                                                 ▼
  report (Python findings are authoritative) ─► human note + decision ─► JSON / CSV
```

- **Required tools depend on the outcome.** `compare_to_ledger` is required only when exactly one candidate
  exists. With no candidate, several candidates, or a missing identifier, the run finishes on the follow-up path
  without asking for an impossible comparison. A model's attempt to compare a different entry is rejected and
  doesn't count as a successful call.
- **Budget:** at most **8 model requests** per invoice, counting extraction, schema repair, tool rounds, and at
  most one transient retry. One model response can request several tools. Typical runs use 4–5 requests.
  Running out of budget marks the run *Incomplete*, which can't be approved.
- **Model summary:** model sentences are kept only if they cite a real finding code or policy reference.
- **Instructions inside documents** are treated as data. Non-allowlisted tools are rejected, and the model
  cannot change the review status.

## Modes

| Mode | What happens | Where |
|---|---|---|
| **Recorded live run** | Replays the saved actual Azure runs of the 11 development samples, with provider, model, and time provenance. No inference. | Public demo (default) |
| **Illustrative demo** | Hand-prepared extraction, clearly labeled. The ledger search, comparison, and arithmetic are real Python. | Always |
| **Live agent** | Actual inference and model-chosen tool calls. TXT and CSV upload enabled. | Local/private only (`LIVE_MODE_ENABLED=true`) |

## Local setup

Requires **Python 3.12** (tested on 3.12.2; packages pinned in `requirements.txt`).

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m streamlit run app.py      # open the http://localhost:8501 URL it prints
python -m pytest                    # 65 offline tests; no network or key needed
```

**Live mode (local only).** Copy `.streamlit/secrets.example.toml` to `.streamlit/secrets.toml` (git-ignored)
and set:

- `AZURE_OPENAI_BASE_URL`: `https://<resource>.openai.azure.com/openai/v1/` or the `.services.ai.azure.com` form
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_DEPLOYMENT`
- `LIVE_MODE_ENABLED = "true"`

The deployment must support Chat Completions with function calling and strict `json_schema`. Verified on
`gpt-4.1-mini`.

```bash
RUN_LIVE_TESTS=1 python -m pytest tests/live -q   # live smoke test: the 950 vs 880 sample
python -m taxflow.record                          # re-record the sample replays
python -m evaluation.run --mode live              # paid held-out benchmark
```

## Evaluation (v2)

[evaluation/v2/](evaluation/v2/) holds 29 held-out synthetic invoices and a held-out ledger (32 entries,
including deliberate traps), with neutral case IDs. The labels in `evaluation/v2/ground_truth/` are read only by
the runner, after all predictions exist; a test checks that agent code never imports them. The cases use
vendors different from the development samples.

The 29 cases cover:

- 5 correct matches, including CAD and EUR invoices and one within the 0.01 tolerance;
- 4 amount differences;
- 3 missing entries, including a similar invoice number with the same amount, and the same number under a
  different vendor;
- 3 duplicate candidates, including one candidate whose amount equals the invoice's;
- 3 currency differences;
- 3 missing fields: invoice number, date, and stated total;
- 3 invoices with wrong arithmetic whose recorded totals match the ledger;
- 2 date mismatches;
- 2 attack invoices;
- 1 unsupported credit note.

Missing currency is covered by development tests. Metric definitions are fixed in the docstring of
[evaluation/scoring.py](evaluation/scoring.py).

**Process:** the prompt was tuned only on the 11 development samples and frozen at `extract-v4+agent-v2` in
commit `a3e2d46`, before the first held-out run. Every label was checked against the deterministic rules by a
test, and a second test confirms the scorer flags corrupted predictions.

### Results: first v2 held-out run (2026-10-01, [reports/eval-v2-20261001T070337Z.md](reports/eval-v2-20261001T070337Z.md))

Azure OpenAI `gpt-4.1-mini` · 8-request budget · dataset `heldout-v2-reconciliation-2026-10-01`

| Metric | Result |
|---|---|
| Routing | 29/29 (invoices 28/28, unsupported 1/1) |
| Matching accuracy (outcome + entry + candidate set) | 28/28 |
| Exception detection | precision 25/25, recall 25/25 |
| False positives | 0 exception pairs; 0/7 clean cases given a blocking exception |
| Arithmetic | exact code set 3/3; status correct 28/28; 0/25 false-positive cases |
| Field extraction (5 required + subtotal, tax) | 193/193, 0 invented values |
| Evidence validity | 353/353 |
| Workflow completion | 29/29 (0 execution failures) |
| Attack cases | 2/2 |
| Latency (completed runs) | median 11.3 s, p95 14.6 s |

**Read these results with caution.** A perfect score here mostly shows that the deterministic rules and the
agent wiring behave as designed on clean, typed, synthetic documents written by the same builder who wrote the
rules. The set is small (29 cases), the layouts are regular, and there is no OCR, scanning noise, or real client
data. It is **not** evidence of real-world accuracy. The harder v1 intake set produced two extraction failures,
which shows the model does make mistakes. Future changes informed by this run must be labeled
`--iteration-on-seen-set`.

**History:** the v1 invoice-intake run ([reports/eval-20261001T061254Z.md](reports/eval-20261001T061254Z.md),
24 cases, tag `v1-invoice-intake`) scored 22/24 workflow completion and 261/264 field accuracy. Its cases are
archived in [evaluation/v1/](evaluation/v1/) and are not used as held-out data for v2.

## 60–90 second demo script

1. Open the app (Recorded live run mode) and point out the four status cards.
2. Choose **"Ledger agrees (950) but invoice arithmetic expects 880"** and select **Analyze invoice**.
3. Show **Ledger reconciliation: Matched** against entry DEV-1007, row 8, in the side-by-side table. Then show
   **Invoice arithmetic: Inconsistent**: 800 + 80 = 880, so the stated 950 is 70.00 higher. *Approve* is disabled.
4. Click the source reference next to *Stated total* to highlight the line in the invoice.
5. Switch to **"Two ledger entries match"** and show *Ambiguous match*, with no entry selected.
6. Open the **Activity log** to show the model-called tools and the outcome-dependent required set.
7. Add a note, choose **Needs follow-up**, and download the CSV.
8. Open the **Evaluation** tab to show the saved v2 report with its denominators and caveats.

## Deployment (Streamlit Community Cloud, public sample demo)

1. Push the repository to GitHub. It contains source, fictional samples, tests, the policy, and non-sensitive
   reports. `secrets.toml` is git-ignored.
2. On share.streamlit.io, create an app: choose the repo and branch, set the main file to `app.py`, and pick
   **Python 3.12** under Advanced settings. **Add no secrets.** Live mode stays off, so there's no upload and no
   inference, and only the recorded and illustrative modes appear.
3. Open the `*.streamlit.app` URL in a private window and check the matched, 950/880, ambiguous, no-entry, and
   unsupported samples, the source references, the review buttons, and both exports.
4. Record here:
   - Repository: _not yet published_
   - App URL: _not yet deployed_
   - Verified revision: _n/a_

## Limitations and next extensions

The current version covers English TXT invoices of 1–5 pages, one ledger entry per invoice, and exact matching
on invoice number and vendor. There is no OCR, PDF, currency conversion, split postings, credit notes, database,
or ERP integration, and no time-savings claim.

Planned extensions:

- text-based PDF invoices;
- analyst-confirmed matches for ambiguous candidates, with an audit trail;
- batch reconciliation of many invoices against one ledger;
- reviewed vendor-alias tables (instead of fuzzy matching);
- a timed manual-vs-assisted study.
