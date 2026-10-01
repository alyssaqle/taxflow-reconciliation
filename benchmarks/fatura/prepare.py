"""Select template-disjoint dev/eval documents, extract their images, OCR them, and derive labels.

Usage: python -m benchmarks.fatura.prepare

Writes (all under data_private/, git-ignored, except the manifest):
  benchmarks/fatura/manifest.csv            neutral id -> source file, template, split (committed)
  data_private/fatura/images/<id>.jpg
  data_private/fatura/ocr/<id>.txt          Tesseract 5 output, the pipeline's only input

OCR settings (chosen on the 50 dev documents only): images are 595x841 px (~72 dpi), so each is
upscaled 2x with Lanczos, then OCR'd with Tesseract --psm 3 (automatic page segmentation). On dev,
label values present in OCR text rose from 56.3% (psm 6, original size) to 98.1%.
  data_private/fatura/labels/<id>.json      derived labels (read only by the scorer)
"""
from __future__ import annotations

import csv
import json
import random
import subprocess
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .labels import derive

PROJECT = Path(__file__).resolve().parents[2]
ZIP = PROJECT / "data_private" / "FATURA.zip"
OUT = PROJECT / "data_private" / "fatura"
MANIFEST = Path(__file__).resolve().parent / "manifest.csv"
SEED = 20261001
DEV_TEMPLATES, DEV_PER_TEMPLATE, EVAL_TOTAL = 10, 5, 500
PREFIX = "invoices_dataset_final/"


def select(names: list[str]) -> list[dict]:
    rng = random.Random(SEED)
    by_t: dict[int, list[str]] = {}
    for n in names:
        t = int(n.split("Template")[1].split("_")[0])
        by_t.setdefault(t, []).append(n)
    templates = sorted(by_t)
    rng.shuffle(templates)
    dev_t, eval_t = templates[:DEV_TEMPLATES], templates[DEV_TEMPLATES:]
    rows = []
    for t in sorted(dev_t):
        for n in rng.sample(sorted(by_t[t]), DEV_PER_TEMPLATE):
            rows.append({"split": "dev", "template": t, "source": n})
    per = [EVAL_TOTAL // len(eval_t) + (1 if i < EVAL_TOTAL % len(eval_t) else 0) for i in range(len(eval_t))]
    for t, k in zip(sorted(eval_t), per):
        for n in rng.sample(sorted(by_t[t]), k):
            rows.append({"split": "eval", "template": t, "source": n})
    order = list(range(len(rows)))
    rng.shuffle(order)  # neutral ids carry no split/template information
    for i, idx in enumerate(order, 1):
        rows[idx]["doc_id"] = f"fdoc_{i:04d}"
    return sorted(rows, key=lambda r: r["doc_id"])


OCR_SCALE, OCR_PSM = 2, 3


def ocr(img: Path) -> tuple[str, float]:
    from PIL import Image

    t0 = time.perf_counter()
    big = img.with_suffix(".x2.png")
    with Image.open(img) as im:
        im.resize((im.width * OCR_SCALE, im.height * OCR_SCALE), Image.LANCZOS).save(big)
    text = subprocess.run(["tesseract", str(big), "stdout", "--psm", str(OCR_PSM)], capture_output=True, text=True,
                          check=True).stdout
    big.unlink()
    return text, time.perf_counter() - t0


def main() -> None:
    import sys
    labels_only = "--labels-only" in sys.argv
    zf = zipfile.ZipFile(ZIP)
    images = [n[len(PREFIX + "images/"):] for n in zf.namelist() if n.startswith(PREFIX + "images/") and n.endswith(".jpg")]
    rows = select(images)
    for d in ("images", "ocr", "labels"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    for r in rows:
        stem = r["source"][:-4]
        ann = json.loads(zf.read(f"{PREFIX}Annotations/Original_Format/{stem}.json"))
        (OUT / "labels" / f"{r['doc_id']}.json").write_text(json.dumps(derive(ann), indent=1))
        if not labels_only:
            (OUT / "images" / f"{r['doc_id']}.jpg").write_bytes(zf.read(f"{PREFIX}images/{r['source']}"))
    if labels_only:
        print("labels regenerated")
        return

    def work(r):
        text, secs = ocr(OUT / "images" / f"{r['doc_id']}.jpg")
        (OUT / "ocr" / f"{r['doc_id']}.txt").write_text(text)
        return r["doc_id"], secs

    with ThreadPoolExecutor(max_workers=6) as ex:
        secs = dict(ex.map(work, rows))
    for r in rows:
        r["ocr_seconds"] = round(secs[r["doc_id"]], 3)
    with MANIFEST.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["doc_id", "split", "template", "source", "ocr_seconds"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} documents: {sum(r['split']=='dev' for r in rows)} dev, {sum(r['split']=='eval' for r in rows)} eval")


if __name__ == "__main__":
    main()
