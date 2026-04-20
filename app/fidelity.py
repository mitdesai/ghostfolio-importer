"""Parse Fidelity's single-account 'Download transactions' CSV export.

Action classification:
  * "YOU BOUGHT ..." -> BUY
  * "YOU SOLD ..."   -> SELL
  * Everything else  -> skipped (dividends, reinvestments, transfers,
    interest, fees — all just cash movements, not share count changes)

This matches the "track investment growth only" principle — dividends
that sit as cash or get reinvested into cash sweeps (FDRXX) don't
change the portfolio growth story we care about.
"""
from __future__ import annotations

import csv
import logging
import re
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from .activity import Activity
from .parsing import clean_money, clean_quantity, parse_date

log = logging.getLogger(__name__)


_ACTION_BUY = re.compile(r"^\s*YOU BOUGHT", re.IGNORECASE)
_ACTION_SELL = re.compile(r"^\s*YOU SOLD", re.IGNORECASE)


def _normalize_header(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "")).strip()


def parse_fidelity_csv(
    path: Path,
    account_id: str,
    default_currency: str = "USD",
) -> Iterator[Activity]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)

        header = None
        for row in reader:
            norm = [_normalize_header(c) for c in row]
            if norm and norm[0] == "Run Date":
                header = norm
                break
        if header is None:
            log.warning("%s: no 'Run Date' header found, skipping", path.name)
            return

        idx = {name: i for i, name in enumerate(header)}
        required = ["Run Date", "Action", "Symbol", "Quantity", "Price ($)"]
        missing = [r for r in required if r not in idx]
        if missing:
            log.error("%s: missing columns %s (got %s)",
                      path.name, missing, list(idx))
            return

        max_idx = max(idx.values())
        for row in reader:
            if not row or not any(c.strip() for c in row):
                continue
            if len(row) <= max_idx:
                log.debug("%s: skipping short row: %s", path.name, row)
                continue

            action_text = row[idx["Action"]].strip()
            if _ACTION_BUY.match(action_text):
                action = "BUY"
            elif _ACTION_SELL.match(action_text):
                action = "SELL"
            else:
                continue

            symbol = row[idx["Symbol"]].strip().upper()
            if not symbol:
                continue

            trade_date = parse_date(row[idx["Run Date"]])
            if not trade_date:
                log.warning("%s: bad date on row: %s", path.name, row)
                continue

            quantity = clean_quantity(row[idx["Quantity"]])
            unit_price = clean_money(row[idx["Price ($)"]])
            if quantity <= 0 or unit_price <= 0:
                continue

            fee = Decimal("0")
            if "Commission ($)" in idx:
                fee += clean_money(row[idx["Commission ($)"]])
            if "Fees ($)" in idx:
                fee += clean_money(row[idx["Fees ($)"]])

            yield Activity(
                account_id=account_id,
                symbol=symbol,
                data_source="YAHOO",
                currency=default_currency,
                date=trade_date,
                action=action,
                quantity=quantity,
                unit_price=unit_price,
                fee=fee,
                source="fidelity",
            )
