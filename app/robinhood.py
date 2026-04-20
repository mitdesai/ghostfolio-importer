"""Parse Robinhood 'Account Activity' CSV export.

Format (2026):
    "Activity Date","Process Date","Settle Date","Instrument","Description",
    "Trans Code","Quantity","Price","Amount"

Trans Codes:
  * Buy / Sell   -> BUY / SELL (imported)
  * CDIV         -> skipped (cash dividend, DRIP not enabled — pure cash)
  * SLIP         -> skipped (Stock Lending Income Program — pure cash)
  * MTCH         -> skipped (IRA Match interest — cash)
  * ACATI/ACATO  -> WARNING log per row (account transfer; shares exist
                    but no cost basis. User needs manual import.)
  * Everything else -> logged + skipped

Quirks:
  * Descriptions are multi-line quoted strings — csv module handles them
    correctly because they're properly quoted.
  * Price/Amount are dollar-prefixed: "$19.26" or "($2,233.58)". We take
    absolute values; the Trans Code determines the sign.
  * The last row of the file is a disclaimer with all blank fields
    except the last column. Trans Code being empty is our skip signal.
"""
from __future__ import annotations

import csv
import logging
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from .activity import Activity
from .parsing import clean_money, clean_quantity, parse_date

log = logging.getLogger(__name__)


_IMPORTED = {"Buy": "BUY", "Sell": "SELL"}

# Codes we skip silently (common, expected, not actionable)
_QUIETLY_SKIPPED = {
    "CDIV", "SLIP", "MTCH", "INT", "ACH", "AFEE", "DFEE",
    "GOLD", "SPR", "REC", "TAX", "WITH",
    "SPL",   # stock split — Ghostfolio pulls split history from Yahoo automatically
    "RTP",   # SPAC redemption — cash event
    "GMPC",  # Robinhood Gold payment — cash fee
    "BCXL",  # buy cancellation / order correction
    "MISC",  # miscellaneous cash adjustment
}

# Transfer-in/out — user-actionable: shares move but no cost basis
_TRANSFER_CODES = {"ACATI", "ACATO"}


def parse_robinhood_csv(
    path: Path,
    account_id: str,
    default_currency: str = "USD",
) -> Iterator[Activity]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            log.warning("%s: empty file", path.name)
            return

        header = [h.strip() for h in header]
        idx = {name: i for i, name in enumerate(header)}
        required = ["Activity Date", "Instrument", "Trans Code",
                    "Quantity", "Price", "Amount"]
        missing = [r for r in required if r not in idx]
        if missing:
            log.error("%s: missing columns %s (got %s)",
                      path.name, missing, list(idx))
            return

        max_idx = max(idx.values())
        transfer_rows: list[str] = []
        unknown_codes: Counter[str] = Counter()

        for row in reader:
            if not row or not any(c.strip() for c in row):
                continue
            if len(row) <= max_idx:
                log.debug("%s: skipping short row: %s", path.name, row)
                continue

            trans_code = row[idx["Trans Code"]].strip()
            if not trans_code:
                continue  # disclaimer / blank row

            if trans_code in _TRANSFER_CODES:
                symbol = row[idx["Instrument"]].strip().upper()
                qty = row[idx["Quantity"]].strip()
                trans_date = row[idx["Activity Date"]].strip()
                if symbol and qty:
                    transfer_rows.append(f"{trans_date} {symbol} qty={qty}")
                continue

            if trans_code in _QUIETLY_SKIPPED:
                continue

            action = _IMPORTED.get(trans_code)
            if action is None:
                unknown_codes[trans_code] += 1
                continue

            activity = _build_trade(
                row, idx, action, account_id, default_currency, path.name,
            )
            if activity is not None:
                yield activity

        # Post-processing summary logs
        if transfer_rows:
            log.warning(
                "%s: %d ACAT transfer rows — these shares have no cost "
                "basis in the CSV. Use the manual import helper to add "
                "them with their original purchase prices: %s",
                path.name, len(transfer_rows), "; ".join(transfer_rows),
            )
        for code, n in unknown_codes.items():
            log.warning(
                "%s: %d rows with unknown Trans Code %r — not imported",
                path.name, n, code,
            )


def _build_trade(
    row, idx, action, account_id, currency, filename,
) -> Activity | None:
    symbol = row[idx["Instrument"]].strip().upper()
    if not symbol:
        return None

    trade_date = parse_date(row[idx["Activity Date"]])
    if not trade_date:
        log.warning("%s: bad date on row: %s", filename, row)
        return None

    quantity = clean_quantity(row[idx["Quantity"]])
    unit_price = clean_money(row[idx["Price"]])
    if quantity <= 0 or unit_price <= 0:
        return None

    return Activity(
        account_id=account_id,
        symbol=symbol,
        data_source="YAHOO",
        currency=currency,
        date=trade_date,
        action=action,
        quantity=quantity,
        unit_price=unit_price,
        fee=Decimal("0"),
        source="robinhood",
    )
