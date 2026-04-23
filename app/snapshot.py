"""Portfolio snapshot: fetch holdings from Ghostfolio and build a report."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from .ghostfolio import GhostfolioClient

log = logging.getLogger(__name__)

ACCOUNT_TYPE_ROTH = "Roth IRA"
ACCOUNT_TYPE_TRADITIONAL = "Traditional IRA"
ACCOUNT_TYPE_BROKERAGE = "Regular Brokerage"


def classify_account(name: str) -> str:
    lower = name.lower()
    if "roth" in lower:
        return ACCOUNT_TYPE_ROTH
    if "ira" in lower or "brokerage link" in lower:
        return ACCOUNT_TYPE_TRADITIONAL
    return ACCOUNT_TYPE_BROKERAGE


@dataclass
class AccountHolding:
    """A single stock held in one specific account."""
    account_id: str
    account_name: str
    account_type: str
    symbol: str
    name: str
    quantity: float
    investment: float  # cost basis
    market_price: float
    value: float
    gross_performance: float
    gross_performance_pct: float
    net_performance: float
    net_performance_pct: float
    currency: str


@dataclass
class HoldingSummary:
    """Aggregated view of one stock across all accounts."""
    symbol: str
    name: str
    currency: str
    total_quantity: float
    total_investment: float
    market_price: float
    total_value: float
    gross_performance: float
    gross_performance_pct: float
    net_performance: float
    net_performance_pct: float
    allocation_pct: float
    account_holdings: list[AccountHolding] = field(default_factory=list)

    @property
    def avg_price(self) -> float:
        if self.total_quantity == 0:
            return 0.0
        return self.total_investment / self.total_quantity


@dataclass
class AccountTypeSummary:
    """All holdings within one account type (Roth IRA, Traditional, Brokerage)."""
    account_type: str
    total_value: float
    holdings: list[AccountHolding] = field(default_factory=list)

    @property
    def tax_note(self) -> str:
        if self.account_type == ACCOUNT_TYPE_ROTH:
            return "Tax-free: gains and qualified withdrawals are not taxed."
        if self.account_type == ACCOUNT_TYPE_TRADITIONAL:
            return "Tax-deferred: withdrawals are taxed as ordinary income."
        return "Taxable: capital gains and dividends are taxed annually."


@dataclass
class PortfolioSnapshot:
    """Complete portfolio snapshot ready for rendering."""
    report_date: date
    total_value: float
    total_investment: float
    total_gain_loss: float
    total_gain_loss_pct: float
    holdings: list[HoldingSummary]
    account_type_sections: list[AccountTypeSummary]
    currency: str


def _extract_holdings(details: dict) -> dict[str, dict]:
    """Extract the holdings map from a portfolio/details response."""
    raw = details.get("holdings", {})
    if isinstance(raw, list):
        return {h.get("symbol", h.get("id", "")): h for h in raw}
    return raw


def _holding_symbol(key: str, h: dict) -> str:
    profile = h.get("assetProfile", {})
    return profile.get("symbol") or h.get("symbol") or key


def _holding_name(key: str, h: dict) -> str:
    profile = h.get("assetProfile", {})
    return profile.get("name") or h.get("name") or key


def _holding_currency(h: dict) -> str:
    profile = h.get("assetProfile", {})
    return profile.get("currency") or h.get("currency") or "USD"


def fetch_snapshot(client: GhostfolioClient, currency: str = "USD") -> PortfolioSnapshot:
    """Fetch all data from Ghostfolio and assemble a PortfolioSnapshot."""
    accounts_list = client.get_accounts()
    log.info("fetched %d accounts from Ghostfolio", len(accounts_list))

    accounts_by_id: dict[str, dict] = {}
    for acc in accounts_list:
        aid = acc.get("id", "")
        if aid:
            accounts_by_id[aid] = acc

    overall = client.get_portfolio_details()
    overall_holdings = _extract_holdings(overall)

    summary_info = overall.get("summary", {}) or {}
    total_value = summary_info.get("currentValue") or summary_info.get("netWorth") or 0.0
    total_investment = summary_info.get("totalInvestment", 0.0)

    per_account_holdings: dict[str, dict[str, dict]] = {}
    for aid, acc in accounts_by_id.items():
        try:
            acct_details = client.get_portfolio_details(account_id=aid)
            per_account_holdings[aid] = _extract_holdings(acct_details)
        except Exception:
            log.warning("failed to fetch holdings for account %s (%s)",
                        acc.get("name", aid), aid, exc_info=True)
            per_account_holdings[aid] = {}

    # Build per-symbol summaries
    holdings_summaries: dict[str, HoldingSummary] = {}
    for key, h in overall_holdings.items():
        symbol = _holding_symbol(key, h)
        qty = h.get("quantity", 0)
        if qty == 0:
            continue
        inv = h.get("investment", 0)
        mp = h.get("marketPrice", 0)
        val = h.get("valueInBaseCurrency", qty * mp)
        alloc = h.get("allocationInPercentage", 0)
        if alloc == 0 and total_value > 0:
            alloc = val / total_value

        holdings_summaries[symbol] = HoldingSummary(
            symbol=symbol,
            name=_holding_name(key, h),
            currency=_holding_currency(h),
            total_quantity=qty,
            total_investment=inv,
            market_price=mp,
            total_value=val,
            gross_performance=h.get("grossPerformance", 0),
            gross_performance_pct=h.get("grossPerformancePercent", 0),
            net_performance=h.get("netPerformance", 0),
            net_performance_pct=h.get("netPerformancePercent", 0),
            allocation_pct=alloc,
        )

    # Build per-account holdings and link them to summaries
    all_account_holdings: list[AccountHolding] = []
    for aid, acct_holdings in per_account_holdings.items():
        acc = accounts_by_id.get(aid, {})
        acc_name = acc.get("name", aid)
        acc_type = classify_account(acc_name)
        for key, h in acct_holdings.items():
            symbol = _holding_symbol(key, h)
            qty = h.get("quantity", 0)
            if qty == 0:
                continue
            inv = h.get("investment", 0)
            mp = h.get("marketPrice", 0)
            val = h.get("valueInBaseCurrency", qty * mp)
            ah = AccountHolding(
                account_id=aid,
                account_name=acc_name,
                account_type=acc_type,
                symbol=symbol,
                name=_holding_name(key, h),
                quantity=qty,
                investment=inv,
                market_price=mp,
                value=val,
                gross_performance=h.get("grossPerformance", 0),
                gross_performance_pct=h.get("grossPerformancePercent", 0),
                net_performance=h.get("netPerformance", 0),
                net_performance_pct=h.get("netPerformancePercent", 0),
                currency=_holding_currency(h),
            )
            all_account_holdings.append(ah)
            if symbol in holdings_summaries:
                holdings_summaries[symbol].account_holdings.append(ah)

    # Sort summaries by value descending
    sorted_holdings = sorted(
        holdings_summaries.values(), key=lambda s: s.total_value, reverse=True
    )

    # Build account-type sections
    type_buckets: dict[str, list[AccountHolding]] = {}
    for ah in all_account_holdings:
        type_buckets.setdefault(ah.account_type, []).append(ah)

    account_type_sections = []
    for at in [ACCOUNT_TYPE_ROTH, ACCOUNT_TYPE_TRADITIONAL, ACCOUNT_TYPE_BROKERAGE]:
        bucket = type_buckets.get(at, [])
        if not bucket:
            continue
        bucket.sort(key=lambda ah: ah.value, reverse=True)
        section_value = sum(ah.value for ah in bucket)
        account_type_sections.append(AccountTypeSummary(
            account_type=at,
            total_value=section_value,
            holdings=bucket,
        ))

    # Compute totals from overall summary or from holdings
    if not total_investment:
        total_investment = sum(s.total_investment for s in sorted_holdings)
    if not total_value:
        total_value = sum(s.total_value for s in sorted_holdings)
    total_gain_loss = total_value - total_investment
    total_gain_loss_pct = (total_gain_loss / total_investment * 100) if total_investment else 0

    return PortfolioSnapshot(
        report_date=date.today(),
        total_value=total_value,
        total_investment=total_investment,
        total_gain_loss=total_gain_loss,
        total_gain_loss_pct=total_gain_loss_pct,
        holdings=sorted_holdings,
        account_type_sections=account_type_sections,
        currency=currency,
    )
