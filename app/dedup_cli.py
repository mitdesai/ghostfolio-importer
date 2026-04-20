"""CLI for inspecting and managing the dedup store.

Usage:
  # List recent imports
  docker compose exec importer python -m app.dedup_cli list

  # List only failures (not in dedup = not imported)
  docker compose exec importer python -m app.dedup_cli list --source robinhood

  # Delete a specific fingerprint so it gets retried
  docker compose exec importer python -m app.dedup_cli delete ec9bae08482280da

  # Delete all records for a source (triggers full re-import on next drop)
  docker compose exec importer python -m app.dedup_cli delete --source robinhood

  # Show count
  docker compose exec importer python -m app.dedup_cli count
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from .config import load_config


def get_conn(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_list(db_path: Path, source: str | None, limit: int):
    conn = get_conn(db_path)
    if source:
        rows = conn.execute(
            "SELECT * FROM imported WHERE source=? ORDER BY imported_at DESC LIMIT ?",
            (source, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM imported ORDER BY imported_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()

    if not rows:
        print("No records found.")
        return
    print(f"{'fingerprint':<18} {'source':<12} {'symbol':<8} {'imported_at'}")
    print("-" * 70)
    for r in rows:
        print(f"{r['fingerprint']:<18} {r['source']:<12} {r['symbol']:<8} {r['imported_at']}")


def cmd_delete(db_path: Path, fingerprint: str | None, source: str | None):
    if not fingerprint and not source:
        print("Provide either a fingerprint or --source", file=sys.stderr)
        return 2

    conn = get_conn(db_path)
    if fingerprint:
        conn.execute("DELETE FROM imported WHERE fingerprint=?", (fingerprint,))
    else:
        conn.execute("DELETE FROM imported WHERE source=?", (source,))
    n = conn.total_changes
    conn.commit()
    conn.close()
    print(f"Deleted {n} record(s). They will be retried on next CSV drop.")


def cmd_count(db_path: Path):
    conn = get_conn(db_path)
    row = conn.execute(
        "SELECT source, COUNT(*) as n FROM imported GROUP BY source ORDER BY source"
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) as n FROM imported").fetchone()["n"]
    conn.close()
    for r in row:
        print(f"  {r['source']:<12} {r['n']}")
    print(f"  {'TOTAL':<12} {total}")


def main(argv=None) -> int:
    cfg = load_config()

    ap = argparse.ArgumentParser(description="Manage the ghostfolio-importer dedup store")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List recent imported records")
    p_list.add_argument("--source", help="Filter by source (fidelity/robinhood/shortcut/manual)")
    p_list.add_argument("--limit", type=int, default=30)

    p_del = sub.add_parser("delete", help="Delete record(s) so they get retried")
    p_del.add_argument("fingerprint", nargs="?", help="Specific fingerprint to delete")
    p_del.add_argument("--source", help="Delete all records for this source")

    sub.add_parser("count", help="Show import counts by source")

    args = ap.parse_args(argv)

    if args.cmd == "list":
        cmd_list(cfg.db_path, args.source, args.limit)
    elif args.cmd == "delete":
        cmd_delete(cfg.db_path, args.fingerprint, getattr(args, "source", None))
    elif args.cmd == "count":
        cmd_count(cfg.db_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
