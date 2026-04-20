"""Shared parsing helpers and domain rules for all broker parsers."""
from __future__ import annotations

from datetime import date as date_cls, datetime
from decimal import Decimal, InvalidOperation


# Money market funds that act as cash sweeps. Dividends from these are
# real income (keep as DIVIDEND with symbol stripped to "USD"), but the
# matching reinvestment BUY is noise — we skip it.
CASH_EQUIVALENT_SYMBOLS = frozenset({
    "FDRXX",  # Fidelity Government Cash Reserves
    "SPAXX",  # Fidelity Government Money Market
    "FZFXX",  # Fidelity Treasury Money Market
    "FDIC",   # FDIC-insured sweep
    "CASH",
})


def is_cash_equivalent(symbol: str) -> bool:
    return (symbol or "").upper() in CASH_EQUIVALENT_SYMBOLS


def clean_money(raw: str) -> Decimal:
    """Strip '$', ',', parentheses, whitespace; return 0 for empty.

    Parentheses denote negatives in many broker CSVs (accounting style),
    e.g. '($1,234.56)' means -1234.56. We return the absolute value here
    and let the caller decide sign based on the transaction type — it's
    less error-prone than trying to preserve accounting signs.
    """
    if raw is None:
        return Decimal("0")
    s = str(raw).strip()
    if not s or s == "-":
        return Decimal("0")
    # Strip parentheses; we don't need the sign here
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    s = s.replace("$", "").replace(",", "").strip()
    if not s:
        return Decimal("0")
    try:
        return abs(Decimal(s))
    except InvalidOperation:
        return Decimal("0")


def clean_quantity(raw: str) -> Decimal:
    """Absolute quantity; sign is conveyed by action type (BUY/SELL)."""
    return clean_money(raw)


def parse_date(raw: str) -> date_cls | None:
    """Try common US broker date formats."""
    cleaned = (raw or "").strip()
    if not cleaned:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y", "%b-%d-%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None
