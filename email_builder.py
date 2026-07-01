#!/usr/bin/env python3
"""
email_builder.py
================
Email 1 (Action Brief) and Email 3 (Exit Report) for the long‑term screener.
Plus the trial email fallback.
"""

from datetime import datetime
from typing import List, Dict, Any

# Shared CSS (used by email_report.py as well)
_CSS_BASE = """
/* ── Professional research email — clean white, GS-inspired ────────────── */
*{margin:0;padding:0;box-sizing:border-box}
body{background:#f1f3f5;font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;padding:12px;color:#1a1d23;-webkit-text-size-adjust:100%;overflow-x:hidden}
.w{max-width:640px;width:100%;margin:0 auto;background:#fff;border-radius:2px;overflow:hidden;box-shadow:0 1px 12px rgba(0,0,0,.07)}
/* Header — white with a thin top accent bar */
.hdr-stripe{height:3px;background:#0d2137}
.hdr{padding:18px 16px 14px;background:#fff;border-bottom:1px solid #eaecef}
.hdr-row{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px}
.brand{font-size:13px;font-weight:700;color:#0d2137;letter-spacing:.06em;text-transform:uppercase}
.issue{font-size:9px;color:#9ca3af;letter-spacing:.12em;text-transform:uppercase}
.hdr-title{font-size:20px;font-weight:700;color:#111827;margin-bottom:3px;letter-spacing:-.02em}
.hdr-sub{font-size:10px;color:#6b7280}
/* Stats bar — light grey, never dark */
.stats{display:flex;background:#f8f9fa;border-bottom:1px solid #eaecef;flex-wrap:wrap}
.stats-cell{flex:1;min-width:60px;padding:12px 14px;border-right:1px solid #eaecef}
.stats-cell:last-child{border-right:none}
.stat-l{font-size:8px;font-weight:600;letter-spacing:.15em;text-transform:uppercase;color:#9ca3af;margin-bottom:4px}
.stat-v{font-size:16px;font-weight:700;color:#111827;letter-spacing:-.01em}
.stat-v.pos{color:#15803d}.stat-v.neg{color:#b91c1c}.stat-v.neu{color:#4b5563}
/* Body */
.body{padding:16px 16px 24px}
/* Sections */
.section{margin-bottom:28px}
.section-hdr{font-size:8px;font-weight:600;letter-spacing:.18em;text-transform:uppercase;color:#9ca3af;margin-bottom:14px;padding-bottom:6px;border-bottom:1px solid #eaecef}
/* Cards */
.card{border:1px solid #e5e7eb;border-radius:2px;margin-bottom:10px;overflow:hidden;background:#fff}
.card-head{padding:14px 16px;border-bottom:1px solid #f0f2f5;display:flex;justify-content:space-between;align-items:flex-start;gap:10px;background:#fafbfc}
.card-ticker{font-size:18px;font-weight:800;color:#111827;letter-spacing:-.01em;line-height:1.1}
.card-company{font-size:10px;color:#6b7280;margin-top:2px}
.card-body{padding:12px 16px}
/* Tier pills */
.pill{display:inline-block;font-size:8px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;padding:2px 7px;border-radius:2px;margin-right:4px}
.p-t1{background:#f0fdf4;color:#15803d;border:1px solid #bbf7d0}
.p-t2{background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe}
.p-t3{background:#fff7ed;color:#c2410c;border:1px solid #fed7aa}
.p-buy{background:#f0fdf4;color:#15803d;border:1px solid #86efac}
.p-inc{background:#fffbeb;color:#b45309;border:1px solid #fde68a}
.p-sell{background:#fef2f2;color:#b91c1c;border:1px solid #fecaca}
/* Inline value colours */
.pos{color:#15803d}.neg{color:#b91c1c}.neu{color:#4b5563}
/* Sentiment badges */
.sv-pos{background:#f0fdf4;color:#15803d;border:1px solid #bbf7d0;font-size:8px;font-weight:600;padding:2px 6px;border-radius:2px}
.sv-neg{background:#fef2f2;color:#b91c1c;border:1px solid #fecaca;font-size:8px;font-weight:600;padding:2px 6px;border-radius:2px}
.sv-neu{background:#f3f4f6;color:#4b5563;border:1px solid #d1d5db;font-size:8px;font-weight:600;padding:2px 6px;border-radius:2px}
.sv-mix{background:#fffbeb;color:#b45309;border:1px solid #fde68a;font-size:8px;font-weight:600;padding:2px 6px;border-radius:2px}
.sv-sig{background:#fef2f2;color:#b91c1c;font-size:8px;font-weight:700;padding:2px 6px;border-radius:2px}
.sv-noi{background:#f3f4f6;color:#6b7280;font-size:8px;font-weight:600;padding:2px 6px;border-radius:2px}
.sv-mix2{background:#fffbeb;color:#b45309;font-size:8px;font-weight:600;padding:2px 6px;border-radius:2px}
/* Footer — light, never dark navy */
.ftr{background:#f8f9fa;padding:14px 16px;border-top:1px solid #eaecef;color:#9ca3af;font-size:9px;line-height:1.7}
.ftr-brand{font-size:11px;font-weight:600;color:#374151;margin-bottom:3px}
.ftr-disc{font-size:9px;color:#9ca3af;margin-top:6px;line-height:1.6}
/* IPO rows */
.ipo-row{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #f3f4f6;font-size:11px}
.ipo-name{font-weight:600;color:#1a1d23}
.ipo-detail{font-size:9px;color:#9ca3af;margin-top:1px}
.ipo-days{font-size:10px;font-weight:600;color:#6b7280}
/* KiwiSaver routing */
.ks-block{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.ks-col{border:1px solid #e5e7eb;border-radius:2px;padding:12px}
.ks-hdr{font-size:8px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:#9ca3af;margin-bottom:6px}
.ks-list{font-size:11px;color:#374151;line-height:1.8;font-weight:600}
"""

def _t(tier: str) -> str:
    cls = f'p-{tier.lower()}'
    return f'<span class="pill {cls}">{tier}</span>'

def _val(v, fmt='pct1', na='—'):
    if v is None: return na
    try:
        f = float(v)
        if fmt == 'pct1': return f'{f:.1f}%'
        if fmt == 'x': return f'{f:.1f}x'
        return str(f)
    except: return na

def _cls(v, pos_thresh=0, neg_thresh=0):
    if v is None: return 'neu'
    try:
        f = float(v)
        if f >= pos_thresh: return 'pos'
        if f <= neg_thresh: return 'neg'
        return 'neu'
    except: return 'neu'

def _sent_badge(s: str) -> str:
    m = {'POSITIVE':'sv-pos','NEGATIVE':'sv-neg','NEUTRAL':'sv-neu','MIXED':'sv-mix'}
    cls = m.get(s.upper(), 'sv-neu')
    return f'<span class="{cls}" style="font-size:9px;padding:2px 5px;border-radius:2px">{s.title()}</span>'

def _sig_badge(s: str) -> str:
    m = {'SIGNAL':'sv-sig','NOISE':'sv-noi','MIXED':'sv-mix2'}
    cls = m.get(s.upper(), 'sv-noi')
    return f'<span class="{cls}" style="font-size:9px;padding:2px 5px;border-radius:2px">{s.title()}</span>'

def _mt_tag(label: str, score: int) -> str:
    return f'<span style="background:#e8f0fe;color:#1a4ab5;padding:3px 8px;border-radius:12px;font-size:9px">{label} · {score}/10</span>'


def _entry_zone(h):
    """
    Returns ('buy'|'wait'|'monitor', reason_str) using stock-specific thesis + scenario data.
    """
    above_200     = h.get('above_200ma')
    pct_from_high = h.get('pct_from_high')
    thesis        = (h.get('thesis_summary') or '').strip()
    scenario      = h.get('scenario') or {}
    tracking      = (scenario.get('current_tracking') or '').strip()
    tracking_note = (scenario.get('tracking_note') or '').strip()

    # Trim thesis to one readable sentence
    thesis_snip = ''
    if thesis:
        sentence = thesis.split('.')[0].strip()
        thesis_snip = sentence + '.' if sentence else ''

    p = abs(pct_from_high) if pct_from_high is not None else None

    if above_200 is False:
        parts = ['Trading below its 200-day moving average — a classic accumulation signal for long-term investors.']
        if thesis_snip:
            parts.append(f'Thesis: {thesis_snip}')
        if tracking:
            parts.append(f'Scenario tracking: {tracking}' + (f' — {tracking_note}' if tracking_note else '') + '.')
        return 'buy', ' '.join(parts)

    if pct_from_high is not None and pct_from_high > -8:
        parts = [f'Only {p:.0f}% off its 52-week high — near peak territory, risk/reward is tight right now.']
        if thesis_snip:
            parts.append(f'The thesis remains intact: {thesis_snip}')
        parts.append('Wait for a 10–15% pullback before adding to this position.')
        return 'wait', ' '.join(parts)

    if pct_from_high is not None:
        depth = 'significant' if p >= 20 else 'healthy'
        parts = [f'{p:.0f}% off its 52-week high — a {depth} pullback that offers a better entry than recent buyers got.']
        if thesis_snip:
            parts.append(f'Thesis: {thesis_snip}')
        if tracking:
            parts.append(f'Scenario tracking: {tracking}' + (f' — {tracking_note}' if tracking_note else '') + '.')
        return 'buy', ' '.join(parts)

    reason = thesis_snip if thesis_snip else 'No technical data available. Review the thesis manually.'
    return 'monitor', reason


def _stock_row(h, show_hint=True):
    """
    Full-width card per holding. Three clear sections:
      1) Tier + TICKER + company  |  Return %
      2) BOUGHT date + entry price  |  TODAY'S PRICE
      3) Can I still enter? — explicit YES / WAIT answer
    """
    ticker     = h.get('ticker', '')
    company    = h.get('company_name', ticker)
    ep         = h.get('entry_price')
    cp         = h.get('current_price')
    date_added = h.get('date_added', '')
    tier       = h.get('tier', '')
    a200       = h.get('above_200ma')
    pfh        = h.get('pct_from_high')

    try:
        from datetime import datetime as _dt
        date_s = _dt.strptime(date_added, '%Y-%m-%d').strftime('%b %Y') if date_added else '—'
    except Exception:
        date_s = '—'

    ep_s  = f'${ep:,.2f}' if ep else '—'
    cp_s  = f'${cp:,.2f}' if cp else '—'
    chg   = ((cp - ep) / ep * 100) if (ep and cp and ep != cp) else None
    chg_s = (f'{"+" if chg >= 0 else ""}{chg:.1f}%') if chg is not None else '—'
    chg_c = '#15803d' if (chg or 0) >= 0 else '#dc2626'

    tier_c   = {'T1': '#15803d', 'T2': '#1d4ed8', 'T3': '#d97706'}.get(tier, '#9ca3af')
    border_c = tier_c

    # Can I still enter?
    zone, reason = _entry_zone(h)
    if zone == 'buy':
        sig_label = 'YES &mdash; Good entry at today\'s price'
        sig_c, sig_bg, sig_bdr = '#166534', '#f0fdf4', '#86efac'
    elif zone == 'wait':
        sig_label = 'WAIT &mdash; Near 52-week high, hold off'
        sig_c, sig_bg, sig_bdr = '#92400e', '#fffbeb', '#fcd34d'
    else:
        sig_label = 'HOLD &mdash; No clear entry signal'
        sig_c, sig_bg, sig_bdr = '#374151', '#f3f4f6', '#d1d5db'

    reason_html = (f'<div style="font-size:10px;color:{sig_c};margin-top:5px;line-height:1.5">{reason}</div>'
                   if reason else '')

    return (
        f'<tr><td style="padding:0 0 10px 0">'
        f'<table width="100%" border="0" cellpadding="0" cellspacing="0" '
        f'style="border-left:4px solid {border_c};border-bottom:1px solid #e5e7eb;background:#ffffff">'

        # ── SECTION 1: Ticker + Return ──────────────────────────────────
        f'<tr>'
        f'<td style="padding:14px 16px 4px 14px;vertical-align:middle">'
        f'<span style="font-size:9px;font-weight:700;letter-spacing:.06em;color:{tier_c}">{tier}</span>'
        f'&nbsp;&nbsp;<strong style="font-size:21px;color:#111827;letter-spacing:-.02em;vertical-align:middle">{ticker}</strong>'
        f'<div style="font-size:11px;color:#6b7280;margin-top:4px">{company}</div>'
        f'</td>'
        f'<td style="padding:14px 16px 4px 8px;text-align:right;vertical-align:top;white-space:nowrap">'
        f'<strong style="font-size:28px;color:{chg_c};letter-spacing:-.02em;line-height:1">{chg_s}</strong>'
        f'</td>'
        f'</tr>'

        # ── DIVIDER ─────────────────────────────────────────────────────
        f'<tr><td colspan="2" style="padding:8px 14px 0">'
        f'<div style="height:1px;background:#f0f2f5"></div>'
        f'</td></tr>'

        # ── SECTION 2: Bought date | Today's price ───────────────────────
        f'<tr>'
        f'<td style="padding:10px 8px 10px 14px;width:50%;vertical-align:top">'
        f'<div style="font-size:8px;font-weight:700;color:#9ca3af;letter-spacing:.12em;text-transform:uppercase;margin-bottom:5px">Bought</div>'
        f'<div style="font-size:15px;font-weight:700;color:#111827">{date_s}</div>'
        f'<div style="font-size:10px;color:#6b7280;margin-top:3px">at entry price {ep_s}</div>'
        f'</td>'
        f'<td style="padding:10px 14px 10px 8px;width:50%;text-align:right;vertical-align:top">'
        f'<div style="font-size:8px;font-weight:700;color:#9ca3af;letter-spacing:.12em;text-transform:uppercase;margin-bottom:5px">Today\'s Price</div>'
        f'<div style="font-size:15px;font-weight:700;color:#111827">{cp_s}</div>'
        f'</td>'
        f'</tr>'

        # ── SECTION 3: Can I still enter? ───────────────────────────────
        f'<tr><td colspan="2" style="padding:0 12px 14px">'
        f'<div style="background:{sig_bg};border:1px solid {sig_bdr};border-radius:4px;padding:10px 14px">'
        f'<div style="font-size:11px;font-weight:700;color:{sig_c}">{sig_label}</div>'
        f'{reason_html}'
        f'</div>'
        f'</td></tr>'

        f'</table>'
        f'</td></tr>'
    )


def _action_month_row(item, kind):
    """Card row for this-month buy/sell/add — same card structure as _stock_row."""
    ticker     = item.get('ticker', '')
    company    = item.get('company_name', ticker)
    ep         = item.get('entry_price')
    cp         = item.get('current_price')
    tier       = item.get('tier', '')
    date_added = item.get('date_added', '')

    try:
        from datetime import datetime as _dt
        date_s = _dt.strptime(date_added, '%Y-%m-%d').strftime('%b %Y') if date_added else '—'
    except Exception:
        date_s = '—'

    ep_s  = f'${ep:,.2f}' if ep else '—'
    cp_s  = f'${cp:,.2f}' if cp else '—'
    chg   = ((cp - ep) / ep * 100) if (ep and cp and ep != cp) else None
    chg_s = (f'{"+" if chg >= 0 else ""}{chg:.1f}%') if chg is not None else '—'
    chg_c = '#15803d' if (chg or 0) >= 0 else '#dc2626'

    badge_map = {
        'buy':      ('NEW BUY',  '#f0fdf4', '#15803d', '#86efac', '#15803d'),
        'sell':     ('SOLD',     '#fef2f2', '#b91c1c', '#fecaca', '#dc2626'),
        'increase': ('ADDED TO', '#fffbeb', '#b45309', '#fde68a', '#d97706'),
    }
    blabel, bbg, btxt, bbd, border_c = badge_map.get(kind, ('', '#f3f4f6', '#6b7280', '#e5e7eb', '#e5e7eb'))

    note = item.get('exit_reason', '') if kind == 'sell' else ''
    note_html = (f'<div style="font-size:10px;color:#6b7280;margin-top:3px">{note[:60]}</div>'
                 if note else '')

    return (
        f'<tr><td style="padding:0 0 10px 0">'
        f'<table width="100%" border="0" cellpadding="0" cellspacing="0" '
        f'style="border-left:4px solid {border_c};border-bottom:1px solid #e5e7eb;background:#fff">'

        f'<tr>'
        f'<td style="padding:14px 16px 4px 14px;vertical-align:middle">'
        f'<span style="background:{bbg};color:{btxt};border:1px solid {bbd};'
        f'font-size:8px;font-weight:700;padding:2px 8px;border-radius:2px">{blabel}</span>'
        f'&nbsp;&nbsp;<strong style="font-size:21px;color:#111827;letter-spacing:-.02em;vertical-align:middle">{ticker}</strong>'
        f'<div style="font-size:11px;color:#6b7280;margin-top:4px">{company}</div>'
        f'</td>'
        f'<td style="padding:14px 16px 4px 8px;text-align:right;vertical-align:top;white-space:nowrap">'
        f'<strong style="font-size:28px;color:{chg_c};letter-spacing:-.02em;line-height:1">{chg_s}</strong>'
        f'</td>'
        f'</tr>'

        f'<tr><td colspan="2" style="padding:8px 14px 0">'
        f'<div style="height:1px;background:#f0f2f5"></div>'
        f'</td></tr>'

        f'<tr>'
        f'<td style="padding:10px 8px 14px 14px;width:50%;vertical-align:top">'
        f'<div style="font-size:8px;font-weight:700;color:#9ca3af;letter-spacing:.12em;text-transform:uppercase;margin-bottom:5px">Bought</div>'
        f'<div style="font-size:15px;font-weight:700;color:#111827">{date_s}</div>'
        f'<div style="font-size:10px;color:#6b7280;margin-top:3px">at entry price {ep_s}</div>'
        f'{note_html}'
        f'</td>'
        f'<td style="padding:10px 14px 14px 8px;width:50%;text-align:right;vertical-align:top">'
        f'<div style="font-size:8px;font-weight:700;color:#9ca3af;letter-spacing:.12em;text-transform:uppercase;margin-bottom:5px">Today\'s Price</div>'
        f'<div style="font-size:15px;font-weight:700;color:#111827">{cp_s}</div>'
        f'</td>'
        f'</tr>'

        f'</table>'
        f'</td></tr>'
    )


def generate_action_email(decisions: Dict, portfolio: Dict) -> tuple:
    """
    Action Brief — action-grouped layout.
    Holdings sorted into: ADD MORE / NEAR HIGH (WAIT) / MONITORING.
    Dark header, portfolio stats bar, fully table-based.
    """
    month_str = datetime.now().strftime('%B %Y')
    date_str  = datetime.now().strftime('%d %b %Y')
    issue_n   = len(portfolio.get('run_history', [])) + 1
    subject   = f'Action Brief | {month_str} | Autonomous Capital'

    new_additions = decisions.get('new_additions', [])
    exits         = decisions.get('exits', [])
    migrations    = decisions.get('migrations', [])

    holdings = [h for h in portfolio.get('holdings', []) if h.get('status') == 'ACTIVE']

    # Portfolio aggregate stats
    returns = []
    for h in holdings:
        ep, cp = h.get('entry_price'), h.get('current_price')
        if ep and cp and ep != cp:
            returns.append((cp - ep) / ep * 100)
    avg_ret   = sum(returns) / len(returns) if returns else None
    n_pos     = sum(1 for r in returns if r >= 0)
    n_neg     = len(returns) - n_pos
    avg_ret_s = f'{"+" if (avg_ret or 0) >= 0 else ""}{avg_ret:.1f}%' if avg_ret is not None else '—'
    avg_ret_c = '#15803d' if (avg_ret or 0) >= 0 else '#dc2626'

    # Classify holdings into zones
    buy_zone, wait_zone, monitor_zone = [], [], []
    for h in holdings:
        zone, _ = _entry_zone(h)
        if zone == 'buy':
            buy_zone.append(h)
        elif zone == 'wait':
            wait_zone.append(h)
        else:
            monitor_zone.append(h)

    def _sort_key(h):
        t_order = {'T1': 0, 'T2': 1, 'T3': 2}.get(h.get('tier', 'T9'), 9)
        ep, cp = h.get('entry_price'), h.get('current_price')
        ret = ((cp - ep) / ep) if (ep and cp) else 0
        return (t_order, -ret)

    buy_zone     = sorted(buy_zone, key=_sort_key)
    wait_zone    = sorted(wait_zone, key=_sort_key)
    monitor_zone = sorted(monitor_zone, key=_sort_key)

    def _divider(label):
        return (
            f'<tr><td style="padding:16px 0 6px">'
            f'<div style="font-size:8px;font-weight:700;color:#9ca3af;letter-spacing:.15em;'
            f'text-transform:uppercase;padding:0 2px">{label}</div>'
            f'</td></tr>'
        )

    # Build body rows — buy zone first, then wait, then monitor
    body_rows = ''
    if new_additions or exits or migrations:
        body_rows += _divider("This month&#39;s actions")
        for item in new_additions:
            body_rows += _action_month_row(item, 'buy')
        for item in migrations:
            body_rows += _action_month_row(item, 'increase')
        for item in exits:
            body_rows += _action_month_row(item, 'sell')

    if buy_zone:
        body_rows += _divider(f'Can still enter &mdash; {len(buy_zone)} holdings')
        for h in buy_zone:
            body_rows += _stock_row(h)

    if wait_zone:
        body_rows += _divider(f'Near highs, wait for pullback &mdash; {len(wait_zone)} holdings')
        for h in wait_zone:
            body_rows += _stock_row(h)

    if monitor_zone:
        body_rows += _divider(f'Monitoring &mdash; {len(monitor_zone)} holdings')
        for h in monitor_zone:
            body_rows += _stock_row(h)

    html = f'''<!DOCTYPE html><html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<style>{_CSS_BASE}</style></head><body>
<div class="w">

<!-- HEADER: dark navy -->
<div style="background:#0d2137;padding:20px 16px 18px">
  <div style="font-size:9px;font-weight:600;color:#94a3b8;letter-spacing:.15em;text-transform:uppercase;margin-bottom:6px">Autonomous Capital</div>
  <table width="100%" border="0" cellpadding="0" cellspacing="0"><tr>
    <td style="vertical-align:bottom">
      <div style="font-size:26px;font-weight:800;color:#ffffff;letter-spacing:-.02em;line-height:1">Action Brief</div>
      <div style="font-size:10px;color:#64748b;margin-top:6px">{month_str} &middot; {len(holdings)} holdings</div>
    </td>
    <td style="text-align:right;vertical-align:top;white-space:nowrap">
      <div style="font-size:9px;color:#475569">#{str(issue_n).zfill(2)}</div>
      <div style="font-size:9px;color:#475569;margin-top:2px">{date_str}</div>
    </td>
  </tr></table>
</div>

<!-- STATS BAR: avg return · gainers · laggards -->
<table width="100%" border="0" cellpadding="0" cellspacing="0" style="border-bottom:2px solid #eaecef">
  <tr>
    <td style="padding:14px 0;width:33%;text-align:center;border-right:1px solid #eaecef">
      <div style="font-size:8px;font-weight:600;color:#9ca3af;letter-spacing:.12em;text-transform:uppercase;margin-bottom:4px">Avg Return</div>
      <div style="font-size:20px;font-weight:800;color:{avg_ret_c};letter-spacing:-.02em">{avg_ret_s}</div>
    </td>
    <td style="padding:14px 0;width:33%;text-align:center;border-right:1px solid #eaecef">
      <div style="font-size:8px;font-weight:600;color:#9ca3af;letter-spacing:.12em;text-transform:uppercase;margin-bottom:4px">Gainers</div>
      <div style="font-size:20px;font-weight:800;color:#15803d;letter-spacing:-.02em">{n_pos}</div>
    </td>
    <td style="padding:14px 0;width:34%;text-align:center">
      <div style="font-size:8px;font-weight:600;color:#9ca3af;letter-spacing:.12em;text-transform:uppercase;margin-bottom:4px">Laggards</div>
      <div style="font-size:20px;font-weight:800;color:{"#dc2626" if n_neg else "#9ca3af"};letter-spacing:-.02em">{n_neg}</div>
    </td>
  </tr>
</table>

<!-- HOLDINGS GROUPED BY ZONE -->
<table width="100%" border="0" cellpadding="0" cellspacing="0" style="padding:0 12px">
  {body_rows}
</table>

<!-- FOOTER -->
<table width="100%" border="0" cellpadding="0" cellspacing="0" style="border-top:1px solid #eaecef">
  <tr><td style="padding:11px 16px;font-size:9px;color:#9ca3af">
    Autonomous Capital &middot; Not financial advice. Verify before acting.
  </td></tr>
</table>

</div></body></html>'''
    return html, subject


def generate_exit_email(exits: List[Dict], month_str: str) -> tuple:
    """
    Email 3 — Exit Report.
    Full trade review including returns vs benchmarks and post‑mortem.
    """
    date_str = datetime.now().strftime('%d %b %Y')
    tickers  = ', '.join(h['ticker'] for h in exits[:3])
    if len(exits) > 3:
        tickers += f' and {len(exits)-3} more'
    subject  = f'Exit Report — {tickers} · {month_str}'

    css = _CSS_BASE + """
.ecard{border:1px solid #e8e8ec;border-radius:4px;margin-bottom:20px;overflow:hidden}
.ec-head{background:#1c0808;padding:14px 16px}
.ec-ticker{font-size:22px;font-weight:800;color:#fff}
.ec-co{font-size:9px;color:rgba(255,255,255,.45)}
.ec-right{text-align:right}
.ret-big{font-size:22px;font-weight:800}
.ret-big.pos{color:#4caf7d}
.ret-big.neg{color:#e05555}
.badge{font-size:8px;font-weight:700;padding:2px 6px;border-radius:2px}
.b-exit{background:#e05555;color:#fff}
.b-win{background:#4caf7d;color:#fff}
.b-loss{background:#e05555;color:#fff}
.b-alpha{background:#1a4ab5;color:#fff}
.b-lag{background:#6b7280;color:#fff}
.returns-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}
.ret-cell{background:#f9fafb;border-radius:2px;padding:8px;text-align:center}
.ret-k{font-size:7px;color:#a0a0aa}
.ret-v{font-size:14px;font-weight:800}
.ret-v.pos{color:#16a34a}
.ret-v.neg{color:#dc2626}
.journey-line{display:flex;align-items:center;padding:6px 0;font-size:9px;border-bottom:0.5px solid #f5f5f8}
.j-date{width:64px;color:#8a8a9a}
.j-dot{width:10px;height:10px;border-radius:50%;margin:0 10px}
.j-dot.add{background:#4caf7d}
.j-dot.exit{background:#e05555}
.thesis-box{background:#fff8f0;border-left:3px solid #e8a020;padding:9px 11px;margin-bottom:8px}
.exit-box{background:#fff5f5;border-left:3px solid #e05555;padding:9px 11px}
.lesson-box{background:#f0f4ff;border-left:3px solid #5b9bd6;padding:9px 11px}
"""

    def _exit_card(h):
        ticker     = h.get('ticker','')
        company    = h.get('company_name', ticker)
        tier       = h.get('tier','T2')
        date_added = str(h.get('date_added', ''))[:7]
        exit_date  = str(h.get('exit_date',  ''))[:10]
        months     = h.get('months_held', '—')
        entry_p    = h.get('entry_price') or h.get('current_price')
        exit_p     = h.get('exit_price')
        ret_pct    = h.get('return_pct')
        qqq_ret    = h.get('qqq_return_pct')
        spy_ret    = h.get('spy_return_pct')
        alpha      = h.get('alpha_vs_qqq')
        exit_reason = h.get('exit_reason', 'Thesis conditions no longer met')
        thesis      = h.get('thesis_summary', '')
        breaks_if   = h.get('thesis_breaks_if', '')
        tracking    = h.get('scenario', {}).get('current_tracking', '—')

        ret_str  = f'{ret_pct:+.1f}%' if ret_pct is not None else '—'
        ret_cls  = 'pos' if (ret_pct or 0) >= 0 else 'neg'
        alpha_str = f'{alpha:+.1f}%' if alpha is not None else '—'
        entry_str = f'${entry_p:.0f}' if entry_p else '—'
        exit_str  = f'${exit_p:.0f}' if exit_p else '—'

        if ret_pct is not None and alpha is not None:
            if ret_pct >= 0 and alpha >= 0:
                lesson = f'Thesis worked. Outperformed QQQ by {alpha_str}. Exit condition correctly identified.'
            elif ret_pct >= 0 and alpha < 0:
                lesson = f'Positive return (+{ret_pct:.1f}%) but lagged QQQ by {abs(alpha):.1f}%.'
            elif ret_pct < 0:
                lesson = f'Loss of {ret_pct:.1f}%. Thesis did not play out.'
            else:
                lesson = 'Review thesis assumptions against actual outcome.'
        else:
            lesson = 'Review original thesis against actual outcome.'

        win_badge = 'b-win' if (ret_pct or 0) >= 0 else 'b-loss'
        win_label = 'Gain' if (ret_pct or 0) >= 0 else 'Loss'
        alpha_badge = 'b-alpha' if (alpha or 0) >= 0 else 'b-lag'
        alpha_label = 'Beat' if (alpha or 0) >= 0 else 'Lagged'

        return f'''
<div class="ecard">
<div class="ec-head" style="display:flex;justify-content:space-between">
  <div>
    <div class="badges">
      <span class="badge b-exit">EXIT</span>
      <span class="badge b-t{tier[-1].lower()}">{tier}</span>
      <span class="badge {win_badge}">{win_label}</span>
      <span class="badge {alpha_badge}">{alpha_label} QQQ</span>
    </div>
    <div class="ec-ticker">{ticker}</div>
    <div class="ec-co">{company}</div>
  </div>
  <div class="ec-right">
    <div class="ret-big {ret_cls}">{ret_str}</div>
    <div class="ret-lbl">total return</div>
  </div>
</div>
<div class="ec-meta" style="padding:8px 16px;background:#1a0808;color:rgba(255,255,255,.5);font-size:9px;display:flex;gap:16px;flex-wrap:wrap">
  <div>Held <strong>{months} months</strong></div>
  <div>Entry <strong>{entry_str} · {date_added}</strong></div>
  <div>Exit <strong>{exit_str} · {exit_date[:7]}</strong></div>
  <div>vs QQQ <strong>{alpha_str}</strong></div>
</div>
<div class="returns-grid" style="padding:12px 16px">
  <div class="ret-cell"><div class="ret-k">Your return</div><div class="ret-v {ret_cls}">{ret_str}</div></div>
  <div class="ret-cell"><div class="ret-k">QQQ same period</div><div class="ret-v {'pos' if (qqq_ret or 0)>=0 else 'neg'}">{qqq_ret:+.1f}%' if qqq_ret else '—'</div></div>
  <div class="ret-cell"><div class="ret-k">Alpha</div><div class="ret-v {'pos' if (alpha or 0)>=0 else 'neg'}">{alpha_str}</div></div>
</div>
<div class="journey-line" style="padding:6px 16px"><div class="j-date">{date_added}</div><div class="j-dot add"></div><div>Thesis: "{thesis[:80]}..."</div></div>
<div class="journey-line" style="padding:6px 16px"><div class="j-date">Monthly</div><div class="j-dot" style="background:#e8e8ec"></div><div>Tracking: {tracking}</div></div>
<div class="journey-line" style="padding:6px 16px"><div class="j-date">{exit_date[:7]}</div><div class="j-dot exit"></div><div>Exit reason: {exit_reason[:100]}</div></div>
<div class="thesis-box" style="margin:10px 16px"><div class="thesis-lbl">Original exit condition</div><div class="thesis-txt">{breaks_if}</div></div>
<div class="exit-box" style="margin:10px 16px"><div class="exit-lbl">Why we sold</div><div class="exit-txt">{exit_reason}</div></div>
<div class="lesson-box" style="margin:10px 16px"><div class="lesson-lbl">Post‑mortem</div><div class="lesson-txt">{lesson}</div></div>
</div>'''

    total_return = sum(h.get('return_pct', 0) or 0 for h in exits) / len(exits) if exits else 0
    total_alpha  = sum(h.get('alpha_vs_qqq', 0) or 0 for h in exits) / len(exits) if exits else 0
    ret_cls      = 'pos' if total_return >= 0 else 'neg'
    alpha_cls    = 'pos' if total_alpha >= 0 else 'neg'

    cards = ''.join(_exit_card(h) for h in exits)

    html = f'''<!DOCTYPE html><html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<style>{css}</style></head><body>
<div class="w">
<div class="hdr-stripe"></div>
<div class="hdr">
  <div class="hdr-row">
    <div class="brand">Autonomous Capital &middot; Exit Report</div>
    <div class="issue">{date_str}</div>
  </div>
  <div class="hdr-title">Trade Review &mdash; {month_str}</div>
  <div class="hdr-sub">Return attribution &middot; Alpha vs benchmark &middot; Thesis post-mortem</div>
</div>
<div class="stats">
  <div class="stats-cell"><div class="stat-l">Exits</div><div class="stat-v">{len(exits)}</div></div>
  <div class="stats-cell"><div class="stat-l">Avg return</div><div class="stat-v {ret_cls}">{total_return:+.1f}%</div></div>
  <div class="stats-cell"><div class="stat-l">Avg alpha</div><div class="stat-v {alpha_cls}">{total_alpha:+.1f}%</div></div>
</div>
<div class="body">
<div class="section"><div class="section-hdr">Exited holdings — full trade review</div>
{cards}
</div>
</div>
<div class="ftr">
  <div class="ftr-brand">Autonomous Capital &middot; Exit Report</div>
  <div class="ftr-disc">For informational purposes only. Not financial advice. Returns are indicative and should be verified against your broker records.</div>
</div>
</div></body></html>'''
    return html, subject


def generate_trial_email(candidates: dict, total_fundamentals: int, total_universe: int) -> tuple:
    """
    Trial email (fallback) — sent when portfolio is empty or API credits missing.
    Shows screened candidates that passed fundamental gates but have no research yet.
    """
    month_str = datetime.now().strftime('%B %Y')
    subject = f'Trial Run · Screened Candidates · {month_str}'

    # Build simple HTML listing candidates
    rows = []
    for ticker, cand in candidates.items():
        tier = cand.get('tier', '?')
        score = cand.get('score', 0)
        reason = cand.get('reason', 'Passed')
        rows.append(f'''
        <tr style="border-bottom:1px solid #e8e8ec">
          <td style="padding:8px;font-weight:700">{ticker}</td>
          <td style="padding:8px"><span class="pill p-{tier.lower()}">{tier}</span></td>
          <td style="padding:8px">{score}</td>
          <td style="padding:8px;color:#6a7a8a">{reason[:60]}</td>
        </tr>
        ''')

    html = f'''<!DOCTYPE html><html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<style>{_CSS_BASE}</style></head><body>
<div class="w">
<div class="hdr">
  <div class="brand">Autonomous Capital · Trial Run</div>
  <div class="issue">{datetime.now().strftime('%d %b %Y')}</div>
  <div class="hdr-title">Screened Candidates — {month_str}</div>
  <div class="hdr-sub">{total_universe:,} universe → {total_fundamentals:,} fundamentals → {len(candidates)} candidates</div>
</div>
<div class="body">
<div class="section">
  <div class="section-hdr">Candidates that passed T1/T2/T3 gates</div>
  <p style="font-size:11px;color:#5a6470;margin-bottom:12px">Full thesis and scenarios will be generated once API credits are available.</p>
  <table style="width:100%;border-collapse:collapse;font-size:11px">
    <thead><tr style="background:#f8f9fb;text-align:left">
      <th style="padding:8px">Ticker</th><th style="padding:8px">Tier</th><th style="padding:8px">Score</th><th style="padding:8px">Reason</th>
    </tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</div>
</div>
<div class="ftr">Autonomous Capital · Trial mode · No API credits consumed</div>
</div></body></html>'''
    return html, subject


def _action_card(item, kind):
    """Compact action card — crisp table layout, one decision per card."""
    ticker        = item.get('ticker', '')
    company       = item.get('company_name', ticker)
    tier          = item.get('tier', '')
    pos           = item.get('position_size_pct', item.get('target_pct', 0)) or 0
    ks            = item.get('kiwisaver_available', False)
    thesis        = item.get('thesis_summary', item.get('thesis', ''))
    exit_c        = item.get('thesis_breaks_if', '')
    above_200     = item.get('above_200ma')
    ret_1yr       = item.get('return_1yr')
    vs_qqq        = item.get('return_vs_qqq')
    mkt_cap       = item.get('market_cap', 0) or 0
    roic          = item.get('roic')
    gm            = item.get('gross_margin')
    entry_price   = item.get('entry_price')
    curr_price    = item.get('current_price')
    pct_from_high = item.get('pct_from_high')
    intel         = item.get('news_intelligence') or {}
    intel_impact  = intel.get('thesis_impact', '')
    intel_reason  = intel.get('impact_reason', '')
    sec_8k        = item.get('sec_8k_count', 0) or 0

    # ── Header pills & colours ────────────────────────────────────────────────
    _amap = {
        'sell':     ('Sell',      '#b91c1c', 'p-sell'),
        'increase': ('Increase',  '#b45309', 'p-inc'),
        'buy':      ('+ Add',     '#15803d', 'p-buy'),
    }
    _act_label, _border_c, _act_cls = _amap.get(kind, _amap['buy'])
    act_pill = f'<span class="pill {_act_cls}" style="font-size:10px;padding:3px 10px">{_act_label}</span>'
    ks_pill  = '<span class="pill p-t1" style="font-size:7px;padding:1px 5px">KiwiSaver</span>' if ks else ''

    _tier_bg, _tier_border, _tier_tk = {
        'T1': ('#f0fdf4', '#15803d', '#14532d'),
        'T2': ('#eff6ff', '#1d4ed8', '#1e3a8a'),
        'T3': ('#fff7ed', '#d97706', '#92400e'),
    }.get(tier, ('#fafbfc', '#e5e7eb', '#111827'))

    pos_html = (f'<div style="text-align:right">'
                f'<div style="font-size:16px;font-weight:700;color:#111827">{round(pos,1)}%</div>'
                f'<div style="font-size:8px;color:#9ca3af;letter-spacing:.1em;text-transform:uppercase">portfolio</div>'
                f'</div>') if pos else ''

    # ── Price row (buy / increase only) ──────────────────────────────────────
    price_row = ''
    if kind in ('buy', 'increase') and (entry_price or curr_price):
        _ep = entry_price or curr_price
        _cp = curr_price  or entry_price
        _chg = ((_cp - _ep) / _ep * 100) if (_ep and _cp and _ep != _cp) else None
        _chg_c = '#15803d' if (_chg or 0) >= 0 else '#dc2626'
        _chg_s = f'({"+" if (_chg or 0) >= 0 else ""}{_chg:.1f}%)' if _chg is not None else ''

        if above_200 is False:
            _sig, _sig_c = 'Below 200MA — buy opportunity', '#15803d'
        elif pct_from_high is not None and pct_from_high > -8:
            _sig, _sig_c = 'Near 52w high — may be extended', '#d97706'
        elif pct_from_high is not None and pct_from_high > -20:
            _sig, _sig_c = 'Good entry range', '#15803d'
        elif pct_from_high is not None:
            _sig, _sig_c = f'{abs(pct_from_high):.0f}% off high — strong entry', '#15803d'
        else:
            _sig, _sig_c = '', '#4b5563'

        price_row = (
            f'<tr style="border-bottom:1px solid #f0f2f5">'
            f'<td colspan="4" style="padding:8px 12px;background:#f8fbff">'
            f'<span style="font-size:8px;color:#0369a1;font-weight:600;text-transform:uppercase;letter-spacing:.08em">Screened at</span>'
            f'<span style="font-size:14px;font-weight:700;color:#0c4a6e;margin-left:6px">${_ep:,.2f}</span>'
            f'<span style="font-size:10px;color:#94a3b8;margin:0 6px">&rarr; Now</span>'
            f'<span style="font-size:14px;font-weight:700;color:#111827">${_cp:,.2f}</span>'
            f'<span style="font-size:10px;font-weight:600;color:{_chg_c};margin-left:5px">{_chg_s}</span>'
            + (f'<span style="float:right;font-size:9px;font-weight:600;color:{_sig_c};line-height:2">{_sig}</span>' if _sig else '')
            + f'</td></tr>'
        )

    # ── Data grid (4 cells) ───────────────────────────────────────────────────
    def _cell(label, value, color='#111827'):
        return (f'<td style="padding:8px 12px;border-right:1px solid #f0f2f5;width:25%">'
                f'<div style="font-size:8px;color:#9ca3af;font-weight:600;text-transform:uppercase;letter-spacing:.08em;margin-bottom:2px">{label}</div>'
                f'<div style="font-size:13px;font-weight:700;color:{color}">{value}</div>'
                f'</td>')

    mc_str   = f'${mkt_cap/1e9:.0f}B'      if mkt_cap  else '—'
    roic_str = f'{roic*100:.0f}%'           if roic     else '—'
    gm_str   = f'{gm*100:.0f}%'             if gm       else '—'
    r1y_str  = f'{ret_1yr:+.0f}%'           if ret_1yr is not None else '—'
    r1y_c    = '#15803d' if (ret_1yr or 0) >= 0 else '#b91c1c'
    qqq_str  = f'{vs_qqq:+.0f}%'            if vs_qqq is not None else '—'
    qqq_c    = '#15803d' if (vs_qqq or 0) >= 0 else '#b91c1c'

    data_row = (
        _cell('Mkt Cap', mc_str) +
        _cell('ROIC', roic_str) +
        _cell('1yr Return', r1y_str, r1y_c) +
        _cell('vs QQQ', qqq_str, qqq_c)
    )

    # ── News signal (1 line) ──────────────────────────────────────────────────
    _isig_map = {
        'STRENGTHENS': ('#15803d', '▲ Strengthens'),
        'THREATENS':   ('#b91c1c', '▼ Threatens'),
        'NEUTRAL':     ('#6b7280', '— Neutral'),
    }
    if intel_impact in _isig_map:
        _ic, _ilbl = _isig_map[intel_impact]
        _reason_txt = f' — {intel_reason}' if intel_reason else ''
        news_signal = (f'<div style="font-size:9px;color:{_ic};padding:5px 12px;border-top:1px solid #f0f2f5">'
                       f'<strong>{_ilbl}</strong>{_reason_txt}'
                       + (f' &middot; <span style="color:#9ca3af">{sec_8k} 8-K</span>' if sec_8k else '')
                       + f'</div>')
    elif sec_8k:
        news_signal = (f'<div style="font-size:9px;color:#b45309;padding:5px 12px;border-top:1px solid #f0f2f5">'
                       f'{sec_8k} SEC 8-K filing{"s" if sec_8k != 1 else ""}</div>')
    else:
        news_signal = ''

    # ── Thesis (max 2 lines, ~160 chars) ─────────────────────────────────────
    thesis_short = (thesis[:160] + '…') if thesis and len(thesis) > 160 else thesis
    thesis_row = (f'<tr style="border-top:1px solid #f0f2f5">'
                  f'<td colspan="4" style="padding:8px 12px;font-size:10px;color:#374151;line-height:1.5">'
                  f'{thesis_short}</td></tr>') if thesis_short else ''

    # ── Exit condition ────────────────────────────────────────────────────────
    exit_short = (exit_c[:120] + '…') if exit_c and len(exit_c) > 120 else exit_c
    exit_row   = (f'<tr><td colspan="4" style="padding:6px 12px 10px;font-size:9px;color:#6b7280">'
                  f'<strong style="color:#b91c1c">Exit if:</strong> {exit_short}</td></tr>') if exit_short else ''

    return f'''<div style="border:1px solid #e5e7eb;border-radius:3px;margin-bottom:10px;overflow:hidden">
  <div style="background:{_tier_bg};border-bottom:2px solid {_tier_border};padding:12px 16px;display:flex;justify-content:space-between;align-items:flex-start">
    <div>
      <div style="display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin-bottom:4px">{act_pill} {_t(tier)} {ks_pill}</div>
      <div style="font-size:20px;font-weight:800;color:{_tier_tk};letter-spacing:-.01em;line-height:1.1">{ticker}</div>
      <div style="font-size:10px;color:#6b7280;margin-top:2px">{company}</div>
    </div>
    {pos_html}
  </div>
  <table style="width:100%;border-collapse:collapse">
    {price_row}
    <tr style="border-bottom:1px solid #f0f2f5">{data_row}</tr>
    {thesis_row}
    {exit_row}
  </table>
  {news_signal}
</div>'''
