# FATURA extraction benchmark · eval · live · 20261001T200811Z-eval-live

**Data:** FATURA (Limam, Dhiaf & Kessentini 2023, Zenodo doi:10.5281/zenodo.8261508, CC BY 4.0): **synthetic** invoice images generated from 50 templates by the dataset authors. Dev and eval use disjoint templates. Input to TaxFlow is our own Tesseract 5 OCR of each image (2x Lanczos upscale, psm 3; settings chosen on dev only); the images are processed by our pipeline, but OCR is Tesseract, not a TaxFlow model.
**System:** Azure OpenAI (v1 API, Chat Completions) · model `gpt-4.1-mini` · prompt extract-v6+agent-v2 · schema reconciliation-v2
**Documents:** selected 500, attempted 500, skipped by token budget 0 (budget 3,000,000; used 1,428,535) · wall time 1208.0 s

| Field | Accuracy | Missing | Wrong | Expected null → correct / invented | Not scored (unknown) | OCR ceiling | Evidence valid |
|---|---|---|---|---|---|---|---|
| vendor_name | 276/328 (84.2%) | 21 | 31 | 0 / 0 of 0 | 172 | 320/328 (97.6%) | 307/307 (100.0%) |
| invoice_number | 412/438 (94.1%) | 4 | 22 | 49 / 0 of 49 | 13 | 423/438 (96.6%) | 434/434 (100.0%) |
| invoice_date | 478/487 (98.2%) | 8 | 1 | 13 / 0 of 13 | 0 | 479/487 (98.4%) | 478/479 (99.8%) |
| currency | 265/266 (99.6%) | 1 | 0 | 135 / 0 of 135 | 99 | 266/266 (100.0%) | 247/265 (93.2%) |
| total | 399/401 (99.5%) | 2 | 0 | 0 / 0 of 0 | 99 | 401/401 (100.0%) | 397/399 (99.5%) |
| subtotal | 342/348 (98.3%) | 3 | 3 | 0 / 0 of 0 | 152 | 343/348 (98.6%) | 344/345 (99.7%) |
| tax | 199/213 (93.4%) | 12 | 2 | 0 / 0 of 0 | 287 | 206/213 (96.7%) | 199/201 (99.0%) |

| Aggregate metric | Result |
|---|---|
| Aggregate field accuracy | 2371/2481 (95.6%) |
| Missing predictions / wrong values | 51 / 59 |
| Invented values (expected null) | 0/197 (0.0%) |
| Docs with all scorable required fields correct | 423/500 (84.6%) |
| Docs with all 5 required fields scorable and correct | 216/277 (78.0%) |
| Evidence validity (all non-null predictions) | 2529/2556 (98.9%) |
| Routed as invoice | 498/500 (99.6%) |
| Missing required field routed to follow-up | 196/197 (99.5%) |
| Discount / multi-GST flagged as unsupported structure | 159/164 (97.0%) |
| Unsupported structure false flags | 4/336 (1.2%) |
| Failed requests | 0/500 (0.0%) |
| Extraction latency median / p95 (s) | 6.8915 / 13.337 |
| OCR + extraction latency median / p95 (s) | 7.397 / 13.84 |
| Tokens total / median per doc | 1,428,535 / 2828.5 |
