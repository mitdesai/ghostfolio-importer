"""Print all Ghostfolio accounts so you can fill ACCOUNT_MAP.

Run with:
  docker compose exec importer python -m app.list_accounts

The printed suggestion uses `:manual` for every account — edit to
`:fidelity` or `:robinhood` based on which brokerage each is at.
"""
from __future__ import annotations

import os
import sys

from .ghostfolio import GhostfolioClient


def main() -> int:
    url = os.environ.get("GHOSTFOLIO_URL")
    token = os.environ.get("GHOSTFOLIO_TOKEN")
    if not url or not token:
        print("Set GHOSTFOLIO_URL and GHOSTFOLIO_TOKEN", file=sys.stderr)
        return 2

    client = GhostfolioClient(url, token)
    accounts = client.list_accounts()
    if not accounts:
        print("No accounts found. Create accounts in Ghostfolio UI first.")
        return 1

    print(f"{'name':<30}  {'currency':<10}  id")
    print("-" * 80)
    for a in accounts:
        print(f"{a.get('name', ''):<30}  {a.get('currency', ''):<10}  {a.get('id', '')}")

    print()
    print("Suggested ACCOUNT_MAP (edit :manual to :fidelity or :robinhood):")
    pairs = [
        f"{a.get('name', '').lower().replace(' ', '-')}={a.get('id', '')}:manual"
        for a in accounts
    ]
    print("ACCOUNT_MAP=" + ",".join(pairs))
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
