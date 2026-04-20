"""Manual CSV importer for historical trades.

For trades that Fidelity/Robinhood can't export (older than 5 years) or
ACAT transfers where the CSV has no cost basis, drop a hand-crafted CSV
into FIDELITY_WATCH_DIR or ROBINHOOD_WATCH_DIR, or run this helper
directly:

    docker compose exec importer python -m app.import_manual /path/to/trades.csv

Expected CSV format:
    account_key,date,symbol,action,quantity,unit_price,fee
    brokerage-fidelity,2020-09-23,TSLA,BUY,3,130.00,0
    brokerage-fidelity,2020-09-23,TSLA,BUY,3,131.09,0

Fields:
  * account_key  — a key from ACCOUNT_MAP (any broker type)
  * date         — YYYY-MM-DD
  * symbol       — ticker (YAHOO data source)
  * action       — BUY or SELL
  * quantity     — positive number
  * unit_price   — positive number (price per share)
  * fee          — optional, defaults to 0

Each row is deduped via the standard fingerprint, so re-running the
same CSV is safe.
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .activity import Activity
from .config import load_config
from .dedup import DedupStore
from .ghostfolio import GhostfolioClient

log = logging.getLogger(__name__)


def _parse_row(row: dict, accounts: dict, currency: str) -> Activity | None:
    key = (row.get("account_key") or "").strip()
    if not key:
        return None
    account = accounts.get(key)
    if not account:
        log.error("unknown account_key %r (not in ACCOUNT_MAP)", key)
        return None

    action = (row.get("action") or "").strip().upper()
    if action not in ("BUY", "SELL"):
        log.error("invalid action %r (must be BUY or SELL)", action)
        return None

    symbol = (row.get("symbol") or "").strip().upper()
    if not symbol:
        return None

    raw_date = (row.get("date") or "").strip()
    try:
        trade_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
    except ValueError:
        log.error("invalid date %r (want YYYY-MM-DD)", raw_date)
        return None

    try:
        quantity = Decimal(str(row.get("quantity") or "0"))
        unit_price = Decimal(str(row.get("unit_price") or "0"))
        fee = Decimal(str(row.get("fee") or "0"))
    except InvalidOperation:
        log.error("invalid number in row: %s", row)
        return None

    if quantity <= 0 or unit_price <= 0:
        return None

    return Activity(
        account_id=account.uuid,
        symbol=symbol,
        data_source="YAHOO",
        currency=currency,
        date=trade_date,
        action=action,
        quantity=quantity,
        unit_price=unit_price,
        fee=fee,
        source="manual",
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv_path", type=Path)
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse and print what would be imported, but don't POST")
    args = ap.parse_args(argv)

    cfg = load_config()
    logging.basicConfig(
        level=cfg.log_level,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if not args.csv_path.exists():
        log.error("file not found: %s", args.csv_path)
        return 2

    client = GhostfolioClient(
        cfg.ghostfolio_url, cfg.ghostfolio_token, tz=cfg.tz,
    )
    store = DedupStore(cfg.db_path)

    imported = 0
    skipped = 0
    errors = 0

    with open(args.csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):  # line 2 = first data row
            activity = _parse_row(row, cfg.accounts, cfg.default_currency)
            if activity is None:
                errors += 1
                continue

            fp = activity.fingerprint()
            if store.has(fp):
                skipped += 1
                continue

            if args.dry_run:
                print(f"WOULD IMPORT: {activity.date} {activity.action} "
                      f"{activity.symbol} qty={activity.quantity} "
                      f"@ {activity.unit_price} -> {activity.account_id}")
                imported += 1
                continue

            try:
                result = client.create_order(activity)
            except Exception:
                log.exception("failed to import row %d: %s", i, row)
                errors += 1
                continue

            store.record(fp, activity.source, activity.symbol,
                         activity.account_id, ghostfolio_id=result.get("id"))
            imported += 1
            log.info("imported %s %s %s qty=%s @ %s",
                     activity.date, activity.action, activity.symbol,
                     activity.quantity, activity.unit_price)

    client.close()
    print(f"Done: imported={imported} skipped(dup)={skipped} errors={errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
