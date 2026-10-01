"""Accounting ledger CSV: load and validate before any processing.

Required columns (exact names, in any order):
    ledger_entry_id, invoice_number, vendor_name, invoice_date, currency, gross_amount

MVP assumption: one accounting entry per invoice (no split postings or credit notes).
Row numbers follow spreadsheet convention: the header is row 1, the first entry is row 2.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
from dataclasses import dataclass
from functools import cached_property

from .currency import is_supported, normalize
from .models import LedgerEntry
from .parsing import InputError

COLUMNS = ["ledger_entry_id", "invoice_number", "vendor_name", "invoice_date", "currency", "gross_amount"]
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5_000
_MONEY_RE = re.compile(r"^\d+(\.\d{1,2})?$")
TEMPLATE_CSV = ",".join(COLUMNS) + "\n"


class LedgerError(InputError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        shown = errors[:12]
        more = f" (+{len(errors) - len(shown)} more)" if len(errors) > len(shown) else ""
        super().__init__("Ledger CSV rejected: " + "; ".join(shown) + more)


@dataclass(frozen=True)
class Ledger:
    ledger_id: str
    name: str
    entries: tuple[LedgerEntry, ...]

    @cached_property
    def index(self) -> dict:
        """Lookup index on the normalized (invoice_number, vendor_name) key, built once per ledger."""
        from .matching import build_index
        return build_index(self.entries)


def parse_ledger_csv(text: str, name: str, max_rows: int = MAX_ROWS) -> Ledger:
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip() for h in (reader.fieldnames or [])]
    errors: list[str] = []
    missing = [c for c in COLUMNS if c not in header]
    extra = [c for c in header if c not in COLUMNS]
    dupes = sorted({c for c in header if header.count(c) > 1})
    if missing:
        errors.append("missing column(s): " + ", ".join(missing))
    if extra:
        errors.append("unexpected column(s): " + ", ".join(extra))
    if dupes:
        errors.append("duplicate column(s): " + ", ".join(dupes))
    if errors:
        raise LedgerError(errors)
    reader.fieldnames = header

    entries: list[LedgerEntry] = []
    seen: dict[str, int] = {}
    for idx, raw in enumerate(reader, start=2):
        if idx - 1 > max_rows:
            raise LedgerError([f"more than {max_rows} rows"])
        if None in raw:  # more cells than headers
            errors.append(f"row {idx}: too many cells")
            continue
        row = {k: (v or "").strip() for k, v in raw.items()}
        if not any(row.values()):
            continue  # ignore fully blank lines
        problems = []
        for col in ("ledger_entry_id", "invoice_number", "vendor_name"):
            if not row[col]:
                problems.append(f"{col} is empty")
        try:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", row["invoice_date"]):
                raise ValueError
            dt.date.fromisoformat(row["invoice_date"])
        except ValueError:
            problems.append(f"invoice_date '{row['invoice_date']}' is not YYYY-MM-DD")
        if not is_supported(row["currency"]):
            problems.append(f"currency '{row['currency']}' is not a supported ISO 4217 code")
        if not _MONEY_RE.match(row["gross_amount"]):
            problems.append(f"gross_amount '{row['gross_amount']}' is not a nonnegative amount with at most 2 decimals")
        eid = row["ledger_entry_id"]
        if eid and eid in seen:
            problems.append(f"ledger_entry_id '{eid}' duplicates row {seen[eid]}")
        elif eid:
            seen[eid] = idx
        if problems:
            errors.extend(f"row {idx}: {p}" for p in problems)
            continue
        entries.append(LedgerEntry(
            ledger_entry_id=eid, row_number=idx, invoice_number=row["invoice_number"],
            vendor_name=row["vendor_name"], invoice_date=row["invoice_date"],
            currency=normalize(row["currency"]), gross_amount=row["gross_amount"],
        ))
    if errors:
        raise LedgerError(errors)
    if not entries:
        raise LedgerError(["the file has no ledger entries"])
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return Ledger(ledger_id=f"ledger-{digest}", name=name, entries=tuple(entries))


def decode_ledger_upload(data: bytes, filename: str) -> Ledger:
    if not filename.lower().endswith(".csv"):
        raise InputError("The accounting file must be a .csv file.")
    if not data:
        raise InputError("The accounting file is empty.")
    if len(data) > MAX_BYTES:
        raise InputError("The accounting file is larger than 2 MB.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("The accounting file is not valid UTF-8.") from None
    return parse_ledger_csv(text, filename)
