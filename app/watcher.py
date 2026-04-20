"""Generic CSV drop-folder watcher, parameterized by broker.

Each broker (fidelity, robinhood) has its own watch_dir and parser
callable. The watcher handles file discovery, subfolder routing,
success/failure moves, and dedup — all shared logic.
"""
from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from .activity import Activity
from .dedup import DedupStore

log = logging.getLogger(__name__)


ParserFn = Callable[[Path, str, str], Iterator[Activity]]


class CsvDropWatcher:
    """Watches `watch_dir` for CSVs dropped into per-account subfolders.

    Layout:
        watch_dir/
        ├── <account-key-1>/
        │   ├── *.csv            <- user drops here
        │   ├── processed/
        │   └── failed/
        └── <account-key-2>/...
    """

    def __init__(
        self,
        name: str,
        watch_dir: Path,
        account_uuids: dict[str, str],
        parser: ParserFn,
        currency: str,
        client,
        store: DedupStore,
        poll_seconds: int = 60,
    ):
        self.name = name
        self.watch_dir = watch_dir
        self.account_uuids = account_uuids
        self.parser = parser
        self.currency = currency
        self.client = client
        self.store = store
        self.poll_seconds = poll_seconds

        watch_dir.mkdir(parents=True, exist_ok=True)
        for key in self.account_uuids:
            self._ensure_account_dirs(key)

    def _ensure_account_dirs(self, key: str) -> tuple[Path, Path, Path]:
        base = self.watch_dir / key
        processed = base / "processed"
        failed = base / "failed"
        for d in (base, processed, failed):
            d.mkdir(parents=True, exist_ok=True)
        return base, processed, failed

    def run_forever(self) -> None:
        log.info("%s watcher started on %s (accounts: %s)",
                 self.name, self.watch_dir, sorted(self.account_uuids))
        while True:
            try:
                self.scan_once()
            except Exception:
                log.exception("unexpected error in %s watcher", self.name)
            time.sleep(self.poll_seconds)

    def scan_once(self) -> None:
        for stray in self.watch_dir.glob("*.csv"):
            log.warning(
                "%s: stray file %s ignored — drop into one of: %s",
                self.name, stray.name, sorted(self.account_uuids),
            )

        for key, account_id in self.account_uuids.items():
            base, _, _ = self._ensure_account_dirs(key)
            for path in sorted(base.glob("*.csv")):
                if time.time() - path.stat().st_mtime < 3:
                    continue
                self._process(path, key, account_id)

    def _process(self, path: Path, account_key: str, account_id: str) -> None:
        _, processed_dir, failed_dir = self._ensure_account_dirs(account_key)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            activities = list(self.parser(path, account_id, self.currency))
            log.info("%s/%s/%s: parsed %d activities",
                     self.name, account_key, path.name, len(activities))
            imported = 0
            for a in activities:
                if self._import_one(a):
                    imported += 1
            log.info("%s/%s/%s: imported %d new activities",
                     self.name, account_key, path.name, imported)
            shutil.move(str(path), str(processed_dir / f"{stamp}-{path.name}"))
        except Exception:
            log.exception("failed to process %s/%s/%s",
                          self.name, account_key, path.name)
            shutil.move(str(path), str(failed_dir / f"{stamp}-{path.name}"))

    def _import_one(self, a: Activity) -> bool:
        fp = a.fingerprint()
        if self.store.has(fp):
            log.debug("skip duplicate %s %s %s %s",
                      a.source, a.action, a.symbol, a.date)
            return False
        try:
            result = self.client.create_order(a)
        except Exception:
            log.exception("Ghostfolio rejected %s: %s %s %s",
                          a.source, a.action, a.symbol, a.date)
            return False
        self.store.record(
            fp, a.source, a.symbol, a.account_id,
            ghostfolio_id=result.get("id"),
        )
        log.info("imported %s %s %s qty=%s @ %s",
                 a.source, a.action, a.symbol, a.quantity, a.unit_price)
        return True
