"""Tracks which activities have already been imported to Ghostfolio.

We keep this state locally even though Ghostfolio has its own DB, because:
  1. Different sources may report the same trade slightly differently
     (e.g. rounding). Local dedup gives us control over what counts as "same".
  2. Avoids making an API call per activity just to check existence.
  3. Makes re-runs of the importer completely safe.
"""
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


_SCHEMA = """
CREATE TABLE IF NOT EXISTS imported (
    fingerprint TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    account_id TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    ghostfolio_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_imported_source ON imported(source);
CREATE INDEX IF NOT EXISTS idx_imported_symbol ON imported(symbol);
"""


class DedupStore:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def has(self, fingerprint: str) -> bool:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM imported WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            return row is not None

    def record(
        self,
        fingerprint: str,
        source: str,
        symbol: str,
        account_id: str,
        ghostfolio_id: str | None = None,
    ) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO imported "
                "(fingerprint, source, symbol, account_id, imported_at, ghostfolio_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    fingerprint,
                    source,
                    symbol,
                    account_id,
                    datetime.now(timezone.utc).isoformat(),
                    ghostfolio_id,
                ),
            )

    def count(self) -> int:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT COUNT(*) AS n FROM imported").fetchone()
            return row["n"]
