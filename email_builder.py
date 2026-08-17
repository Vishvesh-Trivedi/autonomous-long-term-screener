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
/* ── Research-brief holding / screened cards (email_report.py) ─────────── */
.rcard{margin-bottom:18px;border:1px solid #e5e7eb;border-radius:3px;overflow:hidden;background:#fff}
.rc-head{padding:14px 16px;background:#fafbfc;border-bottom:1px solid #eaecef}
.rc-left{margin-bottom:4px}
.rc-right{margin-top:2px}
.rc-ticker{font-size:21px;font-weight:800;color:#111827;letter-spacing:-.02em}
.rc-company{font-size:12px;color:#6b7280;margin-top:2px}
.rc-tier{font-size:11px;color:#374151;font-weight:600;margin-top:4px}
.rc-status{font-size:11px;margin-top:2px}
.rc-body{padding:12px 16px}
/* Metric snapshot tables — the core data grids */
.dtable{width:100%;border-collapse:collapse;margin:6px 0 14px;font-size:12px}
.dtable caption{text-align:left;font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#9ca3af;padding:2px 0 7px}
.dtable td{padding:7px 8px;border-bottom:1px solid #f0f2f5;vertical-align:top;line-height:1.35}
.dtable td.k{color:#6b7280;font-weight:600;white-space:nowrap}
.sv{display:inline-block;font-size:10px;font-weight:600;padding:2px 6px;border-radius:2px;background:#f3f4f6;color:#4b5563}
.flag-clean{color:#15803d;font-weight:700}
.flag-watch{color:#d97706;font-weight:700}
.flag-flag{color:#b91c1c;font-weight:700}
/* ── Mobile (phones): bump the tiny labels so everything is legible ────── */
@media screen and (max-width:600px){
  body{padding:6px !important}
  .w{border-radius:0 !important}
  .body{padding:12px 12px 20px !important}
  .section{margin-bottom:20px !important}
  .stat-l,.section-hdr,.ks-hdr,.card-company,.issue{font-size:10px !important}
  .stat-v{font-size:16px !important}
  .rc-ticker{font-size:22px !important}
  .rc-company,.rc-tier,.rc-status{font-size:12px !important}
  .dtable{font-size:13px !important}
  .dtable td{padding:8px 6px !important}
  .dtable caption{font-size:10px !important}
  .card-ticker{font-size:19px !important}
  .ks-block{display:block !important}
  .ks-col{margin-bottom:10px !important}
}
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


def _rating_style(verdict) -> tuple:
    """Shared long-term rating colours/labels (15-20yr stance, not a trade)."""
    v = str(verdict or '').upper()
    return {
        'CORE_HOLD':   ('#1d4ed8', '#eff4ff', 'CORE HOLD'),
        'ACCUMULATE':  ('#15803d', '#f0fdf4', 'ACCUMULATE'),
        'MOONSHOT':    ('#7c3aed', '#f5f3ff', 'MOONSHOT'),
        'MONITOR':     ('#d97706', '#fffbeb', 'MONITOR'),
        'SPECULATIVE': ('#d97706', '#fffbeb', 'SPECULATIVE'),
        'TRIM':        ('#d97706', '#fffbeb', 'TRIM'),
        'AVOID':       ('#dc2626', '#fef2f2', 'AVOID'),
        'EXIT':        ('#dc2626', '#fef2f2', 'EXIT'),
    }.get(v, ('#6b7280', '#f8f9fa', v or '\u2014'))


def _action_call(h):
    """
    The honest 'what do I do this month' call = long-term rating x entry timing.
    A dip never turns a MONITOR/AVOID name into a buy; technicals are only used
    to time accumulation of names we already rate as accumulate-friendly.
    Returns (label, color, bg, border, priority) where higher priority = more
    actionable (used to pick the 'one thing this month').
    """
    verdict = str(h.get('verdict', '') or '').upper()
    zone, reason = _entry_zone(h)

    # Ratings we are willing to add to on weakness.
    accumulate_ok = verdict in ('CORE_HOLD', 'ACCUMULATE', 'MOONSHOT')
    small = ' (small)' if verdict == 'MOONSHOT' else ''

    if verdict in ('AVOID', 'EXIT'):
        return ('DO NOT ADD &mdash; reason to own it broke', '#b91c1c', '#fef2f2', '#fecaca', reason, 0)
    if verdict in ('MONITOR', 'SPECULATIVE', 'TRIM'):
        return ('HOLD &mdash; still checking, don&#39;t add', '#92400e', '#fffbeb', '#fcd34d', reason, 1)
    if accumulate_ok:
        if zone == 'buy':
            return (f'ADD{small} &mdash; good time to add', '#166534', '#f0fdf4', '#86efac', reason, 3)
        if zone == 'wait':
            return ('HOLD &mdash; wait for a better entry', '#92400e', '#fffbeb', '#fcd34d', reason, 1)
        return ('HOLD &mdash; no clear entry signal', '#374151', '#f3f4f6', '#d1d5db', reason, 1)

    # Unknown/blank verdict — fall back to the neutral entry-zone read.
    if zone == 'buy':
        return ('YES &mdash; reasonable entry today', '#166534', '#f0fdf4', '#86efac', reason, 2)
    if zone == 'wait':
        return ('WAIT &mdash; near 52-week high', '#92400e', '#fffbeb', '#fcd34d', reason, 1)
    return ('HOLD &mdash; no clear entry signal', '#374151', '#f3f4f6', '#d1d5db', reason, 1)



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
        parts = ['Trading below its 200-day average price — often a good time for long-term investors to add.']
        if thesis_snip:
            parts.append(f'Why we own it: {thesis_snip}')
        if tracking:
            parts.append(f'Tracking vs our outlook: {tracking}' + (f' — {tracking_note}' if tracking_note else '') + '.')
        return 'buy', ' '.join(parts)

    if pct_from_high is not None and pct_from_high > -8:
        parts = [f'Only {p:.0f}% off its 52-week high — near its peak, so the reward for the risk is thin right now.']
        if thesis_snip:
            parts.append(f'The reason to own it still holds: {thesis_snip}')
        parts.append('Wait for a 10–15% dip before adding to this position.')
        return 'wait', ' '.join(parts)

    if pct_from_high is not None:
        depth = 'big' if p >= 20 else 'healthy'
        parts = [f'{p:.0f}% off its 52-week high — a {depth} dip that offers a better entry price than recent buyers got.']
        if thesis_snip:
            parts.append(f'Why we own it: {thesis_snip}')
        if tracking:
            parts.append(f'Tracking vs our outlook: {tracking}' + (f' — {tracking_note}' if tracking_note else '') + '.')
        return 'buy', ' '.join(parts)

    reason = thesis_snip if thesis_snip else 'No price-trend data. Review the reasons to own it manually.'
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

    # Long-term rating badge (15-20yr stance) — shown alongside the tier so the
    # action below connects to the committee's actual verdict.
    _rc, _rbg, _rlbl = _rating_style(h.get('verdict'))
    rating_badge = (
        f'&nbsp;<span style="background:{_rbg};color:{_rc};font-size:8px;font-weight:700;'
        f'padding:2px 6px;border-radius:2px;border:1px solid {_rc}33;vertical-align:middle;'
        f'letter-spacing:.04em">{_rlbl}</span>'
    ) if h.get('verdict') else ''

    # What to do this month = rating x entry timing (a dip never buys a MONITOR/AVOID).
    sig_label, sig_c, sig_bg, sig_bdr, reason, _prio = _action_call(h)

    reason_html = (f'<div style="font-size:10px;color:{sig_c};margin-top:5px;line-height:1.5">{reason}</div>'
                   if reason else '')

    # Compact senior-analyst signals: valuation stance, insider net direction,
    # and an honest 'partial data' flag when the call rests on incomplete inputs.
    _sig_chips = []
    _val = h.get('valuation_label')
    if _val and _val not in ('—', 'FAIR'):
        _vc = {'CHEAP': '#15803d', 'RICH': '#d97706', 'EXTREME': '#dc2626'}.get(_val, '#6b7280')
        _sig_chips.append(f'<span style="color:{_vc};font-weight:700">{_val} valuation</span>')
    # Expected return (probability-weighted 10yr IRR from the scenario model)
    _exp_irr = (h.get('scenario') or {}).get('expected_irr_pct')
    if isinstance(_exp_irr, (int, float)):
        _ec = '#15803d' if _exp_irr >= 8 else '#d97706' if _exp_irr >= 0 else '#dc2626'
        _sig_chips.append(f'<span style="color:{_ec};font-weight:700">~{_exp_irr:.0f}%/yr expected</span>')
    # Priced-for-perfection sizing flag (reverse-DCF)
    if h.get('priced_for_perfection'):
        _sig_chips.append('<span style="color:#dc2626;font-weight:700">priced for perfection — start small</span>')
    elif h.get('implied_growth_label') == 'DEMANDING' and isinstance(h.get('implied_growth_pct'), (int, float)):
        _sig_chips.append(f'<span style="color:#d97706">price assumes ~{h["implied_growth_pct"]:.0f}%/yr growth</span>')
    # Reinvestment payoff (ROIIC)
    _roiic_l = h.get('roiic_label')
    if _roiic_l in ('STRONG', 'SOLID'):
        _sig_chips.append('<span style="color:#15803d">high reinvestment payoff</span>')
    elif _roiic_l in ('FADING', 'POOR'):
        _sig_chips.append('<span style="color:#d97706">fading reinvestment payoff</span>')
    _ins = h.get('insider_net_signal') or h.get('insider_signal')
    if _ins == 'SELLING':
        _sig_chips.append('<span style="color:#dc2626">insiders selling</span>')
    elif _ins == 'BUYING':
        _sig_chips.append('<span style="color:#15803d">insiders buying</span>')
    _dil = h.get('dilution_trajectory')
    if _dil in ('SEVERE', 'HIGH'):
        _sig_chips.append('<span style="color:#dc2626">serial dilution</span>')
    _csig = h.get('congress_signal')
    if h.get('congress_source') == 'efd' and _csig in ('BUYING', 'SELLING', 'MIXED'):
        _cc = {'BUYING': '#15803d', 'SELLING': '#dc2626', 'MIXED': '#d97706'}[_csig]
        _clbl = {'BUYING': 'senators buying', 'SELLING': 'senators selling', 'MIXED': 'senators trading'}[_csig]
        _sig_chips.append(f'<span style="color:{_cc}">{_clbl}</span>')
    _dq = h.get('data_completeness') or {}
    if _dq.get('band') == 'THIN':
        _sig_chips.append('<span style="color:#b45309">partial data</span>')
    chips_html = (f'<div style="font-size:9.5px;color:#6b7280;margin-top:6px">'
                  + ' &middot; '.join(_sig_chips) + '</div>') if _sig_chips else ''

    # Portfolio-action advisories on held names (drift trim / event re-research).
    _adv = [x for x in (h.get('concentration_flag'), h.get('rerun_flag')) if x]
    adv_html = ''
    if _adv:
        adv_html = (f'<div style="font-size:9.5px;color:#92400e;background:#fffbeb;'
                    f'border:1px solid #fde68a;border-radius:3px;padding:5px 9px;margin-top:6px">'
                    + '<br>'.join(f'&#9873; {a}' for a in _adv) + '</div>')

    return (
        f'<tr><td style="padding:0 0 10px 0">'
        f'<table width="100%" border="0" cellpadding="0" cellspacing="0" '
        f'style="border-left:4px solid {border_c};border-bottom:1px solid #e5e7eb;background:#ffffff">'

        # ── SECTION 1: Ticker + Return ──────────────────────────────────
        f'<tr>'
        f'<td style="padding:14px 16px 4px 14px;vertical-align:middle">'
        f'<span style="font-size:9px;font-weight:700;letter-spacing:.06em;color:{tier_c}">{tier}</span>'
        f'{rating_badge}'
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
        f'{chips_html}'
        f'{adv_html}'
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

    # Committee self-review flag (advisory) — only shown when not OK.
    rflag = str(item.get('review_flag', '') or '').upper()
    review_html = ''
    if rflag in ('REVIEW', 'OVERRIDE'):
        rc = '#b45309' if rflag == 'REVIEW' else '#b91c1c'
        rbg = '#fffbeb' if rflag == 'REVIEW' else '#fef2f2'
        rnote = str(item.get('review_note', ''))[:90]
        review_html = (
            f'<div style="margin-top:5px;font-size:9.5px;color:{rc};background:{rbg};'
            f'border:1px solid {rc}33;border-radius:3px;padding:3px 6px;display:inline-block">'
            f'\u26a0 Committee {rflag}: {rnote}</div>'
        )

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
        f'{review_html}'
        f'</td>'
        f'<td style="padding:10px 14px 14px 8px;width:50%;text-align:right;vertical-align:top">'
        f'<div style="font-size:8px;font-weight:700;color:#9ca3af;letter-spacing:.12em;text-transform:uppercase;margin-bottom:5px">Today\'s Price</div>'
        f'<div style="font-size:15px;font-weight:700;color:#111827">{cp_s}</div>'
        f'</td>'
        f'</tr>'

        f'</table>'
        f'</td></tr>'
    )


def generate_action_email(decisions: Dict, portfolio: Dict, decision_review: Dict = None) -> tuple:
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

    # Per-tier average return — user may accumulate only certain tiers (e.g. T1),
    # so break the book's return out by T1 / T2 / T3.
    def _tier_avg_return(tier):
        rets = []
        for h in holdings:
            if h.get('tier') != tier:
                continue
            ep, cp = h.get('entry_price'), h.get('current_price')
            if ep and cp and ep != cp:
                rets.append((cp - ep) / ep * 100)
        avg = sum(rets) / len(rets) if rets else None
        s = f'{"+" if (avg or 0) >= 0 else ""}{avg:.1f}%' if avg is not None else '—'
        c = ('#9ca3af' if avg is None else ('#15803d' if avg >= 0 else '#dc2626'))
        return s, c, len(rets)
    t1_ret_s, t1_ret_c, t1_ret_n = _tier_avg_return('T1')
    t2_ret_s, t2_ret_c, t2_ret_n = _tier_avg_return('T2')
    t3_ret_s, t3_ret_c, t3_ret_n = _tier_avg_return('T3')

    # Accumulation-oriented counts (matches the 15-20yr book, not a trading P&L):
    # how many holdings are actionable-to-add now vs hold vs under review.
    n_add = n_hold_act = n_review = 0
    _top_add = None  # (priority, decade_prob, alpha, holding) for 'one thing this month'
    for h in holdings:
        _lbl, _c, _bg, _bdr, _rsn, _prio = _action_call(h)
        v = str(h.get('verdict', '') or '').upper()
        if _prio >= 2 and 'ADD' in _lbl.upper():
            n_add += 1
            key = (_prio,
                   h.get('decade_probability') or 0,
                   h.get('annual_alpha_estimate') or 0)
            if _top_add is None or key > _top_add[0]:
                _top_add = (key, h, _lbl)
        elif v in ('MONITOR', 'SPECULATIVE', 'TRIM', 'AVOID', 'EXIT'):
            n_review += 1
        else:
            n_hold_act += 1

    # 'If you do one thing this month' — the single highest-conviction add.
    priority_banner = ''
    if _top_add is not None:
        _, _ph, _plbl = _top_add
        _pc, _pbg, _plrat = _rating_style(_ph.get('verdict'))
        _pt = _ph.get('ticker', '')
        _pco = _ph.get('company_name', _pt)
        priority_banner = (
            f'<div style="margin:0 12px 8px;padding:12px 14px;background:#f0fdf4;'
            f'border:1px solid #bbf7d0;border-left:4px solid #15803d;border-radius:3px">'
            f'<div style="font-size:8px;font-weight:700;color:#15803d;letter-spacing:.12em;'
            f'text-transform:uppercase;margin-bottom:4px">If you do one thing this month</div>'
            f'<div style="font-size:13px;color:#111827;font-weight:700">Add to {_pt} '
            f'<span style="background:{_pbg};color:{_pc};font-size:8px;font-weight:700;'
            f'padding:2px 6px;border-radius:2px;border:1px solid {_pc}33">{_plrat}</span></div>'
            f'<div style="font-size:10px;color:#4b5563;margin-top:3px">{_pco} is a good '
            f'place to add right now &mdash; a chance to buy a bit more of a company we hold for the long run.</div>'
            f'</div>'
        )

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
        body_rows += _divider(f'Good time to add &mdash; {len(buy_zone)} holdings')
        for h in buy_zone:
            body_rows += _stock_row(h)

    if wait_zone:
        body_rows += _divider(f'Near highs, wait for a better entry &mdash; {len(wait_zone)} holdings')
        for h in wait_zone:
            body_rows += _stock_row(h)

    if monitor_zone:
        body_rows += _divider(f'Monitoring &mdash; {len(monitor_zone)} holdings')
        for h in monitor_zone:
            body_rows += _stock_row(h)

    # Committee self-review banner (advisory). Shows the overall critique plus a
    # count of decisions flagged for a second look.
    review_banner = ''
    dr = decision_review or {}
    _p_note = str(dr.get('portfolio_note', '') or '').strip()
    _n_flag = sum(1 for v in (dr.get('reviews') or {}).values()
                  if str(v.get('flag', '')).upper() in ('REVIEW', 'OVERRIDE'))
    if _p_note or _n_flag:
        _flag_txt = (f'<span style="color:#b45309;font-weight:700">{_n_flag} flagged for review</span>'
                     if _n_flag else '<span style="color:#15803d;font-weight:700">all decisions consistent</span>')
        review_banner = (
            f'<div style="margin:0 12px 4px;padding:11px 14px;background:#f8fafc;'
            f'border:1px solid #e2e8f0;border-left:4px solid #475569;border-radius:3px">'
            f'<div style="font-size:8px;font-weight:700;color:#475569;letter-spacing:.12em;'
            f'text-transform:uppercase;margin-bottom:4px">Model self-check &middot; {_flag_txt}</div>'
            f'<div style="font-size:11px;color:#334155;line-height:1.5">{_p_note[:280]}</div>'
            f'</div>'
        )

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

<!-- STATS BAR: avg return · accumulate now · under review -->
<table width="100%" border="0" cellpadding="0" cellspacing="0" style="border-bottom:2px solid #eaecef">
  <tr>
    <td style="padding:14px 0;width:33%;text-align:center;border-right:1px solid #eaecef">
      <div style="font-size:8px;font-weight:600;color:#9ca3af;letter-spacing:.12em;text-transform:uppercase;margin-bottom:4px">Avg Return</div>
      <div style="font-size:20px;font-weight:800;color:{avg_ret_c};letter-spacing:-.02em">{avg_ret_s}</div>
    </td>
    <td style="padding:14px 0;width:33%;text-align:center;border-right:1px solid #eaecef">
      <div style="font-size:8px;font-weight:600;color:#9ca3af;letter-spacing:.12em;text-transform:uppercase;margin-bottom:4px">Add Now</div>
      <div style="font-size:20px;font-weight:800;color:{"#15803d" if n_add else "#9ca3af"};letter-spacing:-.02em">{n_add}</div>
    </td>
    <td style="padding:14px 0;width:34%;text-align:center">
      <div style="font-size:8px;font-weight:600;color:#9ca3af;letter-spacing:.12em;text-transform:uppercase;margin-bottom:4px">Under Review</div>
      <div style="font-size:20px;font-weight:800;color:{"#d97706" if n_review else "#9ca3af"};letter-spacing:-.02em">{n_review}</div>
    </td>
  </tr>
</table>

<!-- STATS BAR 2: average return by tier (you may accumulate only some tiers) -->
<table width="100%" border="0" cellpadding="0" cellspacing="0" style="border-bottom:2px solid #eaecef">
  <tr>
    <td style="padding:12px 0;width:33%;text-align:center;border-right:1px solid #eaecef">
      <div style="font-size:8px;font-weight:600;color:#15803d;letter-spacing:.12em;text-transform:uppercase;margin-bottom:4px">T1 Avg Return</div>
      <div style="font-size:18px;font-weight:800;color:{t1_ret_c};letter-spacing:-.02em">{t1_ret_s}</div>
      <div style="font-size:8px;color:#9ca3af;margin-top:2px">{t1_ret_n} priced</div>
    </td>
    <td style="padding:12px 0;width:33%;text-align:center;border-right:1px solid #eaecef">
      <div style="font-size:8px;font-weight:600;color:#1d4ed8;letter-spacing:.12em;text-transform:uppercase;margin-bottom:4px">T2 Avg Return</div>
      <div style="font-size:18px;font-weight:800;color:{t2_ret_c};letter-spacing:-.02em">{t2_ret_s}</div>
      <div style="font-size:8px;color:#9ca3af;margin-top:2px">{t2_ret_n} priced</div>
    </td>
    <td style="padding:12px 0;width:34%;text-align:center">
      <div style="font-size:8px;font-weight:600;color:#d97706;letter-spacing:.12em;text-transform:uppercase;margin-bottom:4px">T3 Avg Return</div>
      <div style="font-size:18px;font-weight:800;color:{t3_ret_c};letter-spacing:-.02em">{t3_ret_s}</div>
      <div style="font-size:8px;color:#9ca3af;margin-top:2px">{t3_ret_n} priced</div>
    </td>
  </tr>
</table>

{priority_banner}
{review_banner}
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
.b-t1{background:#0f5132;color:#fff}
.b-t2{background:#1e40af;color:#fff}
.b-t3{background:#9a3412;color:#fff}
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
  <div class="ret-cell"><div class="ret-k">QQQ same period</div><div class="ret-v {'pos' if (qqq_ret or 0)>=0 else 'neg'}">{f"{qqq_ret:+.1f}%" if qqq_ret is not None else "—"}</div></div>
  <div class="ret-cell"><div class="ret-k">Alpha</div><div class="ret-v {'pos' if (alpha or 0)>=0 else 'neg'}">{alpha_str}</div></div>
</div>
<div class="journey-line" style="padding:6px 16px"><div class="j-date">{date_added}</div><div class="j-dot add"></div><div>Thesis: "{thesis[:80]}..."</div></div>
<div class="journey-line" style="padding:6px 16px"><div class="j-date">Ongoing</div><div class="j-dot" style="background:#e8e8ec"></div><div>Tracking: {tracking}</div></div>
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
    qqq_ret       = (ret_1yr - vs_qqq) if (ret_1yr is not None and vs_qqq is not None) else None
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
    qqq_str  = f'{qqq_ret:+.0f}%'            if qqq_ret is not None else '—'
    qqq_c    = '#6b7280'

    data_row = (
        _cell('Mkt Cap', mc_str) +
        _cell('ROIC', roic_str) +
        _cell('1yr Return', r1y_str, r1y_c) +
        _cell('QQQ 1yr', qqq_str, qqq_c)
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
