# FATURA extraction benchmark · dev · live · 20261001T200521Z-dev-live

**Data:** FATURA (Limam, Dhiaf & Kessentini 2023, Zenodo doi:10.5281/zenodo.8261508, CC BY 4.0): **synthetic** invoice images generated from 50 templates by the dataset authors. Dev and eval use disjoint templates. Input to TaxFlow is our own Tesseract 5 OCR of each image (psm 6); the images are processed by our pipeline, but OCR is Tesseract, not a TaxFlow model.
**System:** Azure OpenAI (v1 API, Chat Completions) · model `gpt-4.1-mini` · prompt extract-v6+agent-v2 · schema reconciliation-v2
**Documents:** selected 50, attempted 50, skipped by token budget 0 (budget 3,000,000; used 152,595) · wall time 157.4 s

| Field | Accuracy | Missing | Wrong | Expected null → correct / invented | Not scored (unknown) | OCR ceiling | Evidence valid |
|---|---|---|---|---|---|---|---|
| vendor_name | 39/40 (97.5%) | 0 | 1 | 0 / 0 of 0 | 10 | 39/40 (97.5%) | 40/40 (100.0%) |
| invoice_number | 42/45 (93.3%) | 0 | 3 | 5 / 0 of 5 | 0 | 42/45 (93.3%) | 45/45 (100.0%) |
| invoice_date | 48/50 (96.0%) | 2 | 0 | 0 / 0 of 0 | 0 | 49/50 (98.0%) | 47/48 (97.9%) |
| currency | 26/26 (100.0%) | 0 | 0 | 14 / 0 of 14 | 10 | 26/26 (100.0%) | 24/26 (92.3%) |
| total | 40/40 (100.0%) | 0 | 0 | 0 / 0 of 0 | 10 | 40/40 (100.0%) | 40/40 (100.0%) |
| subtotal | 30/30 (100.0%) | 0 | 0 | 0 / 0 of 0 | 20 | 30/30 (100.0%) | 30/30 (100.0%) |
| tax | 10/10 (100.0%) | 0 | 0 | 0 / 0 of 0 | 40 | 10/10 (100.0%) | 10/10 (100.0%) |

| Aggregate metric | Result |
|---|---|
| Aggregate field accuracy | 235/241 (97.5%) |
| Missing predictions / wrong values | 2 / 4 |
| Invented values (expected null) | 0/19 (0.0%) |
| Docs with all scorable required fields correct | 44/50 (88.0%) |
| Docs with all 5 required fields scorable and correct | 31/35 (88.6%) |
| Evidence validity (all non-null predictions) | 255/258 (98.8%) |
| Routed as invoice | 50/50 (100.0%) |
| Missing required field routed to follow-up | 19/19 (100.0%) |
| Discount / multi-GST flagged as unsupported structure | 5/5 (100.0%) |
| Unsupported structure false flags | 0/45 (0.0%) |
| Failed requests | 0/50 (0.0%) |
| Extraction latency median / p95 (s) | 9.2185 / 13.644 |
| OCR + extraction latency median / p95 (s) | 9.728000000000002 / 14.217 |
| Tokens total / median per doc | 152,595 / 3084.5 |
