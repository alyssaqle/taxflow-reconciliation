# TaxFlow Fictional Intake Policy

Policy version: intake-policy-2026-09-30

This is a fictional internal policy used by the TaxFlow portfolio prototype. It is not
legal, tax, or accounting guidance. Each rule has a stable reference ID that the
`lookup_intake_policy` tool returns. All findings listed here are blocking in v1.

## TF-POL-000 | Normal review
Applies to: NO_FINDINGS
Follow-up: No blocking findings. An analyst may compare the record with the source and approve intake.

## TF-POL-101 | Required field missing
Applies to: MISSING_FIELD
Follow-up: Ask the sender to provide the missing {field} and resend or confirm the invoice.

## TF-POL-102 | Invalid amount or quantity
Applies to: INVALID_AMOUNT
Follow-up: Ask the sender to confirm the {field} value; it is not a valid nonnegative amount.

## TF-POL-103 | Invalid or ambiguous date
Applies to: INVALID_DATE
Follow-up: Ask the sender to confirm the invoice date in an unambiguous format.

## TF-POL-201 | Line item does not reconcile
Applies to: ITEM_MISMATCH
Follow-up: Ask the sender to confirm or correct {field}: quantity times unit price does not equal the stated line total.

## TF-POL-202 | Subtotal does not reconcile
Applies to: SUBTOTAL_MISMATCH
Follow-up: Ask the sender to confirm or correct the subtotal; it does not equal the sum of line totals.

## TF-POL-203 | Total does not reconcile
Applies to: TOTAL_MISMATCH
Follow-up: Ask the sender to confirm or correct the invoice total; it does not equal subtotal plus stated tax.

## TF-POL-301 | Unsupported currency
Applies to: UNSUPPORTED_CURRENCY
Follow-up: Route to a specialist. Version 1 accepts invoices stated explicitly in USD only.

## TF-POL-302 | Unsupported invoice structure
Applies to: UNSUPPORTED_STRUCTURE
Follow-up: Route to a specialist. Discounts, credits, shipping, and multiple tax components are not calculated in version 1.

## TF-POL-303 | Unsupported document
Applies to: UNSUPPORTED_DOCUMENT
Follow-up: Return the document to the requester. Only invoices are accepted for intake in version 1.

## TF-POL-401 | Source evidence not verified
Applies to: UNSUPPORTED_EVIDENCE
Follow-up: Re-read the source for {field} and confirm the value manually before intake.

## TF-POL-402 | Processing incomplete
Applies to: INCOMPLETE_PROCESSING
Follow-up: Re-run the analysis. Approval is not possible until all required checks complete.
