# FATURA extraction benchmark · eval · baseline · 20261001T200818Z-eval-baseline

**Data:** FATURA (Limam, Dhiaf & Kessentini 2023, Zenodo doi:10.5281/zenodo.8261508, CC BY 4.0): **synthetic** invoice images generated from 50 templates by the dataset authors. Dev and eval use disjoint templates. Input to TaxFlow is our own Tesseract 5 OCR of each image (2x Lanczos upscale, psm 3; settings chosen on dev only); the images are processed by our pipeline, but OCR is Tesseract, not a TaxFlow model.
**System:** none (regex baseline) · model `None` · prompt None · schema reconciliation-v2
**Documents:** selected 500, attempted 500, skipped by token budget 0 (budget 3,000,000; used 0) · wall time 0.1 s

| Field | Accuracy | Missing | Wrong | Expected null → correct / invented | Not scored (unknown) | OCR ceiling | Evidence valid |
|---|---|---|---|---|---|---|---|
| vendor_name | 151/328 (46.0%) | 0 | 177 | 0 / 0 of 0 | 172 | 320/328 (97.6%) | 0/328 (0.0%) |
| invoice_number | 414/438 (94.5%) | 7 | 17 | 49 / 0 of 49 | 13 | 423/438 (96.6%) | 0/431 (0.0%) |
| invoice_date | 437/487 (89.7%) | 50 | 0 | 13 / 0 of 13 | 0 | 479/487 (98.4%) | 0/437 (0.0%) |
| currency | 266/266 (100.0%) | 0 | 0 | 135 / 0 of 135 | 99 | 266/266 (100.0%) | 0/266 (0.0%) |
| total | 401/401 (100.0%) | 0 | 0 | 0 / 0 of 0 | 99 | 401/401 (100.0%) | 0/401 (0.0%) |
| subtotal | 343/348 (98.6%) | 4 | 1 | 0 / 0 of 0 | 152 | 343/348 (98.6%) | 0/344 (0.0%) |
| tax | 179/213 (84.0%) | 34 | 0 | 0 / 0 of 0 | 287 | 206/213 (96.7%) | 0/179 (0.0%) |

| Aggregate metric | Result |
|---|---|
| Aggregate field accuracy | 2191/2481 (88.3%) |
| Missing predictions / wrong values | 95 / 195 |
| Invented values (expected null) | 0/197 (0.0%) |
| Docs with all scorable required fields correct | 293/500 (58.6%) |
| Docs with all 5 required fields scorable and correct | 133/277 (48.0%) |
| Evidence validity (all non-null predictions) | n/a (baseline produces no evidence) |
| Routed as invoice | 500/500 (100.0%) |
| Missing required field routed to follow-up | 197/197 (100.0%) |
| Discount / multi-GST flagged as unsupported structure | 0/164 (0.0%) |
| Unsupported structure false flags | 0/336 (0.0%) |
| Failed requests | 0/500 (0.0%) |
| Extraction latency median / p95 (s) | 0.0 / 0.0 |
| OCR + extraction latency median / p95 (s) | 0.5 / 0.859 |
| Tokens total / median per doc | 0 / 0.0 |
