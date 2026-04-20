"""Centralized configuration loaded from environment variables."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

Broker = Literal["fidelity", "robinhood", "manual"]


@dataclass(frozen=True)
class AccountInfo:
    """One entry from ACCOUNT_MAP, parsed."""
    key: str         # friendly name, also the subfolder name
    uuid: str        # Ghostfolio account UUID
    broker: Broker   # which parser/watcher handles this account


@dataclass(frozen=True)
class Config:
    # Ghostfolio connection
    ghostfolio_url: str
    ghostfolio_token: str
    default_currency: str
    tz: str

    # Per-account info keyed by friendly name.
    accounts: dict  # key -> AccountInfo

    # Broker-specific drop directories
    fidelity_watch_dir: Path
    robinhood_watch_dir: Path

    # Symbols to use MANUAL data source for (delisted tickers Yahoo
    # Finance no longer carries). Frozenset for O(1) lookup.
    manual_symbols: frozenset

    # HTTP endpoint
    http_port: int
    http_token: str

    # Dedup store
    db_path: Path

    # Logging
    log_level: str


def _parse_account_map(raw: str) -> dict[str, AccountInfo]:
    """Parse "key=uuid:broker,key2=uuid2:broker2" into a dict of AccountInfo."""
    result: dict[str, AccountInfo] = {}
    for pair in (raw or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        key, _, rest = pair.partition("=")
        key = key.strip()
        if not key or not rest:
            log.warning("ACCOUNT_MAP: skipping malformed entry %r", pair)
            continue
        uuid, _, broker = rest.partition(":")
        uuid = uuid.strip()
        broker = (broker or "manual").strip().lower()
        if broker not in ("fidelity", "robinhood", "manual"):
            log.warning(
                "ACCOUNT_MAP: %s has unknown broker %r; treating as manual",
                key, broker,
            )
            broker = "manual"
        result[key] = AccountInfo(key=key, uuid=uuid, broker=broker)  # type: ignore[arg-type]
    return result


def load_config() -> Config:
    return Config(
        ghostfolio_url=os.environ["GHOSTFOLIO_URL"].rstrip("/"),
        ghostfolio_token=os.environ["GHOSTFOLIO_TOKEN"],
        default_currency=os.environ.get("DEFAULT_CURRENCY", "USD"),
        tz=os.environ.get("TZ", "UTC"),
        accounts=_parse_account_map(os.environ.get("ACCOUNT_MAP", "")),
        fidelity_watch_dir=Path(os.environ.get("FIDELITY_WATCH_DIR", "/fidelity-drop")),
        robinhood_watch_dir=Path(os.environ.get("ROBINHOOD_WATCH_DIR", "/robinhood-drop")),
        manual_symbols=frozenset(
            s.strip().upper()
            for s in os.environ.get("MANUAL_SYMBOLS", "").split(",")
            if s.strip()
        ),
        http_port=int(os.environ.get("HTTP_PORT", "8080")),
        http_token=os.environ.get("HTTP_TOKEN", ""),
        db_path=Path(os.environ.get("DB_PATH", "/state/dedup.sqlite")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )


def accounts_by_broker(accounts: dict, broker: Broker) -> dict:
    """Filter the accounts dict to only entries for the given broker."""
    return {k: v for k, v in accounts.items() if v.broker == broker}
