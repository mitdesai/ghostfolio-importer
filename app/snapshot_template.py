"""HTML template for portfolio snapshot report."""
from __future__ import annotations

from .snapshot import PortfolioSnapshot, HoldingSummary, AccountHolding, AccountTypeSummary


def _fmt_money(val: float, currency: str = "USD") -> str:
    sign = "" if val >= 0 else "-"
    return f"{sign}${abs(val):,.2f}"


def _fmt_pct(val: float) -> str:
    return f"{val:+.2f}%"


def _gain_class(val: float) -> str:
    if val > 0:
        return "gain-positive"
    if val < 0:
        return "gain-negative"
    return ""


def _render_account_holdings_rows(holdings: list[AccountHolding]) -> str:
    rows = []
    for ah in holdings:
        gc = _gain_class(ah.net_performance)
        rows.append(f"""
        <tr class="account-detail-row">
          <td class="indent">{ah.account_name}</td>
          <td class="account-type-badge {ah.account_type.lower().replace(' ', '-')}">{ah.account_type}</td>
          <td class="num">{ah.quantity:,.4f}</td>
          <td class="num">{_fmt_money(ah.investment / ah.quantity if ah.quantity else 0)}</td>
          <td class="num">{_fmt_money(ah.value)}</td>
          <td class="num {gc}">{_fmt_money(ah.net_performance)}</td>
          <td class="num {gc}">{_fmt_pct(ah.net_performance_pct * 100)}</td>
        </tr>""")
    return "\n".join(rows)


def _render_holdings_table(snapshot: PortfolioSnapshot) -> str:
    rows = []
    for h in snapshot.holdings:
        gc = _gain_class(h.net_performance)
        rows.append(f"""
        <tr class="holding-row">
          <td class="symbol"><strong>{h.symbol}</strong></td>
          <td class="name">{h.name}</td>
          <td class="num">{h.total_quantity:,.4f}</td>
          <td class="num">{_fmt_money(h.avg_price)}</td>
          <td class="num">{_fmt_money(h.market_price)}</td>
          <td class="num">{_fmt_money(h.total_value)}</td>
          <td class="num {gc}">{_fmt_money(h.net_performance)}</td>
          <td class="num {gc}">{_fmt_pct(h.net_performance_pct * 100)}</td>
          <td class="num">{h.allocation_pct * 100:.1f}%</td>
        </tr>""")
        # Sub-rows for per-account breakdown
        for ah in h.account_holdings:
            agc = _gain_class(ah.net_performance)
            avg = ah.investment / ah.quantity if ah.quantity else 0
            rows.append(f"""
        <tr class="sub-row">
          <td></td>
          <td class="indent sub-account">
            <span class="badge {ah.account_type.lower().replace(' ', '-')}">{ah.account_type}</span>
            {ah.account_name}
          </td>
          <td class="num sub">{ah.quantity:,.4f}</td>
          <td class="num sub">{_fmt_money(avg)}</td>
          <td class="num sub"></td>
          <td class="num sub">{_fmt_money(ah.value)}</td>
          <td class="num sub {agc}">{_fmt_money(ah.net_performance)}</td>
          <td class="num sub {agc}">{_fmt_pct(ah.net_performance_pct * 100)}</td>
          <td class="num sub"></td>
        </tr>""")
    return "\n".join(rows)


def _render_account_type_section(section: AccountTypeSummary, currency: str) -> str:
    rows = []
    for ah in section.holdings:
        gc = _gain_class(ah.net_performance)
        avg = ah.investment / ah.quantity if ah.quantity else 0
        rows.append(f"""
          <tr>
            <td class="symbol"><strong>{ah.symbol}</strong></td>
            <td>{ah.name}</td>
            <td>{ah.account_name}</td>
            <td class="num">{ah.quantity:,.4f}</td>
            <td class="num">{_fmt_money(avg)}</td>
            <td class="num">{_fmt_money(ah.market_price)}</td>
            <td class="num">{_fmt_money(ah.value)}</td>
            <td class="num {gc}">{_fmt_money(ah.net_performance)}</td>
            <td class="num {gc}">{_fmt_pct(ah.net_performance_pct * 100)}</td>
          </tr>""")

    type_class = section.account_type.lower().replace(' ', '-')
    return f"""
    <div class="account-type-section">
      <div class="section-header {type_class}">
        <h2>{section.account_type}</h2>
        <div class="section-meta">
          <span class="section-value">{_fmt_money(section.total_value, currency)}</span>
          <p class="tax-note">{section.tax_note}</p>
        </div>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Name</th>
            <th>Account</th>
            <th class="num">Shares</th>
            <th class="num">Avg Price</th>
            <th class="num">Mkt Price</th>
            <th class="num">Value</th>
            <th class="num">Gain/Loss</th>
            <th class="num">Gain %</th>
          </tr>
        </thead>
        <tbody>
          {"".join(rows)}
        </tbody>
      </table>
    </div>"""


def render_html(snapshot: PortfolioSnapshot) -> str:
    gc = _gain_class(snapshot.total_gain_loss)
    holdings_table = _render_holdings_table(snapshot)
    account_sections = "\n".join(
        _render_account_type_section(s, snapshot.currency)
        for s in snapshot.account_type_sections
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Portfolio Snapshot - {snapshot.report_date.strftime("%B %d, %Y")}</title>
<style>
  :root {{
    --bg: #f8f9fa;
    --card-bg: #ffffff;
    --border: #dee2e6;
    --text: #212529;
    --text-muted: #6c757d;
    --green: #198754;
    --red: #dc3545;
    --roth-ira: #0d6efd;
    --traditional-ira: #6f42c1;
    --regular-brokerage: #fd7e14;
    --header-bg: #212529;
    --header-text: #ffffff;
  }}

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
    padding: 0;
  }}

  .container {{
    max-width: 1400px;
    margin: 0 auto;
    padding: 24px;
  }}

  /* --- Banner --- */
  .banner {{
    background: var(--header-bg);
    color: var(--header-text);
    padding: 32px;
    border-radius: 12px;
    margin-bottom: 32px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
  }}
  .banner h1 {{
    font-size: 1.75rem;
    font-weight: 600;
  }}
  .banner .date {{
    font-size: 0.9rem;
    opacity: 0.8;
  }}
  .banner-stats {{
    display: flex;
    gap: 40px;
    flex-wrap: wrap;
  }}
  .banner-stat {{
    text-align: right;
  }}
  .banner-stat .label {{
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    opacity: 0.7;
  }}
  .banner-stat .value {{
    font-size: 1.5rem;
    font-weight: 700;
  }}
  .banner-stat .value.gain-positive {{ color: #4ade80; }}
  .banner-stat .value.gain-negative {{ color: #f87171; }}

  /* --- PDF button --- */
  .actions {{
    text-align: right;
    margin-bottom: 24px;
  }}
  .btn-pdf {{
    display: inline-block;
    padding: 10px 24px;
    background: var(--header-bg);
    color: #fff;
    text-decoration: none;
    border-radius: 8px;
    font-weight: 600;
    font-size: 0.9rem;
    border: none;
    cursor: pointer;
  }}
  .btn-pdf:hover {{ opacity: 0.85; }}

  /* --- Section headings --- */
  .section-title {{
    font-size: 1.25rem;
    font-weight: 600;
    margin: 32px 0 16px 0;
    padding-bottom: 8px;
    border-bottom: 2px solid var(--border);
  }}

  /* --- Tables --- */
  .data-table {{
    width: 100%;
    border-collapse: collapse;
    background: var(--card-bg);
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    margin-bottom: 24px;
  }}
  .data-table thead th {{
    background: #f1f3f5;
    padding: 10px 12px;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    font-weight: 600;
    text-align: left;
    border-bottom: 2px solid var(--border);
    white-space: nowrap;
  }}
  .data-table thead th.num {{ text-align: right; }}
  .data-table td {{
    padding: 10px 12px;
    border-bottom: 1px solid #f1f3f5;
    font-size: 0.875rem;
    vertical-align: middle;
  }}
  .data-table td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .data-table td.symbol {{ font-weight: 600; }}
  .data-table td.name {{ max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

  .holding-row {{ background: var(--card-bg); }}
  .holding-row:hover {{ background: #f8f9fa; }}

  .sub-row td {{
    padding-top: 4px;
    padding-bottom: 4px;
    font-size: 0.8rem;
    color: var(--text-muted);
    border-bottom: 1px solid #f8f9fa;
  }}
  .sub-row td.sub {{ font-size: 0.8rem; }}
  .sub-account {{ padding-left: 12px; }}

  .gain-positive {{ color: var(--green); }}
  .gain-negative {{ color: var(--red); }}

  /* --- Account type badges --- */
  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    margin-right: 6px;
    vertical-align: middle;
  }}
  .badge.roth-ira {{ background: #dbeafe; color: var(--roth-ira); }}
  .badge.traditional-ira {{ background: #ede9fe; color: var(--traditional-ira); }}
  .badge.regular-brokerage {{ background: #ffedd5; color: var(--regular-brokerage); }}

  /* --- Account type sections --- */
  .account-type-section {{
    margin-bottom: 32px;
  }}
  .section-header {{
    padding: 16px 20px;
    border-radius: 8px 8px 0 0;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }}
  .section-header h2 {{
    font-size: 1.15rem;
    font-weight: 600;
    color: #fff;
  }}
  .section-header.roth-ira {{ background: var(--roth-ira); }}
  .section-header.traditional-ira {{ background: var(--traditional-ira); }}
  .section-header.regular-brokerage {{ background: var(--regular-brokerage); }}
  .section-meta {{
    text-align: right;
  }}
  .section-value {{
    font-size: 1.2rem;
    font-weight: 700;
    color: #fff;
  }}
  .tax-note {{
    font-size: 0.75rem;
    color: rgba(255,255,255,0.85);
    margin-top: 2px;
  }}

  .account-type-section .data-table {{
    border-radius: 0 0 8px 8px;
    margin-top: 0;
  }}

  /* --- Footer --- */
  .footer {{
    text-align: center;
    padding: 24px;
    font-size: 0.8rem;
    color: var(--text-muted);
  }}

  /* ===== Print / PDF styles ===== */
  @media print {{
    body {{ background: #fff; padding: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .container {{ padding: 0; max-width: none; }}
    .actions {{ display: none; }}
    .banner {{ border-radius: 0; margin-bottom: 20px; padding: 20px; }}

    .data-table {{ box-shadow: none; font-size: 0.8rem; }}
    .data-table td, .data-table thead th {{ padding: 6px 8px; }}

    .holding-row {{ page-break-inside: avoid; }}
    .sub-row {{ page-break-inside: avoid; }}
    .account-type-section {{ page-break-inside: avoid; }}

    .section-header, .section-header.roth-ira, .section-header.traditional-ira, .section-header.regular-brokerage {{
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }}
    .badge {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .gain-positive {{ color: var(--green) !important; -webkit-print-color-adjust: exact; }}
    .gain-negative {{ color: var(--red) !important; -webkit-print-color-adjust: exact; }}
  }}

  @page {{
    size: landscape;
    margin: 15mm 10mm;
    @bottom-center {{
      content: "Portfolio Snapshot - {snapshot.report_date.strftime("%B %d, %Y")} | Page " counter(page) " of " counter(pages);
      font-size: 8pt;
      color: #6c757d;
    }}
  }}
</style>
</head>
<body>
<div class="container">

  <div class="banner">
    <div>
      <h1>Portfolio Snapshot</h1>
      <div class="date">{snapshot.report_date.strftime("%B %d, %Y")}</div>
    </div>
    <div class="banner-stats">
      <div class="banner-stat">
        <div class="label">Total Value</div>
        <div class="value">{_fmt_money(snapshot.total_value, snapshot.currency)}</div>
      </div>
      <div class="banner-stat">
        <div class="label">Cost Basis</div>
        <div class="value">{_fmt_money(snapshot.total_investment, snapshot.currency)}</div>
      </div>
      <div class="banner-stat">
        <div class="label">Gain / Loss</div>
        <div class="value {gc}">{_fmt_money(snapshot.total_gain_loss, snapshot.currency)} ({_fmt_pct(snapshot.total_gain_loss_pct)})</div>
      </div>
    </div>
  </div>

  <div class="actions">
    <a href="/snapshot/pdf" class="btn-pdf">Download PDF</a>
  </div>

  <h2 class="section-title">Holdings Overview</h2>
  <table class="data-table">
    <thead>
      <tr>
        <th>Symbol</th>
        <th>Name</th>
        <th class="num">Shares</th>
        <th class="num">Avg Price</th>
        <th class="num">Mkt Price</th>
        <th class="num">Value</th>
        <th class="num">Gain/Loss</th>
        <th class="num">Gain %</th>
        <th class="num">Alloc %</th>
      </tr>
    </thead>
    <tbody>
      {holdings_table}
    </tbody>
  </table>

  <h2 class="section-title">By Account Type</h2>
  {account_sections}

  <div class="footer">
    Generated by ghostfolio-importer &middot; Data from Ghostfolio
  </div>

</div>
</body>
</html>"""
