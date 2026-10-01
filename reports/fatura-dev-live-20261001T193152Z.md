# FATURA extraction benchmark · dev · live · 20261001T193152Z-dev-live

**Data:** FATURA (Limam, Dhiaf & Kessentini 2023, Zenodo doi:10.5281/zenodo.8261508, CC BY 4.0): **synthetic** invoice images generated from 50 templates by the dataset authors. Dev and eval use disjoint templates. Input to TaxFlow is our own Tesseract 5 OCR of each image (psm 6); the images are processed by our pipeline, but OCR is Tesseract, not a TaxFlow model.
**System:** Azure OpenAI (v1 API, Chat Completions) · model `gpt-4.1-mini` · prompt extract-v4+agent-v2 · schema reconciliation-v2
**Documents:** selected 50, attempted 50, skipped by token budget 0 (budget 3,000,000; used 129,951) · wall time 139.3 s

| Field | Accuracy | Missing | Wrong | Expected null → correct / invented | Not scored (unknown) | OCR ceiling | Evidence valid |
|---|---|---|---|---|---|---|---|
| vendor_name | 23/40 (57.5%) | 11 | 6 | 0 / 0 of 0 | 10 | 27/40 (67.5%) | 29/29 (100.0%) |
| invoice_number | 20/45 (44.4%) | 7 | 18 | 5 / 0 of 5 | 0 | 22/45 (48.9%) | 38/38 (100.0%) |
| invoice_date | 24/50 (48.0%) | 22 | 4 | 0 / 0 of 0 | 0 | 50/50 (100.0%) | 26/28 (92.9%) |
| currency | 17/26 (65.4%) | 9 | 0 | 14 / 0 of 14 | 10 | 0/26 (0.0%) | 17/17 (100.0%) |
| total | 23/40 (57.5%) | 15 | 2 | 0 / 0 of 0 | 10 | 29/40 (72.5%) | 25/25 (100.0%) |
| subtotal | 10/30 (33.3%) | 16 | 4 | 0 / 0 of 0 | 20 | 15/30 (50.0%) | 13/14 (92.9%) |
| tax | 2/10 (20.0%) | 7 | 1 | 0 / 0 of 0 | 40 | 2/10 (20.0%) | 2/3 (66.7%) |

| Aggregate metric | Result |
|---|---|
| Aggregate field accuracy | 119/241 (49.4%) |
| Missing predictions / wrong values | 87 / 35 |
| Invented values (expected null) | 0/19 (0.0%) |
| Docs with all scorable required fields correct | 10/50 (20.0%) |
| Docs with all 5 required fields scorable and correct | 6/35 (17.1%) |
| Evidence validity (all non-null predictions) | 167/172 (97.1%) |
| Routed as invoice | 40/50 (80.0%) |
| Missing required field routed to follow-up | 12/19 (63.2%) |
| Discount / multi-GST flagged as unsupported structure | 0/15 (0.0%) |
| Unsupported structure false flags | 0/35 (0.0%) |
| Failed requests | 0/50 (0.0%) |
| Extraction latency median / p95 (s) | 8.224 / 15.974 |
| OCR + extraction latency median / p95 (s) | 8.43 / 16.228 |
| Tokens total / median per doc | 129,951 / 2687.0 |
