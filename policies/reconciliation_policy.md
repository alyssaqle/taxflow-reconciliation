# TaxFlow Fictional Reconciliation Policy

Policy version: reconciliation-policy-2026-10-01

This is a fictional internal policy used by the TaxFlow portfolio prototype. It is not legal,
tax, or accounting guidance. Each rule has a stable reference ID returned by the
`build_review_checklist` tool. Rules marked "Blocking: yes" prevent approval.

## TF-POL-000 | Normal review
Applies to: NO_FINDINGS
Blocking: no
Follow-up: The invoice agrees with its ledger entry and no blocking exceptions were found. An analyst may compare the sources and approve.

## TF-POL-101 | Required field missing
Applies to: MISSING_FIELD
Blocking: yes
Follow-up: Ask the sender or client to provide the missing {field}; it is required to reconcile the invoice.

## TF-POL-102 | Invalid amount or quantity
Applies to: INVALID_AMOUNT
Blocking: yes
Follow-up: Ask the sender to confirm the {field} value; it is not a valid nonnegative amount.

## TF-POL-103 | Invalid or ambiguous date
Applies to: INVALID_DATE
Blocking: yes
Follow-up: Ask the sender to confirm the invoice date in an unambiguous format.

## TF-POL-104 | Unsupported currency
Applies to: UNSUPPORTED_CURRENCY
Blocking: yes
Follow-up: Ask the sender to state the invoice currency as a valid ISO 4217 code.

## TF-POL-105 | Source evidence not verified
Applies to: UNSUPPORTED_EVIDENCE
Blocking: yes
Follow-up: Re-read the source for {field} and confirm the value manually before reconciling.

## TF-POL-201 | Ledger not searched
Applies to: LEDGER_NOT_SEARCHED
Blocking: yes
Follow-up: Request the missing invoice number or vendor name from the client before searching the ledger.

## TF-POL-202 | No matching ledger entry
Applies to: LEDGER_NO_MATCH
Blocking: yes
Follow-up: Ask the client whether this invoice was recorded and, if so, for the ledger entry ID.

## TF-POL-203 | Ambiguous ledger match
Applies to: LEDGER_AMBIGUOUS
Blocking: yes
Follow-up: Ask the client which ledger entry corresponds to this invoice and whether the other entries are duplicates.

## TF-POL-204 | Currency differs from ledger
Applies to: LEDGER_CURRENCY_MISMATCH
Blocking: yes
Follow-up: Ask the client to confirm the currency recorded for this invoice. No conversion is performed.

## TF-POL-205 | Amount differs from ledger
Applies to: LEDGER_AMOUNT_MISMATCH
Blocking: yes
Follow-up: Ask the client to confirm the recorded gross amount against the invoice's stated total.

## TF-POL-206 | Date differs from ledger
Applies to: LEDGER_DATE_MISMATCH
Blocking: yes
Follow-up: Ask the client to confirm the invoice date recorded in the ledger.

## TF-POL-207 | Ledger comparison incomplete
Applies to: LEDGER_COMPARISON_INCOMPLETE
Blocking: yes
Follow-up: Obtain the missing invoice information so the currency, amount, and date comparisons can be completed.

## TF-POL-301 | Line item does not reconcile
Applies to: ITEM_MISMATCH
Blocking: yes
Follow-up: Ask the vendor to confirm or correct {field}: quantity times unit price does not equal the stated line total.

## TF-POL-302 | Subtotal does not reconcile
Applies to: SUBTOTAL_MISMATCH
Blocking: yes
Follow-up: Ask the vendor to confirm or correct the subtotal; it does not equal the sum of line totals.

## TF-POL-303 | Invoice total does not reconcile
Applies to: TOTAL_MISMATCH
Blocking: yes
Follow-up: Ask the vendor to confirm or correct the invoice total; it does not equal subtotal plus stated tax. The ledger comparison still uses the stated total.

## TF-POL-304 | Invoice arithmetic not fully checked
Applies to: ARITHMETIC_NOT_CHECKED
Blocking: no
Follow-up: Note that the invoice's own arithmetic could not be fully checked (missing subtotal, tax, or line details). This does not block reconciliation.

## TF-POL-305 | Adjustments not calculated
Applies to: UNSUPPORTED_STRUCTURE
Blocking: no
Follow-up: The invoice contains discounts, credits, shipping, or multiple taxes that the arithmetic check does not calculate. Review them manually.

## TF-POL-401 | Unsupported document
Applies to: UNSUPPORTED_DOCUMENT
Blocking: yes
Follow-up: Return the document to the requester. Only invoices are reconciled in this version.

## TF-POL-402 | Processing incomplete
Applies to: INCOMPLETE_PROCESSING
Blocking: yes
Follow-up: Re-run the analysis. Approval is not possible until all required checks complete.
