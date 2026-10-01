"""Generate reproducible synthetic ledgers (1k / 10k / 100k rows) and 1,000 labeled queries per scale.

These are controlled, generated accounting records: not real client data, and not derived from
any public document set. Labels come from how each query is *constructed*, never from running
TaxFlow's matching code.

Ledger composition (per scale N, seed-controlled):
* base entries (unique invoice number + vendor);
* duplicate groups: an extra entry repeating a base entry's invoice number and vendor (~4% of rows);
* identical-amount decoys: same vendor and gross amount as a base entry but a near-miss invoice
  number (two digits transposed) (~6% of rows).

Query mix per scale (1,000):
  match_exact 250 · match_normalized (case/whitespace variants) 80 · match_within_tolerance 40
  amount_diff 120 · currency_diff 80 · date_diff 80 · duplicate 120
  missing_near_miss (number absent; an identical-amount decoy exists) 100
  missing_wrong_vendor (number exists under another vendor) 50
  missing_identifier 80

Usage: python -m benchmarks.ledger_scale.generate
Writes data_private/ledger_scale/ledger_<N>.csv, queries_<N>.jsonl (agent-side input) and
labels_<N>.jsonl (scorer-side), plus benchmarks/ledger_scale/manifest.json (committed hashes).
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import random
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "data_private" / "ledger_scale"
SCALES = (1_000, 10_000, 100_000)
SEED = 20261001
MIX = [("match_exact", 250), ("match_normalized", 80), ("match_within_tolerance", 40), ("amount_diff", 120),
       ("currency_diff", 80), ("date_diff", 80), ("duplicate", 120), ("missing_near_miss", 100),
       ("missing_wrong_vendor", 50), ("missing_identifier", 80)]
CURRENCIES = ["USD"] * 7 + ["EUR", "GBP", "CAD"]
WORDS_A = ["Aster", "Birch", "Cobalt", "Delta", "Ember", "Fjord", "Granite", "Harbor", "Indigo", "Juniper", "Kestrel",
           "Lumen", "Maple", "Nimbus", "Onyx", "Pioneer", "Quarry", "Ridge", "Summit", "Tidal", "Umber", "Vale",
           "Willow", "Xenon", "Yarrow", "Zephyr"]
WORDS_B = ["Analytics", "Consulting", "Logistics", "Media", "Partners", "Supply", "Studios", "Services", "Systems",
           "Works", "Advisory", "Labs"]
SUFFIX = ["LLC", "Inc", "Ltd", "Co", "Group", ""]


def _vendors(rng: random.Random, n: int) -> list[str]:
    names = set()
    while len(names) < n:
        names.add(" ".join(x for x in (rng.choice(WORDS_A), rng.choice(WORDS_A), rng.choice(WORDS_B),
                                        rng.choice(SUFFIX)) if x))
    return sorted(names)


def _transpose(num: str, rng: random.Random) -> str:
    digits = [i for i in range(len(num) - 1) if num[i].isdigit() and num[i + 1].isdigit() and num[i] != num[i + 1]]
    i = rng.choice(digits)
    return num[:i] + num[i + 1] + num[i] + num[i + 2:]


def build(n: int) -> tuple[list[list[str]], list[dict], list[dict]]:
    rng = random.Random(SEED + n)
    vendors = _vendors(rng, max(300, n // 40))
    n_dup, n_decoy = int(n * 0.04), int(n * 0.06)
    n_base = n - n_dup - n_decoy
    used_numbers: set[str] = set()
    base = []
    for i in range(n_base):
        while True:
            num = f"{rng.choice(['INV', 'SI', 'BL'])}-{rng.randint(2024, 2026)}-{rng.randint(100000, 999999)}"
            if num not in used_numbers:
                used_numbers.add(num)
                break
        d = dt.date(2025, 1, 1) + dt.timedelta(days=rng.randint(0, 600))
        base.append({"invoice_number": num, "vendor_name": rng.choice(vendors), "invoice_date": d.isoformat(),
                     "currency": rng.choice(CURRENCIES), "gross_amount": f"{Decimal(rng.randint(1000, 5_000_000)) / 100:.2f}"})
    rng.shuffle(base)
    dup_targets = base[:n_dup]                      # these numbers appear twice
    decoy_targets = base[n_dup:n_dup + n_decoy]     # these have an identical-amount near-miss decoy
    clean = base[n_dup + n_decoy:]                  # unique, no decoy
    rows = [dict(b) for b in base]
    for b in dup_targets:
        extra = dict(b)
        extra["gross_amount"] = rng.choice([b["gross_amount"], f"{Decimal(b['gross_amount']) + 25:.2f}"])
        rows.append(extra)
    decoy_numbers = {}
    for b in decoy_targets:
        while True:
            dn = _transpose(b["invoice_number"], rng)
            if dn not in used_numbers:
                used_numbers.add(dn)
                break
        decoy_numbers[b["invoice_number"]] = dn
        rows.append({**b, "invoice_number": dn})
    rng.shuffle(rows)
    for i, r in enumerate(rows):
        r["ledger_entry_id"] = f"LE-{n}-{i + 1:06d}"
    ids_by_key: dict[tuple, list[str]] = {}
    for r in rows:
        ids_by_key.setdefault((r["invoice_number"], r["vendor_name"]), []).append(r["ledger_entry_id"])
    by_num = {r["invoice_number"]: r for r in rows}

    queries, labels = [], []
    pools = {"clean": list(clean), "decoy": list(decoy_targets)}
    rng.shuffle(pools["clean"])

    def take_clean():
        return pools["clean"].pop()

    qn = 0
    for kind, count in MIX:
        for _ in range(count):
            qn += 1
            qid = f"q{n}-{qn:04d}"
            if kind == "duplicate":
                b = dup_targets[qn % len(dup_targets)]
            elif kind == "missing_near_miss":
                b = decoy_targets[qn % len(decoy_targets)]
            else:
                b = take_clean()
            inv = {k: b[k] for k in ("invoice_number", "vendor_name", "invoice_date", "currency")}
            inv["total"] = b["gross_amount"]
            key = (b["invoice_number"], b["vendor_name"])
            entry, cands, outcome, codes = None, [], None, []
            if kind == "match_exact":
                entry = ids_by_key[key][0]; cands = [entry]; outcome = "Matched"
            elif kind == "match_normalized":
                inv["invoice_number"] = "  " + b["invoice_number"].lower() + " "
                inv["vendor_name"] = b["vendor_name"].upper().replace(" ", "   ")
                entry = ids_by_key[key][0]; cands = [entry]; outcome = "Matched"
            elif kind == "match_within_tolerance":
                inv["total"] = f"{Decimal(b['gross_amount']) + Decimal(rng.choice(['0.01', '-0.01'])):.2f}"
                if Decimal(inv["total"]) < 0:
                    inv["total"] = b["gross_amount"]
                entry = ids_by_key[key][0]; cands = [entry]; outcome = "Matched"
            elif kind == "amount_diff":
                inv["total"] = f"{Decimal(b['gross_amount']) + Decimal(rng.choice(['0.02', '0.50', '9.00', '100.00', '1000.00'])):.2f}"
                entry = ids_by_key[key][0]; cands = [entry]; outcome = "Discrepancy found"; codes = ["LEDGER_AMOUNT_MISMATCH"]
            elif kind == "currency_diff":
                inv["currency"] = rng.choice([c for c in ("USD", "EUR", "GBP", "CAD", "JPY") if c != b["currency"]])
                entry = ids_by_key[key][0]; cands = [entry]; outcome = "Discrepancy found"; codes = ["LEDGER_CURRENCY_MISMATCH"]
            elif kind == "date_diff":
                d = dt.date.fromisoformat(b["invoice_date"]) + dt.timedelta(days=rng.choice([-31, -1, 1, 3, 30]))
                inv["invoice_date"] = d.isoformat()
                entry = ids_by_key[key][0]; cands = [entry]; outcome = "Discrepancy found"; codes = ["LEDGER_DATE_MISMATCH"]
            elif kind == "duplicate":
                cands = sorted(ids_by_key[key]); outcome = "Ambiguous match"; codes = ["LEDGER_AMBIGUOUS"]
            elif kind == "missing_near_miss":
                # the real number was never recorded; the ledger only has the identical-amount near-miss decoy
                while True:
                    num = _transpose(decoy_numbers[b["invoice_number"]], rng)
                    if num not in by_num:
                        break
                inv["invoice_number"] = num
                outcome = "No matching entry"; codes = ["LEDGER_NO_MATCH"]
            elif kind == "missing_wrong_vendor":
                inv["vendor_name"] = next(v for v in vendors if (b["invoice_number"], v) not in ids_by_key)
                outcome = "No matching entry"; codes = ["LEDGER_NO_MATCH"]
            elif kind == "missing_identifier":
                inv["invoice_number"] = None
                outcome = "Needs clarification"; codes = ["LEDGER_NOT_SEARCHED"]
            queries.append({"query_id": qid, **inv})
            labels.append({"query_id": qid, "kind": kind, "expected_outcome": outcome, "expected_entry_id": entry,
                           "expected_candidate_ids": cands, "expected_codes": codes})
    order = list(range(len(queries)))
    rng.shuffle(order)
    queries = [queries[i] for i in order]
    labels = [labels[i] for i in order]
    cols = ["ledger_entry_id", "invoice_number", "vendor_name", "invoice_date", "currency", "gross_amount"]
    return [[r[c] for c in cols] for r in rows], queries, labels


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"seed": SEED, "query_mix": dict(MIX), "files": {}}
    for n in SCALES:
        rows, queries, labels = build(n)
        lp = OUT / f"ledger_{n}.csv"
        with lp.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ledger_entry_id", "invoice_number", "vendor_name", "invoice_date", "currency", "gross_amount"])
            w.writerows(rows)
        (OUT / f"queries_{n}.jsonl").write_text("".join(json.dumps(q) + "\n" for q in queries))
        (OUT / f"labels_{n}.jsonl").write_text("".join(json.dumps(l) + "\n" for l in labels))
        manifest["files"][str(n)] = {
            "rows": len(rows), "queries": len(queries),
            "ledger_sha256": hashlib.sha256(lp.read_bytes()).hexdigest(),
            "queries_sha256": hashlib.sha256((OUT / f"queries_{n}.jsonl").read_bytes()).hexdigest(),
            "labels_sha256": hashlib.sha256((OUT / f"labels_{n}.jsonl").read_bytes()).hexdigest(),
        }
        print(f"{n:>7} rows · {len(queries)} queries")
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
