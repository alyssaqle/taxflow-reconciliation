"""Generate the reviewer-timing pilot: two comparable task sets (A, B) of 10 synthetic invoices each,
one pilot ledger, and a separate answer key. Usage: python -m pilot.generate_tasks

Each set has the same mix: 3 matched, 1 arithmetic-wrong-but-ledger-agrees, 1 amount difference,
1 currency difference, 1 date difference, 1 ambiguous (duplicate entries), 1 no matching entry,
1 missing required field. The ledger (~150 rows) also contains identical-amount decoys and unrelated
entries so that manual lookup is realistic. All data is synthetic.
"""
from __future__ import annotations

import csv
import json
import random
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
D = HERE / "data"
SEED = 4242
KINDS = ["match", "match", "match", "arithmetic", "amount", "currency", "date", "ambiguous", "no_entry", "missing_date"]
EXPECTED = {
    "match": ("Matched", "Approve", []),
    "arithmetic": ("Matched", "Needs follow-up", ["arithmetic"]),
    "amount": ("Discrepancy found", "Needs follow-up", ["amount"]),
    "currency": ("Discrepancy found", "Needs follow-up", ["currency"]),
    "date": ("Discrepancy found", "Needs follow-up", ["date"]),
    "ambiguous": ("Ambiguous match", "Needs follow-up", ["ambiguous"]),
    "no_entry": ("No matching entry", "Needs follow-up", ["no_entry"]),
    "missing_date": ("Needs clarification", "Needs follow-up", ["missing_field"]),
}
A = ["Alder", "Brook", "Cedar", "Dune", "Elm", "Fern", "Glen", "Heath", "Iris", "Jade", "Kelp", "Laurel", "Moss", "Nettle",
     "Oak", "Pine", "Quill", "Reed", "Sage", "Thorn", "Vine", "Wren"]
B = ["Advisory", "Analytics", "Catering", "Design", "Freight", "Legal", "Media", "Print", "Research", "Software", "Staffing"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def money(d: Decimal) -> str:
    return f"{d:,.2f}"


def invoice_text(vendor, number, date, currency, items, tax, total_override=None, omit_date=False) -> tuple[str, Decimal]:
    lts = [Decimal(q) * Decimal(p) for _, q, p in items]
    sub = sum(lts, Decimal("0"))
    total = Decimal(total_override) if total_override else sub + Decimal(tax)
    y, m, d = map(int, date.split("-"))
    L = [vendor.upper(), "Synthetic pilot document", "", "INVOICE", f"Invoice Number: {number}"]
    if not omit_date:
        L.append(f"Invoice Date: {MONTHS[m - 1]} {d}, {y}")
    L += [f"Currency: {currency}", "", f"{'Description':<28}{'Qty':>5}{'Unit Price':>12}{'Line Total':>12}"]
    for (desc, q, p), lt in zip(items, lts):
        L.append(f"{desc:<28}{q:>5}{money(Decimal(p)):>12}{money(lt):>12}")
    L += ["", f"Subtotal: {money(sub)}", f"Tax: {money(Decimal(tax))}", f"Total: {money(total)}", "",
          "All names and figures are fictional."]
    return "\n".join(L) + "\n", total


def main() -> None:
    rng = random.Random(SEED)
    D.mkdir(parents=True, exist_ok=True)
    vendors = rng.sample([f"{a} {b2} {b}" for a in A for b2 in A for b in B if a != b2], 60)
    ledger, tasks, answers = [], [], {}
    eid = iter(range(5001, 9999))

    def add_entry(number, vendor, date, cur, amount):
        e = f"PL-{next(eid)}"
        ledger.append([e, number, vendor, date, cur, amount])
        return e

    for set_name in ("A", "B"):
        kinds = KINDS[:]
        rng.shuffle(kinds)
        for i, kind in enumerate(kinds, 1):
            tid = f"{set_name}{i:02d}"
            vendor = vendors.pop()
            number = f"{vendor.split()[0][:2].upper()}{vendor.split()[1][:1].upper()}-{rng.randint(1000, 9999)}"
            date = f"2026-{rng.randint(1, 9):02d}-{rng.randint(10, 28):02d}"
            items = [(rng.choice(["Consulting hours", "Report preparation", "Data review", "Workshop", "Courier runs"]),
                      str(rng.randint(1, 8)), f"{rng.randint(40, 400)}.00") for _ in range(rng.randint(1, 3))]
            tax = f"{rng.randint(0, 120)}.00"
            override = None
            if kind == "arithmetic":
                lts = sum(Decimal(q) * Decimal(p) for _, q, p in items)
                override = f"{lts + Decimal(tax) + Decimal(rng.choice([50, 70, 100])):.2f}"
            text, total = invoice_text(vendor, number, date, "USD", items, tax, override, omit_date=kind == "missing_date")
            amt = f"{total:.2f}"
            entry = None
            if kind in ("match", "arithmetic", "missing_date"):
                entry = add_entry(number, vendor, date, "USD", amt)
            elif kind == "amount":
                entry = add_entry(number, vendor, date, "USD", f"{total + Decimal(rng.choice([9, 90, 250])):.2f}")
            elif kind == "currency":
                entry = add_entry(number, vendor, date, rng.choice(["EUR", "CAD"]), amt)
            elif kind == "date":
                entry = add_entry(number, vendor, f"2026-{int(date[5:7]) % 9 + 1:02d}-{date[8:]}", "USD", amt)
            elif kind == "ambiguous":
                add_entry(number, vendor, date, "USD", amt)
                add_entry(number, vendor, date, "USD", amt)
            # every task gets an identical-amount decoy with a different invoice number
            add_entry(number[:-1] + str((int(number[-1]) + 3) % 10), vendor, date, "USD", amt)
            (D / "invoices" / f"{tid}.txt").write_text(text)
            outcome, decision, disc = EXPECTED[kind]
            tasks.append({"task_id": tid, "set": set_name})
            answers[tid] = {"kind": kind, "expected_outcome": outcome, "expected_decision": decision,
                            "expected_discrepancies": disc, "expected_entry_id": entry}
    for _ in range(150 - len(ledger)):  # unrelated entries
        v = rng.choice(vendors)
        add_entry(f"{v[:2].upper()}X-{rng.randint(1000, 9999)}", v, f"2026-{rng.randint(1, 9):02d}-{rng.randint(10, 28):02d}",
                  "USD", f"{rng.randint(100, 9000)}.00")
    rng.shuffle(ledger)
    with (D / "pilot_ledger.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ledger_entry_id", "invoice_number", "vendor_name", "invoice_date", "currency", "gross_amount"])
        w.writerows(ledger)
    (D / "tasks.json").write_text(json.dumps(tasks, indent=1))
    (HERE / "answers.json").write_text(json.dumps(answers, indent=1))  # read only by pilot/analyze.py
    print(f"{len(tasks)} tasks, {len(ledger)} ledger rows")


if __name__ == "__main__":
    main()
