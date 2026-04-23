"""HTML dashboard template for portfolio snapshot.

Generates a self-contained HTML page with inline SVG donut charts,
collapsible sections, and responsive layout.  Works in browsers
(interactive) and WeasyPrint (PDF — all sections forced open).
"""
from __future__ import annotations

import math

from .snapshot import (
    AccountTypeSummary,
    HoldingSummary,
    PortfolioSnapshot,
    ACCOUNT_TYPE_BROKERAGE,
    ACCOUNT_TYPE_ROTH,
    ACCOUNT_TYPE_TRADITIONAL,
)

# ── Palette ──────────────────────────────────────────────────────

CHART_COLORS = [
    "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
    "#ec4899", "#06b6d4", "#84cc16", "#f97316", "#6366f1",
]

ACCT_TYPE_COLORS = {
    ACCOUNT_TYPE_ROTH: "#3b82f6",
    ACCOUNT_TYPE_TRADITIONAL: "#8b5cf6",
    ACCOUNT_TYPE_BROKERAGE: "#f59e0b",
}


# ── Formatters ───────────────────────────────────────────────────

def _fmt_money(val: float) -> str:
    sign = "" if val >= 0 else "-"
    return f"{sign}${abs(val):,.2f}"


def _fmt_pct(val: float) -> str:
    return f"{val:+.2f}%"


def _gain_class(val: float) -> str:
    if val > 0:
        return "gain-pos"
    if val < 0:
        return "gain-neg"
    return ""


def _type_css_class(account_type: str) -> str:
    return account_type.lower().replace(" ", "-")


# ── SVG Donut Chart ──────────────────────────────────────────────

_DONUT_R = 70
_DONUT_SW = 22
_DONUT_C = 2 * math.pi * _DONUT_R  # circumference


def _svg_center_text(lines: list[str]) -> str:
    """SVG text elements centered in the donut hole."""
    parts: list[str] = []
    y_start = 100 - 10 * (len(lines) - 1)
    styles = [("15", "700", "#1e293b"), ("11", "400", "#94a3b8")]
    for i, line in enumerate(lines):
        fs, fw, fill = styles[min(i, 1)]
        parts.append(
            f'  <text x="100" y="{y_start + i * 20}" text-anchor="middle" '
            f'font-size="{fs}" font-weight="{fw}" fill="{fill}" '
            f'font-family="-apple-system,BlinkMacSystemFont,sans-serif">'
            f'{line}</text>'
        )
    return "\n".join(parts)


def _svg_donut(
    segments: list[tuple[str, float, str]],
    center_lines: list[str] | None = None,
) -> str:
    """Inline SVG donut chart.

    segments: [(label, pct 0-100, hex_color), ...]
    center_lines: up to 2 lines of text rendered in the donut hole.
    """
    arcs: list[str] = []
    cumulative = 0.0
    for _, pct, color in segments:
        if pct < 0.3:
            cumulative += pct
            continue
        dash = pct / 100.0 * _DONUT_C
        gap = _DONUT_C - dash
        offset = _DONUT_C * 0.25 - cumulative / 100.0 * _DONUT_C
        arcs.append(
            f'  <circle cx="100" cy="100" r="{_DONUT_R}" fill="none" '
            f'stroke="{color}" stroke-width="{_DONUT_SW}" '
            f'stroke-dasharray="{dash:.1f} {gap:.1f}" '
            f'stroke-dashoffset="{offset:.1f}"/>'
        )
        cumulative += pct

    center_svg = _svg_center_text(center_lines) if center_lines else ""

    return (
        '<svg viewBox="0 0 200 200" class="donut" '
        'xmlns="http://www.w3.org/2000/svg">\n'
        + "\n".join(arcs) + "\n"
        + center_svg + "\n"
        + "</svg>"
    )


def _render_legend(
    segments: list[tuple[str, float, str]],
    values: list[str] | None = None,
) -> str:
    """Chart legend with colored dots, labels, percentages, optional values."""
    items: list[str] = []
    for i, (label, pct, color) in enumerate(segments):
        val_html = ""
        if values and i < len(values):
            val_html = f'<span class="legend-val">{values[i]}</span>'
        items.append(
            f'<div class="legend-row">'
            f'<span class="legend-dot" style="background:{color}"></span>'
            f'<span class="legend-label">{label}</span>'
            f'<span class="legend-pct">{pct:.1f}%</span>'
            f'{val_html}'
            f'</div>'
        )
    return '<div class="legend">' + "\n".join(items) + "\n</div>"


# ── Section Renderers ────────────────────────────────────────────

def _render_kpi_cards(snap: PortfolioSnapshot) -> str:
    gc = _gain_class(snap.total_gain_loss)
    return f"""
  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-label">Total Value</div>
      <div class="kpi-value">{_fmt_money(snap.total_value)}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Cost Basis</div>
      <div class="kpi-value">{_fmt_money(snap.total_investment)}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Total Gain / Loss</div>
      <div class="kpi-value {gc}">
        {_fmt_money(snap.total_gain_loss)}
        <span class="kpi-sub {gc}">{_fmt_pct(snap.total_gain_loss_pct)}</span>
      </div>
    </div>
  </div>"""


def _render_allocation_chart(snap: PortfolioSnapshot) -> str:
    """Donut chart showing portfolio allocation by holding."""
    max_slices = 7
    segments: list[tuple[str, float, str]] = []
    values: list[str] = []

    for i, h in enumerate(snap.holdings):
        pct = h.allocation_pct * 100
        if i < max_slices:
            segments.append((h.symbol, pct, CHART_COLORS[i % len(CHART_COLORS)]))
            values.append(_fmt_money(h.total_value))
        elif i == max_slices:
            segments.append(("Other", pct, "#94a3b8"))
            values.append(_fmt_money(h.total_value))
        else:
            label, prev_pct, color = segments[-1]
            segments[-1] = (label, prev_pct + pct, color)
            other_val = sum(x.total_value for x in snap.holdings[max_slices:])
            values[-1] = _fmt_money(other_val)

    center = [str(len(snap.holdings)), "positions"]
    donut = _svg_donut(segments, center)
    legend = _render_legend(segments, values)

    return f"""
  <div class="chart-card">
    <h3 class="chart-title">Portfolio Allocation</h3>
    <div class="chart-body">
      {donut}
      {legend}
    </div>
  </div>"""


def _render_account_type_chart(snap: PortfolioSnapshot) -> str:
    """Donut chart showing value split across account types."""
    segments: list[tuple[str, float, str]] = []
    values: list[str] = []

    for s in snap.account_type_sections:
        pct = (s.total_value / snap.total_value * 100) if snap.total_value else 0
        color = ACCT_TYPE_COLORS.get(s.account_type, "#94a3b8")
        segments.append((s.account_type, pct, color))
        values.append(_fmt_money(s.total_value))

    center = [_fmt_money(snap.total_value), "total"]
    donut = _svg_donut(segments, center)
    legend = _render_legend(segments, values)

    return f"""
  <div class="chart-card">
    <h3 class="chart-title">By Account Type</h3>
    <div class="chart-body">
      {donut}
      {legend}
    </div>
  </div>"""


def _render_acct_breakdown(h: HoldingSummary) -> str:
    """Collapsible per-account breakdown inside a holding card."""
    acct_rows: list[str] = []
    for ah in sorted(h.account_holdings, key=lambda a: a.value, reverse=True):
        agc = _gain_class(ah.net_performance)
        avg = ah.investment / ah.quantity if ah.quantity else 0
        tc = _type_css_class(ah.account_type)
        acct_rows.append(
            f'<tr>'
            f'<td><span class="type-badge {tc}">{ah.account_type}</span></td>'
            f'<td class="cell-muted">{ah.account_name}</td>'
            f'<td class="num">{ah.quantity:,.2f}</td>'
            f'<td class="num">{_fmt_money(avg)}</td>'
            f'<td class="num">{_fmt_money(ah.value)}</td>'
            f'<td class="num {agc}">{_fmt_pct(ah.net_performance_pct * 100)}</td>'
            f'</tr>'
        )

    n = len(h.account_holdings)
    acct_label = f"{n} account{'s' if n != 1 else ''}"

    return f"""
    <details class="acct-details">
      <summary>{acct_label}</summary>
      <div class="acct-table-wrap">
        <table class="acct-table">
          <thead><tr>
            <th>Type</th><th>Account</th><th class="num">Shares</th>
            <th class="num">Avg Cost</th><th class="num">Value</th>
            <th class="num">Return</th>
          </tr></thead>
          <tbody>
            {"".join(acct_rows)}
          </tbody>
        </table>
      </div>
    </details>"""


def _render_holding_card(
    h: HoldingSummary, color: str, show_account_details: bool = True,
) -> str:
    """One holding card, optionally with per-account breakdown."""
    gc = _gain_class(h.net_performance)
    breakdown = _render_acct_breakdown(h) if show_account_details else ""

    return f"""
  <div class="holding-card">
    <div class="holding-header">
      <div class="holding-id">
        <span class="holding-dot" style="background:{color}"></span>
        <span class="holding-symbol">{h.symbol}</span>
        <span class="holding-name">{h.name}</span>
      </div>
      <span class="holding-alloc">{h.allocation_pct * 100:.1f}%</span>
    </div>
    <div class="holding-stats">
      <span>{h.total_quantity:,.4f} shares</span>
      <span class="sep">&middot;</span>
      <span>Avg {_fmt_money(h.avg_price)}</span>
      <span class="sep">&middot;</span>
      <span>Mkt {_fmt_money(h.market_price)}</span>
    </div>
    <div class="holding-metrics">
      <div class="metric">
        <div class="metric-value">{_fmt_money(h.total_value)}</div>
        <div class="metric-label">Value</div>
      </div>
      <div class="metric">
        <div class="metric-value {gc}">{_fmt_money(h.net_performance)}</div>
        <div class="metric-label">Gain / Loss</div>
      </div>
      <div class="metric">
        <div class="metric-value {gc}">{_fmt_pct(h.net_performance_pct * 100)}</div>
        <div class="metric-label">Return</div>
      </div>
    </div>{breakdown}
  </div>"""


def _render_account_type_section(
    section: AccountTypeSummary,
    snap: PortfolioSnapshot,
) -> str:
    """Collapsible account-type section with holdings table."""
    color = ACCT_TYPE_COLORS.get(section.account_type, "#94a3b8")
    pct = (section.total_value / snap.total_value * 100) if snap.total_value else 0
    total_inv = sum(ah.investment for ah in section.holdings)
    gain = section.total_value - total_inv
    gc = _gain_class(gain)

    rows: list[str] = []
    for ah in section.holdings:
        agc = _gain_class(ah.net_performance)
        avg = ah.investment / ah.quantity if ah.quantity else 0
        rows.append(
            f'<tr>'
            f'<td class="cell-symbol"><strong>{ah.symbol}</strong></td>'
            f'<td class="cell-muted">{ah.account_name}</td>'
            f'<td class="num">{ah.quantity:,.2f}</td>'
            f'<td class="num">{_fmt_money(avg)}</td>'
            f'<td class="num">{_fmt_money(ah.value)}</td>'
            f'<td class="num {agc}">{_fmt_money(ah.net_performance)}</td>'
            f'<td class="num {agc}">{_fmt_pct(ah.net_performance_pct * 100)}</td>'
            f'</tr>'
        )

    return f"""
  <details class="type-section">
    <summary class="type-header" style="border-left-color: {color}">
      <div class="type-title">
        <span class="type-name">{section.account_type}</span>
        <span class="type-value">{_fmt_money(section.total_value)}</span>
        <span class="type-pct">({pct:.1f}%)</span>
        <span class="type-gain {gc}">{_fmt_money(gain)} gain</span>
      </div>
      <div class="type-tax">{section.tax_note}</div>
    </summary>
    <div class="type-body">
      <table class="acct-table wide">
        <thead><tr>
          <th>Symbol</th><th>Account</th><th class="num">Shares</th>
          <th class="num">Avg Cost</th><th class="num">Value</th>
          <th class="num">Gain/Loss</th><th class="num">Return</th>
        </tr></thead>
        <tbody>
          {"".join(rows)}
        </tbody>
      </table>
    </div>
  </details>"""


# ── Main Renderer ────────────────────────────────────────────────

def render_html(
    snapshot: PortfolioSnapshot,
    show_account_details: bool = True,
) -> str:
    kpi = _render_kpi_cards(snapshot)
    alloc_chart = _render_allocation_chart(snapshot)
    type_chart = _render_account_type_chart(snapshot)

    holding_cards = "\n".join(
        _render_holding_card(h, CHART_COLORS[i % len(CHART_COLORS)], show_account_details)
        for i, h in enumerate(snapshot.holdings)
    )

    type_sections = ""
    if show_account_details:
        type_sections = "\n".join(
            _render_account_type_section(s, snapshot)
            for s in snapshot.account_type_sections
        )

    date_str = snapshot.report_date.strftime("%B %d, %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Portfolio Snapshot &mdash; {date_str}</title>
<style>
/* ── Reset & Base ── */
:root {{
  --bg: #f8fafc;
  --card: #ffffff;
  --border: #e2e8f0;
  --text: #1e293b;
  --muted: #64748b;
  --light: #94a3b8;
  --green: #10b981;
  --red: #ef4444;
  --header-bg: #0f172a;
  --roth: #3b82f6;
  --trad: #8b5cf6;
  --broker: #f59e0b;
  --shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md: 0 4px 6px rgba(0,0,0,0.05), 0 2px 4px rgba(0,0,0,0.03);
  --radius: 12px;
}}
*, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
               "Helvetica Neue", Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
}}
.container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}

/* ── Header ── */
.header {{
  background: var(--header-bg);
  color: #fff;
  padding: 24px 32px;
  border-radius: var(--radius);
  margin-bottom: 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}}
.header h1 {{ font-size: 1.5rem; font-weight: 600; }}
.header .date {{ font-size: 0.85rem; opacity: 0.7; margin-top: 2px; }}
.btn-pdf {{
  display: inline-block;
  padding: 10px 20px;
  background: rgba(255,255,255,0.12);
  color: #fff;
  text-decoration: none;
  border-radius: 8px;
  font-weight: 500;
  font-size: 0.85rem;
  border: 1px solid rgba(255,255,255,0.2);
  transition: background 0.15s;
}}
.btn-pdf:hover {{ background: rgba(255,255,255,0.22); }}
.btn-pdf-alt {{
  background: transparent;
  border: 1px solid rgba(255,255,255,0.3);
  font-size: 0.78rem;
  padding: 8px 16px;
}}
.btn-group {{ display: flex; gap: 8px; flex-wrap: wrap; }}

/* ── KPI Cards ── */
.kpi-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}}
.kpi-card {{
  background: var(--card);
  padding: 20px 24px;
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}}
.kpi-label {{
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  font-weight: 600;
  margin-bottom: 4px;
}}
.kpi-value {{
  font-size: clamp(1.4rem, 3vw, 2rem);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}}
.kpi-sub {{
  font-size: 0.85rem;
  font-weight: 500;
  margin-left: 8px;
}}

/* ── Charts ── */
.charts-row {{
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 24px;
}}
.chart-card {{
  flex: 1 1 400px;
  background: var(--card);
  padding: 20px 24px;
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}}
.chart-title {{
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 16px;
}}
.chart-body {{
  display: flex;
  align-items: center;
  gap: 24px;
}}
.donut {{
  width: 160px;
  height: 160px;
  flex-shrink: 0;
}}
.legend {{ flex: 1; }}
.legend-row {{
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
  font-size: 0.82rem;
}}
.legend-dot {{
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}}
.legend-label {{ flex: 1; color: var(--text); }}
.legend-pct {{
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  min-width: 44px;
  text-align: right;
}}
.legend-val {{
  color: var(--light);
  font-size: 0.78rem;
  min-width: 80px;
  text-align: right;
}}

/* ── Section Headings ── */
.section-heading {{
  font-size: 1.05rem;
  font-weight: 600;
  margin: 32px 0 16px;
  color: var(--text);
}}

/* ── Holding Cards ── */
.holding-card {{
  background: var(--card);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 20px 24px;
  margin-bottom: 12px;
}}
.holding-header {{
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 2px;
}}
.holding-id {{ display: flex; align-items: center; gap: 10px; }}
.holding-dot {{
  width: 10px; height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}}
.holding-symbol {{ font-size: 1.15rem; font-weight: 700; }}
.holding-name {{
  font-size: 0.85rem;
  color: var(--muted);
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}
.holding-alloc {{
  font-size: 0.85rem;
  color: var(--muted);
  font-weight: 600;
}}
.holding-stats {{
  font-size: 0.82rem;
  color: var(--muted);
  margin-bottom: 16px;
  padding-left: 20px;
}}
.holding-stats .sep {{ margin: 0 6px; opacity: 0.4; }}
.holding-metrics {{
  display: flex;
  gap: 40px;
  margin-bottom: 4px;
  padding-left: 20px;
}}
.metric-value {{
  font-size: 1.15rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}}
.metric-label {{
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--light);
  margin-top: 1px;
}}

/* ── Collapsible Account Details ── */
.acct-details {{
  margin-top: 12px;
  border-top: 1px solid var(--border);
}}
.acct-details summary {{
  cursor: pointer;
  font-size: 0.8rem;
  color: var(--muted);
  padding: 10px 0 10px 20px;
  list-style: none;
  min-height: 44px;
  display: flex;
  align-items: center;
  user-select: none;
}}
.acct-details summary::-webkit-details-marker {{ display: none; }}
.acct-details summary::before {{
  content: "\\25B8";
  margin-right: 8px;
  font-size: 0.7rem;
  transition: transform 0.15s;
}}
.acct-details[open] summary::before {{
  content: "\\25BE";
}}
.acct-table-wrap {{ overflow-x: auto; padding-left: 20px; }}
.acct-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}}
.acct-table th {{
  text-align: left;
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--light);
  font-weight: 600;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
}}
.acct-table th.num {{ text-align: right; }}
.acct-table td {{
  padding: 6px 10px;
  border-bottom: 1px solid #f1f5f9;
  font-variant-numeric: tabular-nums;
}}
.acct-table td.num {{ text-align: right; }}
.acct-table .cell-muted {{ color: var(--muted); }}
.acct-table .cell-symbol {{ font-weight: 600; }}
.acct-table.wide {{ font-size: 0.82rem; }}
.acct-table.wide td {{ padding: 8px 10px; }}

/* ── Type Badges ── */
.type-badge {{
  display: inline-block;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 0.6rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  white-space: nowrap;
}}
.type-badge.roth-ira {{ background: #dbeafe; color: var(--roth); }}
.type-badge.traditional-ira {{ background: #ede9fe; color: var(--trad); }}
.type-badge.regular-brokerage {{ background: #fef3c7; color: #b45309; }}

/* ── Account Type Sections ── */
.type-section {{ margin-bottom: 8px; }}
.type-header {{
  cursor: pointer;
  background: var(--card);
  border-radius: var(--radius);
  padding: 16px 20px;
  box-shadow: var(--shadow);
  border-left: 4px solid var(--muted);
  list-style: none;
  min-height: 44px;
  user-select: none;
}}
.type-header::-webkit-details-marker {{ display: none; }}
.type-title {{
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
}}
.type-name {{ font-weight: 700; font-size: 1rem; }}
.type-value {{
  font-weight: 600;
  font-size: 0.95rem;
  font-variant-numeric: tabular-nums;
}}
.type-pct {{ color: var(--muted); font-size: 0.85rem; }}
.type-gain {{ font-size: 0.85rem; font-variant-numeric: tabular-nums; }}
.type-tax {{
  font-size: 0.78rem;
  color: var(--muted);
  margin-top: 4px;
  font-style: italic;
}}
.type-section[open] .type-header {{
  border-radius: var(--radius) var(--radius) 0 0;
}}
.type-body {{
  background: var(--card);
  border-radius: 0 0 var(--radius) var(--radius);
  padding: 4px 20px 16px;
  box-shadow: var(--shadow);
  overflow-x: auto;
}}

/* ── Gain colors ── */
.gain-pos {{ color: var(--green); }}
.gain-neg {{ color: var(--red); }}

/* ── Footer ── */
.footer {{
  text-align: center;
  padding: 32px 0 16px;
  font-size: 0.78rem;
  color: var(--light);
}}

/* ── Responsive ── */
@media (max-width: 768px) {{
  .container {{ padding: 12px; }}
  .header {{ padding: 16px 20px; flex-direction: column; align-items: flex-start; }}
  .chart-body {{ flex-direction: column; align-items: center; }}
  .donut {{ width: 140px; height: 140px; }}
  .legend {{ width: 100%; }}
  .holding-metrics {{ gap: 20px; flex-wrap: wrap; padding-left: 0; }}
  .holding-stats {{ padding-left: 0; }}
  .holding-name {{ max-width: 180px; }}
  .type-title {{ gap: 8px; }}
}}

/* ── Print / PDF ── */
@media print {{
  body {{
    background: #fff;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}
  .container {{ padding: 0; max-width: none; }}
  .btn-pdf, .btn-group {{ display: none !important; }}
  .header {{ border-radius: 0; margin-bottom: 16px; padding: 16px 24px; }}

  /* Force all <details> sections open for print */
  details > summary {{ pointer-events: none; }}
  details > summary ~ * {{
    display: block !important;
  }}
  details > .acct-table-wrap,
  details > .type-body {{
    display: block !important;
  }}
  .acct-details {{ border-top-color: var(--border); }}
  .acct-details summary::before {{ content: "\\25BE"; }}

  /* Remove shadows, add borders */
  .kpi-card, .chart-card, .holding-card, .type-header, .type-body {{
    box-shadow: none;
    border: 1px solid var(--border);
  }}

  /* Page breaks */
  .holding-card {{ page-break-inside: avoid; }}
  .type-section {{ page-break-inside: avoid; }}
  .charts-row {{ page-break-inside: avoid; }}

  /* Preserve colors */
  .gain-pos {{ color: var(--green) !important; }}
  .gain-neg {{ color: var(--red) !important; }}
  .type-badge {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  .legend-dot {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  .holding-dot {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  circle {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
}}

@page {{
  size: landscape;
  margin: 12mm 10mm;
  @bottom-center {{
    content: "Portfolio Snapshot — {date_str} | Page " counter(page) " of " counter(pages);
    font-size: 8pt;
    color: #94a3b8;
  }}
}}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <div>
      <h1>Portfolio Snapshot</h1>
      <div class="date">{date_str}</div>
    </div>
    <div class="btn-group">
      <a href="/snapshot/pdf" class="btn-pdf">PDF Summary</a>
      <a href="/snapshot/pdf?details=1" class="btn-pdf btn-pdf-alt">PDF with Account Details</a>
    </div>
  </div>

  {kpi}

  <div class="charts-row">
    {alloc_chart}
    {type_chart}
  </div>

  <h2 class="section-heading">Holdings</h2>
  {holding_cards}

  {'<h2 class="section-heading">By Account Type</h2>' if type_sections else ""}
  {type_sections}

  <div class="footer">
    Generated by ghostfolio-importer &middot; Data from Ghostfolio
  </div>

</div>
</body>
</html>"""
