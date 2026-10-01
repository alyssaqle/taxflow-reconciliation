# FATURA extraction benchmark · dev · baseline · 20261001T194907Z-dev-baseline

**Data:** FATURA (Limam, Dhiaf & Kessentini 2023, Zenodo doi:10.5281/zenodo.8261508, CC BY 4.0): **synthetic** invoice images generated from 50 templates by the dataset authors. Dev and eval use disjoint templates. Input to TaxFlow is our own Tesseract 5 OCR of each image (psm 6); the images are processed by our pipeline, but OCR is Tesseract, not a TaxFlow model.
**System:** none (regex baseline) · model `None` · prompt None · schema reconciliation-v2
**Documents:** selected 50, attempted 50, skipped by token budget 0 (budget 3,000,000; used 0) · wall time 0.0 s

| Field | Accuracy | Missing | Wrong | Expected null → correct / invented | Not scored (unknown) | OCR ceiling | Evidence valid |
|---|---|---|---|---|---|---|---|
| vendor_name | 24/40 (60.0%) | 0 | 16 | 0 / 0 of 0 | 10 | 39/40 (97.5%) | 0/40 (0.0%) |
| invoice_number | 42/45 (93.3%) | 0 | 3 | 5 / 0 of 5 | 0 | 42/45 (93.3%) | 0/45 (0.0%) |
| invoice_date | 44/50 (88.0%) | 6 | 0 | 0 / 0 of 0 | 0 | 49/50 (98.0%) | 0/44 (0.0%) |
| currency | 26/26 (100.0%) | 0 | 0 | 14 / 0 of 14 | 10 | 26/26 (100.0%) | 0/26 (0.0%) |
| total | 40/40 (100.0%) | 0 | 0 | 0 / 0 of 0 | 10 | 40/40 (100.0%) | 0/40 (0.0%) |
| subtotal | 30/30 (100.0%) | 0 | 0 | 0 / 0 of 0 | 20 | 30/30 (100.0%) | 0/30 (0.0%) |
| tax | 10/10 (100.0%) | 0 | 0 | 0 / 0 of 0 | 40 | 10/10 (100.0%) | 0/10 (0.0%) |

| Aggregate metric | Result |
|---|---|
| Aggregate field accuracy | 216/241 (89.6%) |
| Missing predictions / wrong values | 6 / 19 |
| Invented values (expected null) | 0/19 (0.0%) |
| Docs with all scorable required fields correct | 31/50 (62.0%) |
| Docs with all 5 required fields scorable and correct | 18/35 (51.4%) |
| Evidence validity (all non-null predictions) | n/a (baseline produces no evidence) |
| Routed as invoice | 50/50 (100.0%) |
| Missing required field routed to follow-up | 19/19 (100.0%) |
| Discount / multi-GST flagged as unsupported structure | 0/5 (0.0%) |
| Unsupported structure false flags | 0/45 (0.0%) |
| Failed requests | 0/50 (0.0%) |
| Extraction latency median / p95 (s) | 0.0 / 0.0 |
| OCR + extraction latency median / p95 (s) | 0.491 / 0.659 |
| Tokens total / median per doc | 0 / 0.0 |
