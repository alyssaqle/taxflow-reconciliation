# TaxFlow — Invoice Intake Agent

TaxFlow helps a tax or finance operations analyst do the **first review of an incoming invoice**. It reads a
(fictional) invoice, organizes the key fields with a **source reference for every value**, checks completeness
and arithmetic with Python `Decimal`, and prepares a review packet. **A person makes the review decision.**

> Portfolio prototype using synthetic data only. TaxFlow does not file taxes, calculate tax liability, pay
> invoices, certify compliance, or send messages. The stated tax amount is treated as an input. Independent
> branding; no affiliation with any firm is implied.

**Example.** An invoice states subtotal USD 800.00, tax USD 80.00, total USD 950.00. TaxFlow calculates
800.00 + 80.00 = 880.00, flags `TOTAL_MISMATCH` ("the stated total USD 950.00 is USD 70.00 higher"), blocks
approval, and recommends asking the sender to confirm or correct the invoice (policy ref `TF-POL-203`).

## Status

| Requirement | Implemented | Locally tested | Live verified | Deployed |
|---|---|---|---|---|
| A · UI, 6 samples, source viewer, illustrative extraction, real Python checks | ✅ | ✅ | n/a | ⏳ |
| B · Azure OpenAI adapter, structured extraction, model function-calling loop | ✅ | ✅ | ✅ Azure OpenAI `gpt-4.1-mini` (2026-10-01) | n/a (public demo is replay only) |
| C · TXT upload, evidence, review note/decision, JSON/CSV export | ✅ | ✅ | ✅ samples run live | ⏳ |
| D · 24-case held-out benchmark, README, deploy config | ✅ | ✅ | ✅ first held-out run saved | ⏳ |

The live agent was verified on **Azure OpenAI** (v1 API, Chat Completions, deployment `gpt-4.1-mini`). On every
supported sample, the model called `validate_intake`, `reconcile_invoice`, and `lookup_intake_policy` through
function calling. The six bundled samples are saved as **Recorded live runs** in `samples/recorded/`.

## Architecture

```
 TXT sample/upload ──► parsing.py ── pages + numbered lines (read-only source viewer)
                          │
                          ▼
   agent.extract ── Azure OpenAI (Chat Completions, strict json_schema) ──► draft + evidence spans
                          │                                      (1 request, +1 schema repair if needed)
                          ▼
   evidence.verify_draft ── quote in cited span? value consistent with quote? (numbers/dates/USD)
                          │
                          ▼
   agent.run_tool_loop ── model chooses function calls ──► tools.py (allowlist, server-side draft only)
        ▲                                                 ├ validate_intake(document_id)
        └──────────── tool outputs returned to model ─────┤ reconcile_invoice(document_id)
                                                          └ lookup_intake_policy(finding_codes)
                          │      budget: ≤ 6 model requests per document, incl. retries
                          ▼
   pipeline._assemble ── Python findings are authoritative; checklist from codes + policy refs;
                          model sentences kept only if they cite a real finding/policy ref
                          ▼
   app.py ── record + findings + sources + activity log ─► human: note, Approve / Needs follow-up ─► JSON/CSV
```

| File | Role |
|---|---|
| `app.py` | Streamlit UI (Review / Evaluation / About tabs) |
| `taxflow/models.py` | Pydantic schemas: evidence, draft, findings, checks, trace, result |
| `taxflow/parsing.py` | Page/line numbering; upload limits (UTF-8, 2 MB, 20,000 chars, ≤ 5 pages) |
| `taxflow/evidence.py` | Source-span and value/quote verification |
| `taxflow/checks.py` | Required fields, validity, currency, structure, Decimal reconciliation |
| `taxflow/tools.py` | The three allowlisted tools and the execution trace |
| `taxflow/policy.py`, `policies/intake_policy.md` | Fictional policy with stable IDs `TF-POL-xxx` |
| `taxflow/providers.py` | The only place provider configuration lives (Azure OpenAI v1) |
| `taxflow/agent.py` | Extraction prompt/schema, request budget, function-calling loop |
| `taxflow/pipeline.py` | Illustrative, live, and recorded-run orchestration |
| `taxflow/exports.py` | JSON and CSV exports |
| `taxflow/record.py` | Saves successful live sample runs as "Recorded live run" packets |
| `evaluation/` | 24 held-out cases, separate labels, runner, scoring |

## Local setup

Requires **Python 3.12** (tested on 3.12.2; packages pinned in `requirements.txt`).

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m streamlit run app.py        # open the http://localhost:8501 URL it prints
python -m pytest                      # offline tests (no network, no key)
```

## Modes

| Mode | What happens | Where |
|---|---|---|
| **Illustrative demo** | Hand-prepared extraction, clearly labeled. The completeness, evidence, and arithmetic checks are real Python. Tools are called directly by the app; no model is called. | Always available |
| **Recorded live run** | Replays a saved actual live run with provider/model/time provenance. No inference. Your review choices apply only to the replay. | Shown once `samples/recorded/*.json` exist |
| **Live agent** | Actual inference and model-chosen tool calls on the current input; synthetic TXT upload is enabled. A failed request is shown as Failed/Incomplete, never as a mock success. | Local/private only (`LIVE_MODE_ENABLED=true`) |

### Configuring live mode (local only)

```bash
cp .streamlit/secrets.example.toml .streamlit/secrets.toml   # git-ignored
```

Then fill in, locally only:

| Setting | Value |
|---|---|
| `MODEL_PROVIDER` | `azure_openai` |
| `AZURE_OPENAI_BASE_URL` | `https://<resource-name>.openai.azure.com/openai/v1/` |
| `AZURE_OPENAI_API_KEY` | key from the Azure portal (Resource → Keys and Endpoint) |
| `AZURE_OPENAI_DEPLOYMENT` | your deployment name, e.g. a `gpt-4.1-mini` or `gpt-4o` deployment |
| `LIVE_MODE_ENABLED` | `true` locally; keep `false` for public hosting |

Environment variables with the same names override the file. The deployment must support **Chat Completions
with function calling and `response_format` `json_schema` (strict)**. The client uses the v1 route (no
`api-version`), a 45 s timeout, and SDK retries disabled so every attempt counts against the budget.

Smoke test and recording, once configured:

```bash
RUN_LIVE_TESTS=1 python -m pytest tests/live -q     # one live run of the 800/80/950 sample
python -m taxflow.record                            # saves successful runs as Recorded live runs
```

## Checks and tools

- **Required fields** (fictional policy): vendor, invoice number, ISO invoice date, explicit USD currency
  (a `$` alone is not enough), at least one complete line item, subtotal, explicitly stated tax (zero is valid), total.
- **Arithmetic**: each item total is `quantity × unit_price`, rounded to cents with `ROUND_HALF_UP`. The subtotal
  is compared with the sum of the *stated* line totals, so a single wrong line is reported once as
  `ITEM_MISMATCH` (the sum of calculated totals is still shown in the check details). Total = subtotal + tax.
  Differences greater than USD 0.01 are flagged.
- **Skipped checks** are reported as `NOT CHECKED` with the reason, never as passes.
- **Finding codes** (all blocking in v1): `MISSING_FIELD`, `INVALID_AMOUNT`, `INVALID_DATE`, `ITEM_MISMATCH`,
  `SUBTOTAL_MISMATCH`, `TOTAL_MISMATCH`, `UNSUPPORTED_CURRENCY`, `UNSUPPORTED_STRUCTURE`,
  `UNSUPPORTED_EVIDENCE`, `UNSUPPORTED_DOCUMENT`, `INCOMPLETE_PROCESSING`.
- **Evidence**: every non-null value cites page, line range (≤ 6 lines) and an exact quote. The quote must occur in
  that span, and numbers, dates, and USD must be consistent with the quote. A matching quote does not prove the
  field interpretation is right; evaluation scores values separately.
- **Approval** requires processing status *Complete* and zero blocking findings. A new input or re-run resets the
  decision. *Needs follow-up* exports keep all findings and the reviewer's note.
- **Prompt injection**: document text is passed as delimited untrusted data. It cannot add tools (non-allowlisted
  names are rejected), tools resolve only the current document ID and read the server-side draft, and the model
  cannot change review status.

## Evaluation

`evaluation/cases/` holds 24 held-out synthetic documents with neutral IDs. Their labels are in
`evaluation/ground_truth/`, which only `evaluation/run.py` reads after all predictions exist; agent code never
imports it (a test enforces this). The split is 8 complete, 6 missing data, 4 inconsistent amounts, 3 malicious
instructions, and 3 unsupported documents (quote, pay stub, bank statement). Vendors and layouts differ from the
six development samples. Metric definitions are in the docstring of `evaluation/scoring.py`.

```bash
python -m evaluation.run --mode live      # paid inference; writes reports/eval-<timestamp>.json/.md
```

Model failures stay in the denominator. Runs made after changes informed by held-out failures must use
`--iteration-on-seen-set`, and the original report should be kept. The app's Evaluation tab only reads saved reports.

### Results: first held-out run (2026-10-01, `reports/eval-20261001T061254Z.md`)

Azure OpenAI `gpt-4.1-mini` · prompt `extract-v2+agent-v1` · dataset `heldout-v1-2026-09-30`. The prompt was tuned
only on the six development samples before this run.

| Metric | Result |
|---|---|
| Routing | 24/24 (invoices 21/21, unsupported 3/3) |
| Field extraction accuracy | 261/264 (98.9%), 0 invented values |
| Missing-field detection | recall 6/6, precision 6/8 |
| Arithmetic exact code set | 4/4, 0/17 false-positive cases |
| Evidence validity | 262/262 |
| Workflow completion | 22/24 (invoices 19/21, unsupported 3/3) |
| Attack cases | 3/3 |
| Latency (successful runs) | median 10.1 s, p95 12.4 s (n = 24) |

**Failures (kept as-is):** `case_06`: the unit price `$22.00` (no explicit currency) was extracted as null, so a
line item was reported incomplete. `case_16`: in the line `pages: 12 @ 35.00`, the model folded "pages: 12" into
the description and left quantity null. Both are extraction errors that Python correctly turned into blocking
`MISSING_FIELD` findings rather than wrong arithmetic. This is a small synthetic benchmark, not evidence of
real-world reliability. Any fix informed by these cases must be rerun with `--iteration-on-seen-set`.

Iteration targets (≥ 22/24 routing, ≥ 90% field accuracy, ≥ 90% missing-field recall, ≥ 20/24 workflow
completions, 3/3 attack cases) were all met on this run.

## Deployment (Streamlit Community Cloud, sample demo only)

1. Push this repository to GitHub (source, fictional samples, tests, policy, non-sensitive reports only).
2. On share.streamlit.io: **Create app** → pick the repo, branch `main`, main file `app.py`; under
   **Advanced settings** choose **Python 3.12**. Add no secrets. Live mode stays disabled, so there is no upload
   control and no inference.
3. Open the `*.streamlit.app` URL in a private window. Check the clean, missing-number, wrong-total, and
   unsupported samples, the source references, the review buttons, and both exports.
4. Record the URLs and verified commit here:
   - Repository: _not yet published_
   - App URL: _not yet deployed_
   - Verified revision: _n/a_

## 60–90 second demo script

1. Open TaxFlow and point to the mode banner (Recorded live run, or Illustrative demo).
2. Choose **Wrong total (800 + 80 vs 950)** and select **Analyze invoice**.
3. Click the source reference next to *Total* to show the highlighted line in the source.
4. Read the finding: `TOTAL_MISMATCH`, expected 880.00, 70.00 higher. *Approve intake* is disabled.
5. Open the **Activity log** to show `validate_intake`, `reconcile_invoice`, and `lookup_intake_policy`, and who invoked them.
6. Add a note, select **Needs follow-up**, and download the CSV.
7. Open the **Evaluation** tab to show the saved report with its denominators and failures.

## Limitations and extensions

v1 supports English, explicit-USD, 1–5 page TXT invoices with a single stated tax amount and no discounts,
credits, shipping, or multiple taxes. Other inputs route to follow-up. There is no OCR, PDF, database, or
external integration, and no time-savings claim. Planned extensions: text-based PDF upload, analyst field
corrections with audit history, W-2/1099-NEC schemas, a manual-vs-assisted timing study, and more currencies.
