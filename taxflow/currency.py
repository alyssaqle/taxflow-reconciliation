"""Supported currencies: ISO 4217 codes from the maintained ``pycountry`` dataset.

Non-money codes (precious metals, bond-market units, SDR, test/no-currency codes) and
fund codes are excluded. Currency is never inferred from a symbol and never converted.
"""
from __future__ import annotations

import importlib.metadata
from functools import lru_cache

import pycountry

EXCLUDED = {
    "XAG", "XAU", "XPD", "XPT",                 # precious metals
    "XBA", "XBB", "XBC", "XBD", "XDR", "XSU", "XUA",  # units of account
    "XTS", "XXX",                               # testing / no currency
    "BOV", "CHE", "CHW", "CLF", "COU", "MXV", "USN", "UYI", "UYW",  # fund codes
}


@lru_cache(maxsize=1)
def supported_codes() -> dict[str, str]:
    """alpha_3 -> English name, e.g. {"USD": "US Dollar", "EUR": "Euro"}."""
    return {c.alpha_3: c.name for c in pycountry.currencies if c.alpha_3 not in EXCLUDED}


def is_supported(code: str | None) -> bool:
    return code is not None and code.strip().upper() in supported_codes()


def normalize(code: str | None) -> str | None:
    return code.strip().upper() if code is not None else None


def data_version() -> str:
    return f"pycountry {importlib.metadata.version('pycountry')} (ISO 4217)"
