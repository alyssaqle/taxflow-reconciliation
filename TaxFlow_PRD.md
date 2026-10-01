# TaxFlow: Invoice-to-Ledger Reconciliation Agent

Product requirements · Version 3 · October 1, 2026 · Author: Alyssa Le

Version 3 supersedes the invoice-only intake scope of version 2. Version 2 is preserved at git tag
`v1-invoice-intake`, together with its implementation and first evaluation report.

## 1. Problem and user

**User:** a tax or finance operations analyst.

**Problem:** the analyst receives a client's invoices and accounting spreadsheet. They must confirm that each
invoice agrees with its accounting entry and identify discrepancies that need follow-up.

**User story:** As an analyst, I want each invoice compared with its ledger entry, with the evidence and the
exceptions in one report, so that I can decide quickly and defensibly what needs follow-up.

**Product:** an evidence-backed exception report prepared for human review. TaxFlow does not file taxes,
calculate tax liability, pay invoices, post entries, certify compliance, or send messages. It uses independent
TaxFlow branding and synthetic data only. Time savings are a hypothesis to measure later, not a claim.

## 2. Workflow

1. Select a synthetic invoice and the sample ledger. In local/private live mode, upload a TXT invoice and an
   accounting CSV instead.
2. Extract vendor, invoice number, invoice date, currency, and stated total (plus subtotal, tax, and line items
   for the arithmetic check). Each value has a verified source reference.
3. Search the ledger for corresponding entries.
4. Compare the invoice with the entry in Python.
5. Show the match, the discrepancies, the evidence, and the policy-referenced follow-up.
6. Let the analyst record a note and a decision, then download JSON or CSV.

## 3. Key distinction

Compare the invoice's **stated total** with the ledger's **gross amount** (tax included). Check the invoice's own
arithmetic **separately**, and never replace the stated total with a calculated value.

Example: subtotal 800, tax 80, stated total 950, and a ledger gross amount of 950. The ledger comparison is
**Matched**; the invoice arithmetic is **Inconsistent**, because 880 was expected. Both are shown. The
arithmetic finding blocks approval, the recommended decision is Needs follow-up, and a reviewer note cannot
remove the finding.

## 4. Accounting CSV

Columns: `ledger_entry_id, invoice_number, vendor_name, invoice_date, currency, gross_amount`.

The file is validated before processing, and any failure rejects the whole file with row-level reasons:

- exact columns;
- ISO dates;
- supported ISO 4217 currencies from a maintained list (`pycountry`; metals, test, and fund codes excluded);
- nonnegative Decimal amounts with at most 2 decimals;
- unique entry IDs, and non-empty identifiers;
- UTF-8, at most 2 MB and 5,000 rows.

A template and a fictional sample dataset are downloadable. MVP assumption: one entry per invoice. Split
postings and credit notes are out of scope.

## 5. Matching and comparison rules

- **Matching key:** match on invoice number **and** vendor name, normalizing only whitespace and case. There is
  no fuzzy matching, no invented match, and no selection by amount.
- **Candidates:** return all of them.
  - One candidate: compare.
  - Several candidates: **Ambiguous match**.
  - No candidate: **No matching entry**.
  - A missing invoice number or vendor: **Needs clarification**, without searching.
- **Comparison order:** currency first, with no conversion; a currency mismatch prevents amount comparison and is
  a blocking discrepancy. Then compare the stated total with the gross amount using Decimal, where a difference
  of at most 0.01 agrees. Then compare the invoice date.
- **Matched** requires the currency, amount, and date comparisons all to complete and agree. Matching
  identifiers alone are insufficient: an incomplete comparison gives **Needs clarification**.

## 6. Required fields and blocking

- **Required fields:** vendor, invoice number, invoice date, an explicit supported currency (never inferred from
  "$"), and the stated total. A missing required field is blocking.
- **Arithmetic inputs:** a missing subtotal, tax, or line item makes the arithmetic Not checked or Partially
  checked. This is a visible, non-blocking limitation in the report and export, and it does not independently
  block reconciliation approval.
- **Other blocking exceptions:** ledger exceptions, arithmetic mismatches (item, subtotal, total), invalid values,
  unsupported currency, unverified evidence, an unsupported document, and incomplete processing.
- **Kept separate:** processing status, reconciliation outcome, invoice arithmetic, and the human review
  decision, in both the UI and the exports. Approval requires processing Complete and zero blocking exceptions.

## 7. Agent

The pipeline: extract with the model (strict structured output) → verify evidence → model function-calling loop
over allowlisted Python tools → Python findings (authoritative) → checklist from policy references → human review.

**Tools:**

- `validate_intake`
- `reconcile_invoice` (invoice arithmetic)
- `find_ledger_candidates`
- `compare_to_ledger` (only for the single candidate Python returned)
- `build_review_checklist`

Tools read server-side state, are scoped to the current session's document and ledger, and never accept amounts
from the model.

**Required tools depend on the outcome:** a unique candidate requires a comparison. No candidate, several
candidates, missing fields, and unsupported documents finish on their follow-up branches. A correctly reported
exception counts as a successful workflow; an execution failure never does.

**Budget:** at most 8 model requests per invoice, counting extraction, repair, tool rounds, and at most one
transient retry. One response may request several tools. When the budget runs out, the run is Incomplete and
can't be approved.

The activity log shows the actual executed tools. Recorded and illustrative modes are labeled as such. Live
inference is local/private only; the public demo has live mode disabled and no upload.

## 8. Evaluation

Development fixtures (11 samples with a sample ledger) are kept separate from a 29-case held-out set, which has
its own ledger and labels:

| Group | Count |
|---|---|
| Correct matches | 5 |
| Amount differences | 4 |
| Missing entries | 3 |
| Duplicate candidates | 3 |
| Currency differences | 3 |
| Missing fields (identifier, date, stated total) | 3 |
| Arithmetic wrong, recorded total matches | 3 |
| Date mismatches | 2 |
| Attack invoices | 2 |
| Unsupported document | 1 |

Missing currency is tested in development tests. The prompt is frozen before the first held-out run.

**Metrics:**

- routing;
- matching accuracy (outcome, entry, and candidate set);
- exception-detection precision and recall;
- false positives;
- arithmetic detection;
- field extraction;
- evidence validity;
- workflow completion, by category;
- execution failures;
- attack outcomes;
- latency.

Report actual denominators and failures, and keep the original report even when targets are missed.

## 9. Acceptance criteria

1. The 950/950/880 example shows Matched plus a blocking arithmetic finding, and approval is disabled.
2. Ambiguous, no-match, and missing-identifier cases complete without a comparison call and block approval.
3. A currency mismatch prevents amount comparison. An incomplete comparison is never Matched.
4. An amount-equal but non-matching entry is never selected.
5. CSV validation rejects bad columns, dates, currencies, amounts, and duplicate IDs.
6. Exports carry all four statuses, the ledger entry and row, the comparison rows, the findings with their
   blocking flag, and the reviewer note. Spreadsheet formulas are escaped.
7. Live runs show the actual model-called tools. Budget exhaustion and failures are explicit.
8. The public demo works with live mode disabled and no upload control.

## 10. Out of scope and extensions

**Out of scope:** OCR, PDF, currency conversion, split postings, credit notes, fuzzy matching, databases, ERP
integrations, and multi-agent orchestration.

**Extensions:**

- text-based PDF;
- analyst-confirmed resolution of ambiguous matches, with an audit trail;
- batch reconciliation;
- reviewed vendor-alias tables;
- a timed manual-vs-assisted study.
