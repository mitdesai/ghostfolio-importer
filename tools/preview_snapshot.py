#!/usr/bin/env python3
"""Preview the portfolio snapshot dashboard using mock data.

Renders the snapshot HTML template with realistic mock holdings and
opens the result in the default browser.  Useful for iterating on the
template design without a running Ghostfolio instance.

Run from the repository root so the `app` package is importable:

    # Default: full dashboard with account details, opens in browser
    python tools/preview_snapshot.py

    # Summary mode (no per-account breakdowns — matches "PDF Summary")
    python tools/preview_snapshot.py --no-details

    # Generate both versions side by side
    python tools/preview_snapshot.py --both

    # Write to a specific file instead of a temp file
    python tools/preview_snapshot.py --out /tmp/snapshot.html
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import webbrowser
from datetime import date
from pathlib import Path

# Ensure the repo root is on sys.path so `app` is importable regardless
# of the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.snapshot import (
    AccountHolding,
    AccountTypeSummary,
    HoldingSummary,
    PortfolioSnapshot,
    ACCOUNT_TYPE_BROKERAGE,
    ACCOUNT_TYPE_ROTH,
    ACCOUNT_TYPE_TRADITIONAL,
)
from app.snapshot_template import render_html


# ── Mock account holdings ────────────────────────────────────────

def _ah(
    symbol: str, name: str, acct_id: str, acct_name: str, acct_type: str,
    qty: float, investment: float, market_price: float,
) -> AccountHolding:
    value = qty * market_price
    gain = value - investment
    gain_pct = gain / investment if investment else 0
    return AccountHolding(
        account_id=acct_id,
        account_name=acct_name,
        account_type=acct_type,
        symbol=symbol,
        name=name,
        quantity=qty,
        investment=investment,
        market_price=market_price,
        value=value,
        gross_performance=gain,
        gross_performance_pct=gain_pct,
        net_performance=gain,
        net_performance_pct=gain_pct,
        currency="USD",
    )


def _build_mock_data() -> PortfolioSnapshot:
    # ── Per-account holdings (mirrors the user's real portfolio shape) ──
    all_ah: list[AccountHolding] = [
        # AMD
        _ah("AMD", "Advanced Micro Devices, Inc.", "a1", "Brokerage - MH (Robinhood)",
            ACCOUNT_TYPE_BROKERAGE, 1.0, 107.71, 274.96),
        _ah("AMD", "Advanced Micro Devices, Inc.", "a2", "Brokerage - MH (Fidelity)",
            ACCOUNT_TYPE_BROKERAGE, 57.0, 5202.39, 274.96),
        _ah("AMD", "Advanced Micro Devices, Inc.", "a3", "Brokerage - Joint Investment",
            ACCOUNT_TYPE_BROKERAGE, 69.0, 7374.72, 274.96),
        _ah("AMD", "Advanced Micro Devices, Inc.", "a4", "Roth VA - MH",
            ACCOUNT_TYPE_ROTH, 20.0, 2291.40, 274.96),
        _ah("AMD", "Advanced Micro Devices, Inc.", "a5", "Traditional IRA - MH",
            ACCOUNT_TYPE_TRADITIONAL, 280.0, 32228.40, 274.96),
        # TSLA
        _ah("TSLA", "Tesla, Inc.", "a2", "Brokerage - MH (Fidelity)",
            ACCOUNT_TYPE_BROKERAGE, 81.0, 3700.08, 392.50),
        _ah("TSLA", "Tesla, Inc.", "a6", "Brokerage Link",
            ACCOUNT_TYPE_TRADITIONAL, 56.0, 19600.00, 392.50),
        _ah("TSLA", "Tesla, Inc.", "a3", "Brokerage - Joint Investment",
            ACCOUNT_TYPE_BROKERAGE, 5.0, 1665.05, 392.50),
        _ah("TSLA", "Tesla, Inc.", "a5", "Traditional IRA - MH",
            ACCOUNT_TYPE_TRADITIONAL, 10.0, 3826.00, 392.50),
        _ah("TSLA", "Tesla, Inc.", "a8", "Brokerage - MM",
            ACCOUNT_TYPE_BROKERAGE, 54.967, 13506.13, 392.50),
        # AMZN
        _ah("AMZN", "Amazon.com, Inc.", "a2", "Brokerage - MH (Fidelity)",
            ACCOUNT_TYPE_BROKERAGE, 8.0, 1431.44, 248.28),
        _ah("AMZN", "Amazon.com, Inc.", "a5", "Traditional IRA - MH",
            ACCOUNT_TYPE_TRADITIONAL, 171.0, 30213.00, 248.28),
        _ah("AMZN", "Amazon.com, Inc.", "a3", "Brokerage - Joint Investment",
            ACCOUNT_TYPE_BROKERAGE, 54.0, 9666.00, 248.28),
        # META
        _ah("META", "Meta Platforms, Inc.", "a1", "Brokerage - MH (Robinhood)",
            ACCOUNT_TYPE_BROKERAGE, 0.3426, 193.51, 670.01),
        _ah("META", "Meta Platforms, Inc.", "a6", "Brokerage Link",
            ACCOUNT_TYPE_TRADITIONAL, 56.0, 31584.00, 670.01),
        _ah("META", "Meta Platforms, Inc.", "a5", "Traditional IRA - MH",
            ACCOUNT_TYPE_TRADITIONAL, 23.0, 13489.90, 670.01),
        # HIMS
        _ah("HIMS", "Hims & Hers Health, Inc.", "a2", "Brokerage - MH (Fidelity)",
            ACCOUNT_TYPE_BROKERAGE, 400.0, 6400.00, 31.01),
        _ah("HIMS", "Hims & Hers Health, Inc.", "a3", "Brokerage - Joint Investment",
            ACCOUNT_TYPE_BROKERAGE, 500.0, 9000.00, 31.01),
        _ah("HIMS", "Hims & Hers Health, Inc.", "a5", "Traditional IRA - MH",
            ACCOUNT_TYPE_TRADITIONAL, 745.0, 15645.00, 31.01),
        # GOOG
        _ah("GOOG", "Alphabet Inc.", "a2", "Brokerage - MH (Fidelity)",
            ACCOUNT_TYPE_BROKERAGE, 40.0, 6800.00, 161.53),
        _ah("GOOG", "Alphabet Inc.", "a4", "Roth VA - MH",
            ACCOUNT_TYPE_ROTH, 25.0, 4250.00, 161.53),
        _ah("GOOG", "Alphabet Inc.", "a5", "Traditional IRA - MH",
            ACCOUNT_TYPE_TRADITIONAL, 60.0, 9360.00, 161.53),
        # NVDA
        _ah("NVDA", "NVIDIA Corporation", "a2", "Brokerage - MH (Fidelity)",
            ACCOUNT_TYPE_BROKERAGE, 15.0, 1350.00, 113.76),
        _ah("NVDA", "NVIDIA Corporation", "a4", "Roth VA - MH",
            ACCOUNT_TYPE_ROTH, 30.0, 3300.00, 113.76),
        # MSFT
        _ah("MSFT", "Microsoft Corporation", "a3", "Brokerage - Joint Investment",
            ACCOUNT_TYPE_BROKERAGE, 10.0, 3800.00, 437.03),
        _ah("MSFT", "Microsoft Corporation", "a5", "Traditional IRA - MH",
            ACCOUNT_TYPE_TRADITIONAL, 20.0, 7800.00, 437.03),
        # PLTR
        _ah("PLTR", "Palantir Technologies Inc.", "a1", "Brokerage - MH (Robinhood)",
            ACCOUNT_TYPE_BROKERAGE, 100.0, 2500.00, 117.42),
        _ah("PLTR", "Palantir Technologies Inc.", "a4", "Roth VA - MH",
            ACCOUNT_TYPE_ROTH, 50.0, 1500.00, 117.42),
    ]

    # ── Aggregate into HoldingSummary per symbol ──
    by_symbol: dict[str, list[AccountHolding]] = {}
    for ah in all_ah:
        by_symbol.setdefault(ah.symbol, []).append(ah)

    total_portfolio_value = sum(ah.value for ah in all_ah)

    holdings: list[HoldingSummary] = []
    for symbol, ahs in by_symbol.items():
        total_qty = sum(a.quantity for a in ahs)
        total_inv = sum(a.investment for a in ahs)
        total_val = sum(a.value for a in ahs)
        mp = ahs[0].market_price
        gain = total_val - total_inv
        gain_pct = gain / total_inv if total_inv else 0
        holdings.append(HoldingSummary(
            symbol=symbol,
            name=ahs[0].name,
            currency="USD",
            total_quantity=total_qty,
            total_investment=total_inv,
            market_price=mp,
            total_value=total_val,
            gross_performance=gain,
            gross_performance_pct=gain_pct,
            net_performance=gain,
            net_performance_pct=gain_pct,
            allocation_pct=total_val / total_portfolio_value if total_portfolio_value else 0,
            account_holdings=ahs,
        ))

    holdings.sort(key=lambda h: h.total_value, reverse=True)

    # ── Account type sections ──
    type_buckets: dict[str, list[AccountHolding]] = {}
    for ah in all_ah:
        type_buckets.setdefault(ah.account_type, []).append(ah)

    sections: list[AccountTypeSummary] = []
    for at in [ACCOUNT_TYPE_ROTH, ACCOUNT_TYPE_TRADITIONAL, ACCOUNT_TYPE_BROKERAGE]:
        bucket = type_buckets.get(at, [])
        if not bucket:
            continue
        bucket.sort(key=lambda a: a.value, reverse=True)
        sections.append(AccountTypeSummary(
            account_type=at,
            total_value=sum(a.value for a in bucket),
            holdings=bucket,
        ))

    total_inv = sum(h.total_investment for h in holdings)
    total_val = sum(h.total_value for h in holdings)
    total_gain = total_val - total_inv

    return PortfolioSnapshot(
        report_date=date(2026, 4, 22),
        total_value=total_val,
        total_investment=total_inv,
        total_gain_loss=total_gain,
        total_gain_loss_pct=(total_gain / total_inv * 100) if total_inv else 0,
        holdings=holdings,
        account_type_sections=sections,
        currency="USD",
    )


def _write_and_open(html: str, out_path: str | None, label: str) -> str:
    if out_path:
        path = os.path.abspath(out_path)
        with open(path, "w") as f:
            f.write(html)
    else:
        fd, path = tempfile.mkstemp(suffix=".html", prefix=f"snapshot-{label}-")
        with os.fdopen(fd, "w") as f:
            f.write(html)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview portfolio snapshot dashboard")
    parser.add_argument("--out", help="Write HTML to this path instead of a temp file")
    parser.add_argument(
        "--no-details", action="store_true",
        help="Hide per-account breakdowns (summary-only mode)",
    )
    parser.add_argument(
        "--both", action="store_true",
        help="Generate both summary and detailed versions side by side",
    )
    args = parser.parse_args()

    snapshot = _build_mock_data()

    if args.both:
        path_full = _write_and_open(render_html(snapshot, show_account_details=True), None, "detailed")
        path_summary = _write_and_open(render_html(snapshot, show_account_details=False), None, "summary")
        print(f"Detailed:  {path_full}")
        print(f"Summary:   {path_summary}")
        webbrowser.open(f"file://{path_full}")
        webbrowser.open(f"file://{path_summary}")
    else:
        show_details = not args.no_details
        html = render_html(snapshot, show_account_details=show_details)
        path = _write_and_open(html, args.out, "preview")
        print(f"Written to: {path}")
        webbrowser.open(f"file://{path}")


if __name__ == "__main__":
    main()
