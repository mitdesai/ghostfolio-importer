"""Main entry point. Wires up Fidelity watcher, Robinhood watcher, and
the HTTP endpoint for the iOS shortcut."""
from __future__ import annotations

import logging
import signal
import sys
import threading
import time

from .config import accounts_by_broker, load_config
from .dedup import DedupStore
from .fidelity import parse_fidelity_csv
from .ghostfolio import GhostfolioClient
from .robinhood import parse_robinhood_csv
from .shortcut_server import ShortcutServer
from .watcher import CsvDropWatcher


def main() -> int:
    cfg = load_config()

    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    log = logging.getLogger("main")
    log.info("ghostfolio-importer starting up")

    if not cfg.accounts:
        log.error("ACCOUNT_MAP is empty; nothing to do")
        return 2

    client = GhostfolioClient(
        cfg.ghostfolio_url, cfg.ghostfolio_token,
        tz=cfg.tz,
        manual_symbols=cfg.manual_symbols,
    )
    if not client.health():
        log.warning("Ghostfolio health check failed; will keep trying")
    store = DedupStore(cfg.db_path)
    log.info("dedup store has %d records", store.count())

    threads: list[threading.Thread] = []

    # --- HTTP endpoint for iOS shortcut ---
    if cfg.http_token:
        account_keys_to_uuid = {k: v.uuid for k, v in cfg.accounts.items()}
        http = ShortcutServer(
            port=cfg.http_port,
            auth_token=cfg.http_token,
            account_map=account_keys_to_uuid,
            currency=cfg.default_currency,
            client=client,
            store=store,
        )
        threads.append(http.run_in_thread())
    else:
        log.info("HTTP_TOKEN not set; shortcut endpoint disabled")

    # --- Fidelity watcher ---
    fidelity_accounts = accounts_by_broker(cfg.accounts, "fidelity")
    if fidelity_accounts:
        fid_uuids = {k: v.uuid for k, v in fidelity_accounts.items()}
        watcher = CsvDropWatcher(
            name="fidelity",
            watch_dir=cfg.fidelity_watch_dir,
            account_uuids=fid_uuids,
            parser=parse_fidelity_csv,
            currency=cfg.default_currency,
            client=client,
            store=store,
        )
        t = threading.Thread(target=watcher.run_forever, daemon=True, name="fidelity")
        t.start()
        threads.append(t)
    else:
        log.info("No Fidelity accounts in ACCOUNT_MAP; Fidelity watcher disabled")

    # --- Robinhood watcher ---
    rh_accounts = accounts_by_broker(cfg.accounts, "robinhood")
    if rh_accounts:
        rh_uuids = {k: v.uuid for k, v in rh_accounts.items()}
        watcher = CsvDropWatcher(
            name="robinhood",
            watch_dir=cfg.robinhood_watch_dir,
            account_uuids=rh_uuids,
            parser=parse_robinhood_csv,
            currency=cfg.default_currency,
            client=client,
            store=store,
        )
        t = threading.Thread(target=watcher.run_forever, daemon=True, name="robinhood")
        t.start()
        threads.append(t)
    else:
        log.info("No Robinhood accounts in ACCOUNT_MAP; Robinhood watcher disabled")

    # --- Block until signal ---
    stop = threading.Event()

    def _shutdown(signum, _frame):
        log.info("received signal %s, shutting down", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        while not stop.is_set():
            time.sleep(1)
    finally:
        client.close()
        log.info("bye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
