#!/usr/bin/env python3
"""
email_report.py
===============
Email 2 — Research Brief (Goldman Sachs standard).

Dense, analytical, professional. Every holding gets a full research card:
  - Megatrend alignment
  - Business quality (ROIC, margins, FCF, earnings quality)
  - Capital structure (net cash, coverage, dilution)
  - Management signals (insider ownership, Form 4 activity)
  - Technical position (200MA, 52w range, 1yr vs QQQ)
  - Sentiment (Finnhub, Reddit, 8-K, signal/noise)
  - 20-year thesis and scenarios
  - Exit condition
  - 10‑K highlights (prominent, authoritative)
"""

from datetime import datetime
from email_builder import _CSS_BASE, _t, _val, _cls, _sent_badge, _sig_badge, _mt_tag


def _pct(v, na='—'):
    if v is None: return na
    try: return f'{float(v)*100:.1f}%'
    except: return na

def _pct2(v, na='—'):
    """Already a percentage (e.g. return_1yr is already in %)"""
    if v is None: return na
    try: return f'{float(v):+.1f}%'
    except: return na

def _money(v, na='—'):
    if v is None: return na
    try:
        f = float(v)
        if abs(f) >= 1000: return f'${f/1e3:.1f}B'
        return f'${f:.0f}M'
    except: return na

def _score(v, total=10, na='—'):
    if v is None: return na
    return f'{int(v)}/{total}'


def _holding_card(h: dict) -> str:
    ticker    = h.get('ticker','')
    company   = h.get('company_name', ticker)
    tier      = h.get('tier','T2')
    pos       = h.get('position_size_pct', 0) or 0
    ks        = h.get('kiwisaver_available', False)
    date_added= str(h.get('date_added',''))[:7]

    # Megatrend
    mt_lbl    = h.get('megatrend_label','')
    mt_score  = h.get('megatrend_score', 0) or 0

    # Fundamentals (from Yahoo)
    roic      = h.get('roic')
    gm        = h.get('gross_margin')
    rev_gr    = h.get('rev_growth')
    eq        = h.get('earnings_quality','—')
    fcf_yield = h.get('fcf_yield')
    de        = h.get('de_ratio')
    cov       = h.get('interest_coverage')
    net_cash  = h.get('net_cash_m')
    net_flag  = h.get('net_cash_flag','—')
    insider   = h.get('insider_pct')
    dilution  = h.get('dilution_rate')
    rd_int    = h.get('rd_intensity', 0) or 0
    moat_prx  = h.get('moat_proxy_label','—')

    # Technicals
    cur_price = h.get('current_price')
    above200  = h.get('above_200ma')
    pct_high  = h.get('pct_from_high')
    pct_200ma = h.get('pct_from_200ma')
    ret_1yr   = h.get('return_1yr')
    vs_qqq    = h.get('return_vs_qqq')
    qqq_ret   = (ret_1yr - vs_qqq) if (ret_1yr is not None and vs_qqq is not None) else None
    trend     = h.get('trend','—')
    cagr3     = h.get('return_3yr_cagr')
    cagr5     = h.get('return_5yr_cagr')
    cagr10    = h.get('return_10yr_cagr')
    max_dd    = h.get('max_drawdown')
    lt_alpha  = h.get('long_term_alpha_pp')
    lt_note   = h.get('long_term_note','')

    # Sentiment
    news_n    = h.get('news_count', 0) or 0
    news_sent = h.get('news_sentiment','NEUTRAL')
    reddit_n  = h.get('reddit_mentions', 0) or 0
    reddit_src= h.get('reddit_source','')
    reddit_disp = 'n/a' if reddit_src == 'blocked' else f'{reddit_n}'
    # Congress (Senate eFD) trading signal
    cong_src  = h.get('congress_source','unavailable')
    cong_sig  = h.get('congress_signal','UNAVAILABLE')
    cong_buys = h.get('congress_buys', 0) or 0
    cong_sells= h.get('congress_sells', 0) or 0
    sec_8k    = h.get('sec_8k_count',0) or 0
    signal    = h.get('signal_or_noise','NOISE')
    sent_note = h.get('sentiment_note','')
    sent_conf = h.get('sentiment_confidence', '—')
    sec_events     = h.get('sec_8k_events', [])
    sec_highlights = h.get('sec_8k_highlights', [])
    sec_latest_date= h.get('sec_8k_latest_date', '')
    congress_tx    = h.get('congress_disclosures', [])

    # Research
    thesis    = h.get('thesis_summary','')
    breaks_if = h.get('thesis_breaks_if','')
    moat_type = h.get('moat_type','')
    moat_dur  = h.get('moat_durability_years','')
    mgmt_gr   = h.get('management_grade','')
    runway_yr = h.get('growth_runway_years','')
    risk      = h.get('primary_risk','')
    decade_p  = h.get('decade_probability')
    alpha_est = h.get('annual_alpha_estimate')
    ten_k_hl  = h.get('ten_k_highlights', [])   # list of strings

    # Sector durability (20-yr)
    sect_dur  = h.get('sector_durability_20yr', '')
    sect_note = h.get('sector_survival_note', '')
    sect_risk = h.get('sector_risk_note', '')   # set only when this downgraded the verdict — see screener.py research_candidate()

    # Senior-analyst signals (valuation, insider net, multi-year integrity, data quality)
    val_label  = h.get('valuation_label', '—')
    val_note   = h.get('valuation_note', '')
    val_peg    = h.get('val_peg')
    ins_net    = h.get('insider_net_signal') or h.get('insider_signal', '—')
    ins_note   = h.get('insider_note', '')
    eq3        = h.get('earnings_quality_3yr', eq)
    eq3_dir    = h.get('eq_trend_direction', '—')
    dil_traj   = h.get('dilution_trajectory', '—')
    share5     = h.get('share_5yr_change')
    dq         = h.get('data_completeness') or {}
    conc_flag  = h.get('concentration_flag', '')
    rerun_flag = h.get('rerun_flag', '')

    # LLM news intelligence
    intel          = h.get('news_intelligence', {})
    intel_status   = intel.get('_status', 'ok' if intel else 'no_data')  # 'ok' | 'no_data' | 'failed'
    intel_error    = intel.get('_error', '')
    intel_impact   = intel.get('thesis_impact', '')
    intel_reason   = intel.get('impact_reason', '')
    intel_insights = intel.get('key_insights', [])
    intel_watch    = intel.get('watch_flag', '')
    intel_summary  = intel.get('sentiment_summary', '')

    scenario  = h.get('scenario', {})
    tracking  = str(scenario.get('current_tracking','—')).upper()
    trk_note  = scenario.get('tracking_note','')
    bull_s    = scenario.get('bull', {})
    base_s    = scenario.get('base', {})
    bear_s    = scenario.get('bear', {})

    # Cross‑check
    cc        = h.get('cross_check','')
    edgar_ok  = h.get('edgar_available', False)

    # Formatting helpers
    price_str   = f'${cur_price:.2f}' if cur_price else '—'
    ret_str     = f'{ret_1yr:+.1f}% 1yr' if ret_1yr is not None else '—'
    ret_c       = '#15803d' if (ret_1yr or 0) >= 0 else '#dc2626'
    mkt_cap_str = f"${h.get('market_cap',0)/1e9:.1f}B" if h.get('market_cap') else '—'
    rev_str     = f"${(h.get('revenue',0) or 0)/1e6:.0f}M" if h.get('revenue') else '—'
    ks_str      = 'KiwiSaver' if ks else 'Sharesies'
    tier_c      = {'T1': '#15803d', 'T2': '#1d4ed8', 'T3': '#d97706'}.get(tier, '#6b7280')
    border_c    = tier_c
    trk_c       = {'BULL': '#15803d', 'BASE': '#d97706', 'BEAR': '#dc2626'}.get(tracking, '#6b7280')
    roic_c      = '#15803d' if (roic or 0) > 0.12 else ('#d97706' if (roic or 0) > 0.06 else '#374151')
    gm_c        = '#15803d' if (gm or 0) > 0.40 else ('#d97706' if (gm or 0) > 0.20 else '#374151')
    rg_c        = '#15803d' if (rev_gr or 0) > 0.10 else ('#d97706' if (rev_gr or 0) > 0 else '#dc2626')
    above_str   = (f'+{abs(pct_200ma or 0):.1f}% above 200MA' if above200
                   else f'{abs(pct_200ma or 0):.1f}% below 200MA' if above200 is not None else '—')
    above_c     = '#15803d' if above200 else ('#dc2626' if above200 is not None else '#6b7280')
    sect_c      = {'HIGH': '#15803d', 'MEDIUM': '#d97706', 'LOW': '#dc2626'}.get(sect_dur, '#6b7280')

    # ── SECTION LABEL ─────────────────────────────────────────────────────
    def _sec_label(label, note=''):
        note_html = (f'&nbsp;<span style="font-size:8px;font-weight:400;color:#d1d5db">{note}</span>'
                     if note else '')
        return (
            f'<div style="background:#f8f9fa;border-top:1px solid #eaecef;border-bottom:1px solid #eaecef;'
            f'padding:7px 14px;font-size:8px;font-weight:700;letter-spacing:.12em;'
            f'text-transform:uppercase;color:#9ca3af">{label}{note_html}</div>'
        )

    # ── STAT CELL (for fundamentals / technicals tables) ──────────────────
    def _stat(label, value, color='#111827', last=False, w='33%'):
        border = '' if last else 'border-right:1px solid #f0f2f5;'
        return (
            f'<td style="padding:8px 10px;width:{w};vertical-align:top;{border}">'
            f'<div style="font-size:8px;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px">{label}</div>'
            f'<div style="font-size:12px;font-weight:700;color:{color}">{value}</div>'
            f'</td>'
        )

    # ── SCENARIO CELL ─────────────────────────────────────────────────────
    def _scen_td(s, label, c_text, c_bg, c_bdr):
        if not s:
            return '<td style="width:33%"></td>'
        mult    = s.get('multiple', '—')
        prob    = s.get('probability', 0)
        cap     = max(s.get('mktcap_10yr_b', 0) or 0, 0)
        narr    = (s.get('narrative', '') or '')[:110]
        cap_str = f'${cap/1000:.1f}T' if cap >= 1000 else f'${cap:.0f}B'
        active  = (tracking == label.upper())
        brd     = f'border:2px solid {c_text}' if active else f'border:1px solid {c_bdr}'
        tick    = '&nbsp;&#10003;' if active else ''
        return (
            f'<td style="padding:3px;width:33%;vertical-align:top">'
            f'<div style="{brd};background:{c_bg};border-radius:3px;padding:9px 8px;text-align:center">'
            f'<div style="font-size:8px;font-weight:700;color:{c_text};letter-spacing:.06em;'
            f'text-transform:uppercase;margin-bottom:4px">{label} {float(prob)*100:.0f}%{tick}</div>'
            f'<div style="font-size:18px;font-weight:800;color:#111827;line-height:1">{mult}x</div>'
            f'<div style="font-size:11px;font-weight:600;color:#374151;margin-top:2px">{cap_str}</div>'
            f'<div style="font-size:8.5px;color:#6b7280;margin-top:5px;line-height:1.4">{narr}</div>'
            f'</div>'
            f'</td>'
        )

    # ── MARKET INTELLIGENCE BLOCK ──────────────────────────────────────────
    if intel_status == 'ok' and intel:
        ic, ibg, ibdr, ilbl = {
            'STRENGTHENS': ('#15803d', '#f0fdf4', '#bbf7d0', 'Strengthens 20-yr thesis'),
            'THREATENS':   ('#b91c1c', '#fef2f2', '#fecaca', 'Threatens 20-yr thesis'),
            'NEUTRAL':     ('#4b5563', '#f3f4f6', '#e5e7eb', 'Neutral to thesis'),
        }.get(intel_impact, ('#6b7280', '#f8f9fa', '#e5e7eb', 'Market intelligence'))

        insights_html = ''.join(
            f'<div style="font-size:10px;color:#1a1d23;padding:4px 0;border-bottom:1px solid {ibdr}">&bull; {ins}</div>'
            for ins in intel_insights[:3] if ins
        )
        watch_html = (f'<div style="font-size:9px;color:#b45309;font-weight:600;margin-top:6px">Watch: {intel_watch}</div>'
                      if intel_watch else '')
        intel_html = (
            f'<div style="border-left:4px solid {ic};background:{ibg};border-radius:2px;padding:10px 12px">'
            f'<div style="font-size:9px;font-weight:700;color:{ic};text-transform:uppercase;'
            f'letter-spacing:.08em;margin-bottom:6px">{ilbl}'
            f'{f" — {intel_reason}" if intel_reason else ""}</div>'
            f'{insights_html}'
            f'{watch_html}'
            f'</div>'
        )
    elif intel_status == 'failed':
        intel_html = (
            f'<div style="border-left:4px solid #dc2626;background:#fef2f2;border-radius:2px;padding:10px 12px">'
            f'<div style="font-size:9px;font-weight:700;color:#b91c1c;text-transform:uppercase;'
            f'letter-spacing:.08em;margin-bottom:4px">⚠ LLM analysis failed</div>'
            f'<div style="font-size:10px;color:#7f1d1d">{intel_error or "Unknown error — check screener.log"}</div>'
            f'</div>'
        )
    else:
        intel_html = f'<div style="font-size:10px;color:#9ca3af;font-style:italic">No recent news to analyze.</div>'

    # ── RAW NEWS (Finnhub + Reddit — counts & sentiment only, no AI) ───────
    _news_sent_c = {'POSITIVE': '#15803d', 'NEGATIVE': '#dc2626'}.get(str(news_sent).upper(), '#4b5563')
    news_raw_html = (
        f'<table width="100%" border="0" cellpadding="0" cellspacing="0"><tr>'
        + _stat('Finnhub articles', f'{news_n} &middot; <span style="color:{_news_sent_c}">{news_sent}</span>')
        + _stat('Reddit mentions', reddit_disp)
        + _stat('Signal / noise', signal, last=True)
        + f'</tr></table>'
    )

    # ── SEC / NEWS BLOCK (existing colour-coding logic, clean table) ───────
    _news_hl = h.get('news_highlights', [])
    if sec_highlights:
        _8k_c, _8k_bg, _8k_lbl = '#1d4ed8', '#f0f4ff', '#1d4ed8'
        _8k_hdr = (f'SEC 8-K &middot; {sec_8k} filing{"s" if sec_8k!=1 else ""}'
                   + (f' &middot; {sec_latest_date}' if sec_latest_date else ''))
        _8k_body = ''.join(
            f'<div style="font-size:10px;padding:4px 0;color:#1a1d23;border-bottom:1px solid #d1ddf5">&bull; {pt}</div>'
            for pt in sec_highlights if pt
        )
    elif sec_8k > 0:
        _8k_c, _8k_bg, _8k_lbl = '#d97706', '#fffbeb', '#92400e'
        _8k_hdr = (f'SEC 8-K &middot; {sec_8k} filing{"s" if sec_8k!=1 else ""}'
                   + (f' &middot; {sec_latest_date}' if sec_latest_date else ''))
        events_str = ', '.join(e.get('description', '') for e in sec_events[:2]) if sec_events else 'Filed — highlights pending'
        _8k_body = f'<div style="font-size:10px;color:#92400e;margin-top:4px">{events_str}</div>'
    elif _news_hl:
        _8k_c, _8k_bg, _8k_lbl = '#374151', '#f8f9fa', '#374151'
        _8k_hdr = 'Recent news highlights'
        _8k_body = ''.join(
            f'<div style="font-size:10px;padding:4px 0;color:#1a1d23;border-bottom:1px solid #e5e7eb">&bull; {pt}</div>'
            for pt in _news_hl if pt
        )
    else:
        _8k_c, _8k_bg, _8k_lbl = '#e5e7eb', '#fafafa', '#9ca3af'
        _8k_hdr = 'No recent SEC filings'
        _8k_body = '<div style="font-size:10px;color:#9ca3af">No material events in last 90 days</div>'

    sec_8k_html = (
        f'<div style="border-left:4px solid {_8k_c};background:{_8k_bg};border-radius:2px;padding:10px 12px">'
        f'<div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;'
        f'color:{_8k_lbl};margin-bottom:5px">{_8k_hdr}</div>'
        f'{_8k_body}</div>'
    )

    # ── 10-K HIGHLIGHTS ───────────────────────────────────────────────────
    ten_k_html = ''
    if ten_k_hl and any(ten_k_hl):
        bullets = ''.join(
            f'<div style="font-size:10.5px;color:#3a3a3a;padding:4px 0;border-bottom:1px solid #f0e4c0">&bull; {b}</div>'
            for b in ten_k_hl if b
        )
        ten_k_html = (
            f'<div style="margin-top:10px;padding:10px 12px;background:#fff8e8;border-left:4px solid #d4a020;border-radius:2px">'
            f'<div style="font-size:8px;font-weight:700;color:#b87a20;letter-spacing:.1em;'
            f'text-transform:uppercase;margin-bottom:6px">From the company\'s own 10-K filing</div>'
            f'{bullets}'
            f'</div>'
        )

    # ── CONGRESSIONAL TRADING (House + Senate, last 90 days) ───────────────
    congress_html = ''
    if congress_tx:
        rows = ''.join(
            f'<div style="font-size:10px;padding:4px 0;color:#1a1d23;border-bottom:1px solid #e0e7f5">'
            f'<strong>{tx.get("name","—")}</strong>'
            f'&nbsp;<span style="color:#6b7280">({tx.get("chamber","—")})</span>'
            f'&nbsp;<span style="color:{"#15803d" if tx.get("type")=="Purchase" else "#dc2626" if tx.get("type")=="Sale" else "#6b7280"}">{tx.get("type","—")}</span>'
            + (f'&nbsp;<span style="color:#6b7280">{tx.get("amount")}</span>' if tx.get('amount') else '')
            + f'&nbsp;<span style="color:#9ca3af">{tx.get("date","")}</span>'
            f'</div>'
            for tx in congress_tx[:5]
        )
        congress_html = (
            f'<div style="margin-top:10px;padding:10px 12px;background:#f5f3ff;border-left:4px solid #7c3aed;border-radius:2px">'
            f'<div style="font-size:8px;font-weight:700;color:#6d28d9;letter-spacing:.1em;'
            f'text-transform:uppercase;margin-bottom:6px">Congressional trading &middot; last 90 days</div>'
            f'{rows}'
            f'</div>'
        )

    # ── BUILD CARD ────────────────────────────────────────────────────────
    thesis_html = thesis if thesis else '<em style="color:#9ca3af">Thesis pending</em>'

    # Long-term rating header (firm-style). No 12-month price target — a 15-20yr
    # note points to the 10-year scenario instead. Conviction is driven by the
    # model's decade probability (odds the thesis actually plays out).
    _rc, _rbg, _rlbl = _rating_style(h.get('verdict'))
    if isinstance(decade_p, (int, float)):
        _conv = 'High' if decade_p >= 0.6 else ('Medium' if decade_p >= 0.4 else 'Low')
        _conv_s = f'Conviction: {_conv}'
    else:
        _conv_s = ''
    # Band the model's alpha estimate rather than print false-precision decimals.
    # It is a single free-model estimate, so a directional band is the honest unit.
    if isinstance(alpha_est, (int, float)):
        _ab = ('Ahead of QQQ' if alpha_est >= 2
               else 'Behind QQQ' if alpha_est <= -2
               else 'In line with QQQ')
        _alpha_s = f'Est. {_ab}'
    else:
        _alpha_s = ''
    _moat_s  = f'moat {moat_dur}+ yrs' if moat_dur else ''
    _meta    = ' &middot; '.join([s for s in (_conv_s, _alpha_s, _moat_s) if s])
    if _conv_s or _alpha_s:
        _meta += ' &middot; <span style="color:#9ca3af">model est.</span>'
    _call    = (thesis[:150] + '…') if (thesis and len(thesis) > 150) else (thesis or 'Thesis pending')
    rating_header = (
        f'<tr><td style="padding:0 14px 12px">'
        f'<div style="border:1px solid {_rc}33;background:{_rbg};border-radius:3px;padding:10px 12px">'
        f'<table width="100%" border="0" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="vertical-align:middle;white-space:nowrap">'
        f'<span style="background:{_rc};color:#fff;font-size:12px;font-weight:800;'
        f'letter-spacing:.04em;padding:4px 11px;border-radius:3px">{_rlbl}</span>'
        f'<span style="font-size:8px;color:#9ca3af;margin-left:8px;text-transform:uppercase;'
        f'letter-spacing:.08em">15-20yr stance</span></td>'
        f'<td style="vertical-align:middle;text-align:right;font-size:9.5px;color:#4b5563">{_meta or "&mdash;"}</td>'
        f'</tr></table>'
        f'<div style="font-size:10px;color:#4b5563;line-height:1.5;font-style:italic;margin-top:8px">'
        f'The call: {_call}</div>'
        f'</div>'
        f'</td></tr>'
    )

    # ── Advisory flags for held names: concentration drift + event re-research ──
    _adv_items = [x for x in (conc_flag, rerun_flag) if x]
    advisory_html = ''
    if _adv_items:
        _adv_rows = ''.join(
            f'<div style="font-size:10px;color:#92400e;margin-top:2px">&#9873; {a}</div>'
            for a in _adv_items)
        advisory_html = (
            f'<tr><td style="padding:0 14px 10px">'
            f'<div style="border:1px solid #fde68a;background:#fffbeb;border-radius:3px;padding:8px 12px">'
            f'<div style="font-size:8px;font-weight:800;letter-spacing:.08em;color:#b45309;'
            f'text-transform:uppercase">Portfolio action</div>{_adv_rows}</div></td></tr>'
        )

    # ── Valuation & multi-year integrity block ──
    _val_c = {'CHEAP':'#15803d','FAIR':'#4b5563','RICH':'#d97706','EXTREME':'#dc2626'}.get(val_label, '#4b5563')
    _ins_c = {'BUYING':'#15803d','SELLING':'#dc2626'}.get(ins_net, '#4b5563')
    _dil_c = {'SEVERE':'#dc2626','HIGH':'#dc2626','MODERATE':'#d97706'}.get(dil_traj, '#15803d')
    _eq3_c = ('#15803d' if eq3=='CLEAN' else '#d97706' if eq3=='WATCH'
              else '#dc2626' if eq3=='FLAG' else '#4b5563')
    _share5_s   = f' ({share5:+.0f}%/5yr)' if isinstance(share5, (int, float)) else ''
    _peg_s      = f' &middot; PEG {val_peg}' if isinstance(val_peg, (int, float)) else ''
    _val_note_s = f' &middot; <span style="color:#6b7280">{val_note}</span>' if val_note else ''
    _ins_note_s = f' &middot; <span style="color:#6b7280">{ins_note}</span>' if ins_note else ''
    _eq3_dir_s  = f' &middot; {eq3_dir}' if (eq3_dir and eq3_dir != '—') else ''
    _dq_band    = dq.get('band'); _dq_score = dq.get('score'); _dq_missing = dq.get('missing') or []
    _dq_c       = {'FULL':'#15803d','PARTIAL':'#d97706','THIN':'#dc2626'}.get(_dq_band, '#9ca3af')
    _dq_miss_s  = (' &middot; missing: ' + ', '.join(_dq_missing)) if _dq_missing else ''
    _dq_html    = (f'<div style="font-size:9.5px;color:{_dq_c};margin-top:8px">'
                   f'<strong>Evidence base: {_dq_band} ({_dq_score}%)</strong>{_dq_miss_s}</div>'
                   if (_dq_band and _dq_band != 'FULL') else '')
    # Congress (Senate) — only render when the feed worked; stay silent (honest) otherwise
    _cong_c = {'BUYING':'#15803d','SELLING':'#dc2626','MIXED':'#d97706'}.get(cong_sig, '#4b5563')
    _cong_txt = (f'{cong_sig.title()} &middot; {cong_buys} buy / {cong_sells} sell'
                 if cong_sig in ('BUYING','SELLING','MIXED')
                 else 'No trades in 120d' if cong_sig == 'NONE' else '')
    _cong_row = (f'<div><span style="color:#9ca3af">Congress (Senate 120d)</span> '
                 f'<strong style="color:{_cong_c}">{_cong_txt}</strong></div>'
                 if (cong_src == 'efd' and _cong_txt) else '')
    integrity_html = (
        f'<tr><td style="padding:0">{_sec_label("Valuation &amp; Integrity", "Growth-adjusted &middot; SEC EDGAR multi-year")}</td></tr>'
        f'<tr><td style="padding:10px 14px">'
        f'<div style="font-size:10px;color:#374151;line-height:1.8">'
        f'<div><span style="color:#9ca3af">Valuation</span> '
        f'<strong style="color:{_val_c}">{val_label}</strong>{_peg_s}{_val_note_s}</div>'
        f'<div><span style="color:#9ca3af">Insider (6m)</span> '
        f'<strong style="color:{_ins_c}">{ins_net}</strong>{_ins_note_s}</div>'
        f'<div><span style="color:#9ca3af">Dilution (filed, 5yr)</span> '
        f'<strong style="color:{_dil_c}">{dil_traj}</strong>{_share5_s}</div>'
        f'<div><span style="color:#9ca3af">Earnings quality (3yr)</span> '
        f'<strong style="color:{_eq3_c}">{eq3}</strong>{_eq3_dir_s}</div>'
        f'{_cong_row}'
        f'</div>'
        f'{_dq_html}'
        f'</td></tr>'
    )
    card = (
        f'<table id="{ticker}" width="100%" border="0" cellpadding="0" cellspacing="0" '
        f'style="margin-bottom:14px;border:1px solid #e5e7eb;border-left:4px solid {border_c};background:#fff">'

        # HEADER — ticker · company · price · return · mkt cap · revenue
        f'<tr><td style="padding:0">'
        f'<table width="100%" border="0" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="padding:14px 14px 12px;vertical-align:top">'
        f'<span style="font-size:9px;font-weight:700;color:{tier_c};letter-spacing:.06em">{tier}</span>'
        f'&nbsp;&nbsp;<strong style="font-size:22px;color:#111827;letter-spacing:-.02em">{ticker}</strong>'
        f'&nbsp;<span style="font-size:9px;background:#f3f4f6;color:#6b7280;padding:2px 6px;border-radius:2px;vertical-align:middle">{ks_str}</span>'
        f'<div style="font-size:11px;color:#6b7280;margin-top:3px">{company}</div>'
        f'<div style="font-size:9px;color:#adb5bd;margin-top:3px">'
        f'Added {date_added} &nbsp;&middot;&nbsp; {round(pos,1)}% portfolio'
        f'{f" &middot; {mt_lbl} {mt_score}/10" if mt_lbl and mt_score >= 6 else ""}'
        f'</div>'
        f'</td>'
        f'<td style="padding:14px 14px 12px;text-align:right;vertical-align:top;white-space:nowrap">'
        f'<div style="font-size:22px;font-weight:800;color:#111827;letter-spacing:-.02em">{price_str}</div>'
        f'<div style="font-size:12px;font-weight:700;color:{ret_c};margin-top:3px">{ret_str}</div>'
        f'<div style="font-size:9px;color:#9ca3af;margin-top:4px">Mkt Cap: {mkt_cap_str}</div>'
        f'<div style="font-size:9px;color:#9ca3af;margin-top:2px">Revenue: {rev_str}</div>'
        f'</td>'
        f'</tr></table>'
        f'</td></tr>'

        + rating_header
        + advisory_html

        # INVESTMENT THESIS
        + f'<tr><td style="padding:0">{_sec_label("Investment Thesis", "20-year view")}</td></tr>'
        f'<tr><td style="padding:12px 14px 10px">'
        f'<div style="font-size:11px;color:#1a1d23;line-height:1.65">'
        f'{thesis_html}'
        f'</div>'
        + (f'<table width="100%" border="0" cellpadding="0" cellspacing="0" style="margin-top:10px"><tr>'
           f'<td style="font-size:9.5px;color:#6b7280;padding-right:10px">Moat: <strong style="color:#374151">{moat_type}</strong></td>'
           f'<td style="font-size:9.5px;color:#6b7280;padding-right:10px">{moat_dur} yrs durable</td>'
           f'<td style="font-size:9.5px;color:#6b7280;padding-right:10px">Mgmt: <strong style="color:#374151">{mgmt_gr}</strong></td>'
           f'<td style="font-size:9.5px;color:#6b7280">Runway: <strong style="color:#374151">{runway_yr} yrs</strong></td>'
           f'</tr></table>'
           if moat_type else '')
        + (f'<div style="font-size:9.5px;color:#6b7280;margin-top:6px">'
           f'<span style="color:{sect_c};font-weight:700">Sector 20yr: {sect_dur}</span>'
           f'{f" &middot; {sect_note}" if sect_note else ""}'
           f'</div>' if sect_dur else '')
        + (f'<div style="font-size:9.5px;color:#374151;margin-top:6px">'
           f'<strong>Primary risk:</strong> {risk}</div>' if risk else '')
        + ten_k_html
        + congress_html
        + (f'<div style="font-size:9.5px;color:#b91c1c;border-left:3px solid #fecaca;padding:5px 10px;'
           f'margin-top:8px;background:#fef2f2"><strong>Exit if:</strong> {breaks_if}</div>'
           if breaks_if else '')
        + f'</td></tr>'

        # 10-YEAR SCENARIO TRACKING
        + (f'<tr><td style="padding:0">{_sec_label("10-Year Scenario", f"Currently tracking: {tracking}")}</td></tr>'
           f'<tr><td style="padding:10px 14px">'
           + (f'<div style="font-size:10px;color:#374151;line-height:1.5;margin-bottom:10px;'
              f'border-left:3px solid {trk_c};padding-left:10px">{trk_note}</div>' if trk_note else '')
           + f'<table width="100%" border="0" cellpadding="0" cellspacing="0"><tr>'
           f'{_scen_td(bull_s,"Bull","#15803d","#f0fdf4","#bbf7d0")}'
           f'{_scen_td(base_s,"Base","#4b5563","#f8f9fa","#e5e7eb")}'
           f'{_scen_td(bear_s,"Bear","#b91c1c","#fef2f2","#fecaca")}'
           f'</tr></table>'
           f'</td></tr>'
           if (bull_s or base_s or bear_s) else '')

        # FUNDAMENTALS (all 12 metrics)
        + f'<tr><td style="padding:0">{_sec_label("Fundamentals", "Yahoo Finance · SEC EDGAR")}</td></tr>'
        f'<tr><td style="padding:10px 14px">'
        f'<table width="100%" border="0" cellpadding="0" cellspacing="0">'
        f'<tr style="border-bottom:1px solid #f0f2f5">'
        + _stat('ROIC', _pct(roic), roic_c)
        + _stat('Gross Margin', _pct(gm), gm_c)
        + _stat('Rev Growth', _pct(rev_gr), rg_c, last=True)
        + f'</tr><tr style="border-bottom:1px solid #f0f2f5">'
        + _stat('FCF Yield', _val(fcf_yield,'pct1') if fcf_yield else '—')
        + _stat('Net Cash', f'{_money(net_cash)} {net_flag}', '#15803d' if (net_cash or 0) > 0 else '#374151')
        + _stat('D/E Ratio', _val(de,'x') if de else '—', last=True)
        + f'</tr><tr>'
        + _stat('Earn. Quality', eq, '#15803d' if eq=='CLEAN' else '#d97706' if eq=='WATCH' else '#374151')
        + _stat('Dilution', _pct(dilution), '#dc2626' if (dilution or 0) > 0.15 else '#374151')
        + _stat('Insider Own.', _pct(insider), last=True)
        + f'</tr></table>'
        f'</td></tr>'

        + integrity_html

        # TRACK RECORD (10yr) — long-term compounding, what matters most
        + f'<tr><td style="padding:0">{_sec_label("Track Record", "Compounding vs QQQ &middot; 10-15yr lens")}</td></tr>'
        f'<tr><td style="padding:10px 14px">'
        f'<table width="100%" border="0" cellpadding="0" cellspacing="0"><tr>'
        + _stat('3yr CAGR', _pct2(cagr3) if cagr3 is not None else '—')
        + _stat('5yr CAGR', _pct2(cagr5) if cagr5 is not None else '—')
        + _stat('10yr CAGR', _pct2(cagr10) if cagr10 is not None else '—')
        + _stat('Max Drawdown', _pct2(max_dd) if max_dd is not None else '—', '#dc2626', last=True)
        + f'</tr></table>'
        + (f'<div style="font-size:9.5px;margin-top:6px;font-weight:700;color:{"#15803d" if (lt_alpha or 0)>=0 else "#dc2626"}">vs QQQ: {lt_alpha:+}pp/yr long-term</div>' if lt_alpha is not None else '')
        + (f'<div style="font-size:9.5px;color:#b45309;border-left:3px solid #fde68a;padding:5px 10px;margin-top:6px;background:#fffbeb"><strong>Downgraded:</strong> {lt_note}</div>' if lt_note else '')
        + (f'<div style="font-size:9.5px;color:#b45309;border-left:3px solid #fde68a;padding:5px 10px;margin-top:6px;background:#fffbeb"><strong>Downgraded (sector):</strong> {sect_risk}</div>' if sect_risk else '')
        + f'</td></tr>'

        # TECHNICAL POSITION
        + f'<tr><td style="padding:0">{_sec_label("Technical Position", "background only")}</td></tr>'
        f'<tr><td style="padding:10px 14px">'
        f'<table width="100%" border="0" cellpadding="0" cellspacing="0"><tr>'
        + _stat('200-Day MA', above_str, above_c)
        + _stat('52w High', f'{_val(pct_high,"pct1") if pct_high else "—"} from high')
        + _stat('QQQ vs Stock (12 months)',
                (f'QQQ {qqq_ret:+.0f}% <span style="font-weight:400;color:#9ca3af">||</span> Stock {ret_1yr:+.0f}%'
                 if (ret_1yr is not None and qqq_ret is not None) else '—'),
                '#15803d' if (vs_qqq or 0) >= 0 else '#dc2626', last=True)
        + f'</tr></table>'
        f'</td></tr>'

        # NEWS — raw Finnhub + Reddit (no AI)
        + f'<tr><td style="padding:0">{_sec_label("News", f"Raw feed &middot; Finnhub + Reddit &middot; 30 days")}</td></tr>'
        f'<tr><td style="padding:10px 14px">{news_raw_html}</td></tr>'

        # AI INSIGHTS — the model's read of the news above
        + f'<tr><td style="padding:0">{_sec_label("AI insights &middot; news", "LLM&#39;s read of the news above &middot; paraphrased, not verbatim")}</td></tr>'
        f'<tr><td style="padding:10px 14px">{intel_html}</td></tr>'

        # 8-K FILING INSIGHTS
        + f'<tr><td style="padding:0">{_sec_label("AI insights &middot; 8-K filings", "LLM-extracted from the SEC 8-K filing text &middot; EDGAR")}</td></tr>'
        f'<tr><td style="padding:10px 14px 14px">{sec_8k_html}</td></tr>'

        + f'</table>'
    )
    return card

    def _src(tag):
        return f'<span style="font-size:7px;color:#9aa0a6;margin-left:2px">{tag}</span>'

    # Helper for scenario cells
    def _scen_cell(s, label, css):
        if not s:
            return ''
        mult = s.get('multiple','—')
        prob = s.get('probability', 0)
        cap  = s.get('mktcap_10yr_b', 0) or 0
        if cap < 0:
            cap = 0
        narr = (s.get('narrative','') or '')[:120]
        cap_str = f'${cap/1000:.1f}T' if cap >= 1000 else f'${cap:.0f}B'
        _sc = {'scen-bull':('#15803d','#f0fdf4','#bbf7d0'),
               'scen-base':('#4b5563','#f8f9fa','#e5e7eb'),
               'scen-bear':('#b91c1c','#fef2f2','#fecaca')}.get(css,('#4b5563','#f8f9fa','#e5e7eb'))
        return (f'<div style="flex:1;min-width:110px;border:1px solid {_sc[2]};background:{_sc[1]};'
                f'padding:9px;border-radius:2px;text-align:center;font-size:10px">'
                f'<div style="font-size:8px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;'
                f'color:{_sc[0]};margin-bottom:4px">{label} &middot; {float(prob)*100:.0f}%</div>'
                f'<div style="font-size:18px;font-weight:800;color:#111827;letter-spacing:-.02em">{mult}x</div>'
                f'<div style="font-size:11px;color:#374151;font-weight:600">{cap_str}</div>'
                f'<div style="color:#6b7280;font-size:9px;margin-top:3px;line-height:1.4">{narr}</div>'
                f'</div>')

    # Thesis line
    thesis_html = f'<div style="font-size:12px; color:#1a3a1a; line-height:1.5; margin-bottom:6px">{thesis}</div>' if thesis else '<div style="color:#a0a0a0; font-style:italic">Thesis pending</div>'

    # 10‑K highlights – PROMINENT block, gold background, gavel icon, placed right after thesis
    if ten_k_hl and any(ten_k_hl):
        ten_k_block = f'''<div style="margin:12px 0 8px; padding:10px 12px; background:#fff8e8; border-left:4px solid #d4a020; border-radius:2px;">
          <div style="font-size:9px; font-weight:700; letter-spacing:0.1em; color:#b87a20; margin-bottom:6px">⚖️ From the company's own 10‑K filing</div>
          <ul style="margin:0 0 0 18px; padding:0; font-size:10.5px; color:#3a3a3a; line-height:1.5;">
            {"".join(f'<li style="margin-bottom:4px">{b}</li>' for b in ten_k_hl if b)}
          </ul>
        </div>'''
    else:
        ten_k_block = ''

    # Moat / thesis details
    if moat_type:
        moat_block = f'''<div style="font-size:10px; color:#2a4a2a; margin-bottom:6px">
            <span>Moat: <strong>{moat_type}</strong></span> &middot; <span>Durability: <strong>{moat_dur} yrs</strong></span> &middot; <span>Mgmt: <strong>{mgmt_gr}</strong></span> &middot; <span>Runway: <strong>{runway_yr} yrs</strong></span>
      {f'&middot; <span>Decade prob: <strong>{float(decade_p)*100:.0f}%</strong></span>' if decade_p else ''}
      {f'&middot; <span>Est. alpha: <strong>+{float(alpha_est):.0f}%/yr</strong></span>' if alpha_est else ''}
    </div>'''
    else:
        moat_block = ''

    # Scenarios
    if bull_s or base_s or bear_s:
        scenario_block = f'''<div style="padding:10px 16px">
    <div style="font-size:9px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:#9ca3af;margin-bottom:8px">AI Scenario Estimates &nbsp;<span style="font-weight:400;color:#d1d5db">10yr indicative — grounded to current mktcap</span></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      {_scen_cell(bull_s,'Bull','scen-bull')}
      {_scen_cell(base_s,'Base','scen-base')}
      {_scen_cell(bear_s,'Bear','scen-bear')}
    </div>
    <div style="font-size:10px;color:#374151;margin-top:8px">
      Tracking: <strong class="{trk_cls}">{tracking}</strong>
      {f'&nbsp;&mdash;&nbsp;<span style="color:#6b7280">{trk_note}</span>' if trk_note else ''}
    </div>
  </div>'''
    else:
        scenario_block = ''

    # Pre-compute SEC 8-K / news block with clean, non-alarming colours
    _news_hl = h.get('news_highlights', [])
    if sec_highlights:
        _8k_border, _8k_bg, _8k_lbl_color = '#1d4ed8', 'background:#f0f4ff;', '#1d4ed8'
        _8k_header = (f'SEC 8-K &nbsp;&middot;&nbsp; {sec_8k} filing{"s" if sec_8k!=1 else ""}'
                      + (f' &nbsp;&middot;&nbsp; {sec_latest_date}' if sec_latest_date else ''))
        _8k_body = ('<div style="margin-top:5px">'
                    + ''.join(f'<div style="font-size:11px;padding:3px 0;color:#1a1d23;'
                              f'border-bottom:1px solid #e0e7f3">&bull; {pt}</div>'
                              for pt in sec_highlights if pt)
                    + '</div>')
    elif sec_8k > 0:
        _8k_border, _8k_bg, _8k_lbl_color = '#d97706', 'background:#fffbeb;', '#92400e'
        _8k_header = (f'SEC 8-K &nbsp;&middot;&nbsp; {sec_8k} filing{"s" if sec_8k!=1 else ""}'
                      + (f' &nbsp;&middot;&nbsp; {sec_latest_date}' if sec_latest_date else ''))
        events_str = ', '.join(e.get('description', '') for e in sec_events[:2]) if sec_events else 'Filed — highlights pending'
        _8k_body = f'<div style="font-size:10px;color:#92400e;margin-top:4px">{events_str}</div>'
    elif _news_hl:
        _8k_border, _8k_bg, _8k_lbl_color = '#374151', 'background:#f8f9fa;', '#374151'
        _8k_header = 'Recent news highlights'
        _8k_body = ('<div style="margin-top:5px">'
                    + ''.join(f'<div style="font-size:11px;padding:3px 0;color:#1a1d23;'
                              f'border-bottom:1px solid #e5e7eb">&bull; {pt}</div>'
                              for pt in _news_hl if pt)
                    + '</div>')
    else:
        _8k_border, _8k_bg, _8k_lbl_color = '#e5e7eb', '', '#9ca3af'
        _8k_header = 'SEC 8-K &nbsp;&middot;&nbsp; No recent filings'
        _8k_body = '<div style="font-size:10px;color:#9ca3af;margin-top:3px">No material events in last 90 days</div>'

    sec_8k_html = (f'<div style="border-left:3px solid {_8k_border};padding:8px 11px;'
                   f'{_8k_bg}border-radius:2px">'
                   f'<div style="font-size:9px;font-weight:700;letter-spacing:.08em;'
                   f'text-transform:uppercase;color:{_8k_lbl_color}">{_8k_header}</div>'
                   f'{_8k_body}</div>')

    # Tier left-border colour
    _tier_border = {'T1': '#15803d', 'T2': '#1d4ed8', 'T3': '#c2410c'}.get(tier, '#6b7280')

    # Build card string
    card = f'''
<div class="rcard" id="{ticker}" style="margin-bottom:20px;border:1px solid #e5e7eb;border-left:3px solid {_tier_border};border-radius:2px;overflow:hidden;background:#fff">
  <!-- HEADER -->
  <div style="padding:14px 16px;background:#fafbfc;border-bottom:1px solid #eaecef;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px">
    <div>
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;flex-wrap:wrap">
        <span style="font-size:22px;font-weight:800;color:#111827;letter-spacing:-.02em;line-height:1">{ticker}</span>
        {_t(tier)}
        <span style="font-size:8px;color:#9ca3af;background:#f3f4f6;padding:2px 6px;border-radius:2px">{ks_str}</span>
      </div>
      <div style="font-size:11px;color:#6b7280;margin-bottom:4px">{company}</div>
      <div style="font-size:10px;color:#374151">
        {price_str} &nbsp;<span class="{ret_cls}" style="font-weight:600">{ret_str}</span>
        &nbsp;&middot;&nbsp;{round(pos,1)}% portfolio &nbsp;&middot;&nbsp;Added {date_added}
      </div>
    </div>
    <div style="text-align:right">
      <div style="font-size:8px;color:#9ca3af;letter-spacing:.1em;text-transform:uppercase">Mkt Cap</div>
      <div style="font-size:14px;font-weight:700;color:#111827">{mkt_cap_str}</div>
      <div style="font-size:8px;color:#9ca3af;letter-spacing:.1em;text-transform:uppercase;margin-top:4px">Revenue</div>
      <div style="font-size:14px;font-weight:700;color:#111827">{rev_str}</div>
    </div>
  </div>

  <!-- Megatrend tag -->
  {f'<div style="padding:6px 16px;border-bottom:1px solid #f3f4f6">{_mt_tag(mt_lbl, mt_score)}</div>' if mt_lbl and mt_score >= 6 else ''}

  <!-- HARD DATA -->
  <div style="padding:12px 16px;border-bottom:1px solid #f3f4f6">
    <div style="font-size:9px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:#9ca3af;margin-bottom:8px">
      Fundamentals &nbsp;<span style="font-weight:400;color:#d1d5db">Yahoo Finance &middot; SEC EDGAR</span>
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;font-size:10.5px">
      <div><span style="color:#9ca3af">ROIC</span> <strong style="color:#111827">{_pct(roic)}</strong>{_src('Y')}</div>
      <div><span style="color:#9ca3af">Gross Margin</span> <strong style="color:#111827">{_pct(gm)}</strong>{_src('Y')}</div>
      <div><span style="color:#9ca3af">Rev Growth</span> <strong style="color:#111827">{_pct(rev_gr)}</strong>{_src('Y')}</div>
      <div><span style="color:#9ca3af">Earn. Quality</span> <strong style="color:#111827">{eq}</strong>{_src('Y')}</div>
      <div><span style="color:#9ca3af">FCF Yield</span> <strong style="color:#111827">{_val(fcf_yield,'pct1') if fcf_yield else '—'}</strong></div>
      <div><span style="color:#9ca3af">Net Cash</span> <strong style="color:#111827">{_money(net_cash)} {net_flag}</strong>{_src('Y')}</div>
      <div><span style="color:#9ca3af">D/E</span> <strong style="color:#111827">{_val(de,'x') if de else '—'}</strong>{_src('Y')}</div>
      <div><span style="color:#9ca3af">Int. Coverage</span> <strong style="color:#111827">{_val(cov,'x') if cov else '—'}</strong></div>
      <div><span style="color:#9ca3af">Dilution</span> <strong style="color:#111827">{_pct(dilution)}</strong>{_src('Y')}</div>
      <div><span style="color:#9ca3af">Insider Own.</span> <strong style="color:#111827">{_pct(insider)}</strong>{_src('Y')}</div>
      <div><span style="color:#9ca3af">R&D Int.</span> <strong style="color:#111827">{rd_int:.1f}%</strong></div>
      <div><span style="color:#9ca3af">Moat Proxy</span> <strong style="color:#111827">{moat_prx}</strong></div>
    </div>
    {f'<div style="font-size:9px;color:#{"15803d" if cc=="CLEAN" else "b45309"};margin-top:6px">{"✓ Cross-checked with SEC filings" if cc=="CLEAN" else "⚠ Some metrics differ from SEC filings" if edgar_ok else ""}</div>' if cc or edgar_ok else ''}
  </div>

  <!-- TECHNICALS -->
  <div style="padding:10px 16px;border-bottom:1px solid #f3f4f6">
    <div style="font-size:9px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:#9ca3af;margin-bottom:8px">Technical position</div>
    <div style="display:flex;flex-wrap:wrap;gap:16px;font-size:10px">
      <div><span style="color:#9ca3af">200MA</span>&nbsp;<strong class="{above_cls}">{above_str}</strong></div>
      <div><span style="color:#9ca3af">vs QQQ</span>&nbsp;<strong>{_pct2(vs_qqq)}</strong></div>
      <div><span style="color:#9ca3af">Trend</span>&nbsp;<strong>{trend}</strong></div>
      <div><span style="color:#9ca3af">52w High</span>&nbsp;<strong>{_val(pct_high,'pct1') if pct_high else '—'}</strong></div>
    </div>
  </div>

  <!-- MARKET INTELLIGENCE (LLM) -->
  <div style="padding:10px 16px;border-bottom:1px solid #f3f4f6">
    <div style="font-size:9px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:#9ca3af;margin-bottom:8px">
      Market intelligence &nbsp;<span style="font-weight:400;color:#d1d5db">{news_n} news &middot; {reddit_n} community posts &middot; 30 days</span>
    </div>

    {(lambda ic, ibg, ibdr, ilbl: f"""<div style="border:1px solid {ibdr};border-left:3px solid {ic};background:{ibg};border-radius:2px;padding:9px 11px;margin-bottom:8px">
      <div style="font-size:8px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:{ic};margin-bottom:5px">{ilbl}{(" — " + intel_reason) if intel_reason else ""}</div>
      {"".join(f'<div style="font-size:9.5px;color:#1a1d23;padding:2px 0;border-bottom:1px solid {ibdr}">&bull; {ins}</div>' for ins in intel_insights[:3] if ins)}
      {f'<div style="font-size:8.5px;color:#b45309;margin-top:5px"><strong>Watch:</strong> {intel_watch}</div>' if intel_watch else ""}
      {f'<div style="font-size:9px;color:#6b7280;margin-top:4px;font-style:italic">{intel_summary}</div>' if intel_summary else ""}
    </div>""")(
        *{
            'STRENGTHENS': ('#15803d', '#f0fdf4', '#bbf7d0', 'Strengthens 20-yr thesis'),
            'THREATENS':   ('#b91c1c', '#fef2f2', '#fecaca', 'Threatens 20-yr thesis'),
            'NEUTRAL':     ('#4b5563', '#f3f4f6', '#e5e7eb', 'Neutral to 20-yr thesis'),
        }.get(intel_impact, ('#6b7280', '#f8f9fa', '#e5e7eb', 'News &amp; community sentiment'))
    ) if intel else f"""<div style="font-size:10px;color:#374151;padding:6px 0">{f'<strong>Signal:</strong> {sent_note}' if sent_note else 'No material thesis impact detected.'}&nbsp;{_sent_badge(news_sent) if news_n else ""}&nbsp;{_sig_badge(signal)}</div>"""}

    <!-- SEC 8-K / News -->
    {sec_8k_html}
  </div>

  <!-- RESEARCH & 10‑K -->
  <div style="padding:12px 16px;border-bottom:1px solid #f3f4f6">
    <div style="font-size:9px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:#9ca3af;margin-bottom:8px">Investment thesis &nbsp;<span style="font-weight:400;color:#d1d5db">NVIDIA Llama &middot; 20-year view</span></div>
    {thesis_html}
    {ten_k_block}
    {moat_block}
    {f"""<div style="font-size:9px;color:#6b7280;margin-bottom:4px">
      {'<span style="color:' + {"HIGH":"#15803d","MEDIUM":"#d97706","LOW":"#b91c1c"}.get(sect_dur,"#6b7280") + ';font-weight:700">20yr sector: ' + sect_dur + '</span>' if sect_dur else ''}
      {(' &middot; ' + sect_note) if sect_note else ''}
    </div>""" if sect_dur else ''}
    {f'<div style="font-size:10px;color:#4b5563;margin-bottom:4px"><strong>Primary risk:</strong> {risk}</div>' if risk else ''}
    {f'<div style="font-size:10px;color:#b91c1c;border-left:2px solid #fecaca;padding-left:7px;margin-top:4px"><strong>Exit if:</strong> {breaks_if}</div>' if breaks_if else ''}
  </div>

  <!-- SCENARIOS -->
  {scenario_block}
</div>'''
    return card


def _screened_card(s: dict) -> str:
    """Research card for screened-but-not-researched candidates."""
    ticker  = s.get('ticker','')
    company = s.get('company_name', ticker)
    tier    = s.get('tier','T3')
    reason  = s.get('reason','')
    mt_lbl  = s.get('megatrend_label','')
    mt_score= s.get('megatrend_score',0) or 0
    mt_yrs  = s.get('tailwind_years',0) or 0

    # Fundamentals
    roic    = s.get('roic')
    gm      = s.get('gross_margin')
    rev_gr  = s.get('rev_growth')
    eq      = s.get('earnings_quality','—')
    eq_cls  = {'CLEAN':'flag-clean','WATCH':'flag-watch','FLAG':'flag-flag'}.get(eq,'neu')
    fcf_y   = s.get('fcf_yield')
    net_cash= s.get('net_cash_m')
    net_flag= s.get('net_cash_flag','—')
    de      = s.get('de_ratio')
    insider = s.get('insider_pct')
    ins_sig = s.get('insider_signal','—')
    dilution= s.get('dilution_rate')
    moat_p  = s.get('moat_proxy_label','—')
    pp      = s.get('pricing_power','—')
    reinv   = s.get('reinvestment_rate')
    recur   = s.get('recurring_revenue_proxy','—')
    val_lbl = s.get('valuation_label','—')
    val_peg = s.get('val_peg')
    _val_cls = {'CHEAP':'pos','FAIR':'neu','RICH':'neg','EXTREME':'neg'}.get(val_lbl,'neu')
    _val_peg_s = f' &middot; PEG {val_peg}' if isinstance(val_peg,(int,float)) else ''
    _ins_cls = {'BUYING':'pos','SELLING':'neg'}.get(ins_sig,'neu')
    # Congress (Senate eFD)
    cong_src  = s.get('congress_source','unavailable')
    cong_sig  = s.get('congress_signal','UNAVAILABLE')
    cong_buys = s.get('congress_buys', 0) or 0
    cong_sells= s.get('congress_sells', 0) or 0
    _cong_cls = {'BUYING':'pos','SELLING':'neg','MIXED':'neu'}.get(cong_sig,'neu')
    if cong_src != 'efd':
        _cong_disp = 'unavailable'
    elif cong_sig in ('BUYING','SELLING','MIXED'):
        _cong_disp = f'{cong_sig.title()} · {cong_buys} buy / {cong_sells} sell'
    else:
        _cong_disp = 'no trades (120d)'

    # Technicals
    above200= s.get('above_200ma')
    pct_high= s.get('pct_from_high')
    pct_200ma = s.get('pct_from_200ma')
    ret_1yr = s.get('return_1yr')
    vs_qqq  = s.get('return_vs_qqq')
    qqq_ret = (ret_1yr - vs_qqq) if (ret_1yr is not None and vs_qqq is not None) else None

    # Sentiment
    news_n  = s.get('news_count', 0) or 0
    news_s  = s.get('news_sentiment','NEUTRAL')
    reddit_n= s.get('reddit_mentions', 0) or 0
    reddit_src = s.get('reddit_source','')
    sec_8k  = s.get('sec_8k_count',0) or 0
    signal  = s.get('signal_or_noise','NOISE')
    themes  = s.get('key_themes',[])

    above_str = (f'✓ +{abs(pct_200ma or 0):.1f}% above' if above200
                 else f'✗ {abs(pct_200ma or 0):.1f}% below' if above200 is not None
                 else '—')
    above_cls = 'pos' if above200 else ('neg' if above200 is not None else 'neu')
    themes_str= ', '.join(themes) if themes else '—'

    # EDGAR 5-year trajectory fields
    def _tr_fmt(trend, change=None):
        if not trend or trend == 'INSUFFICIENT':
            return '—', 'neu'
        cls = 'pos' if trend == 'RISING' else 'neg' if trend == 'FALLING' else 'neu'
        suffix = f' ({change:+.0f}%)' if change is not None else ''
        return f'{trend.title()}{suffix}', cls

    edgar_ok    = s.get('edgar_available', False)
    rev_tr,  rev_tr_cls  = _tr_fmt(s.get('revenue_trend'), s.get('revenue_5yr_change'))
    roic_tr, roic_tr_cls = _tr_fmt(s.get('roic_trend'), s.get('roic_5yr_change'))
    gm_tr,   gm_tr_cls    = _tr_fmt(s.get('gross_margin_trend'))
    dil_flag    = s.get('dilution_trajectory', 'NONE') or 'NONE'
    share_chg   = s.get('share_5yr_change')
    dil_detail  = f' ({share_chg:+.0f}% shares)' if share_chg is not None else ''
    dil_tr      = dil_flag.title() + dil_detail
    dil_tr_cls  = 'neg' if dil_flag in ('SEVERE','HIGH') else 'neu' if dil_flag == 'MODERATE' else 'pos'
    cross_chk   = s.get('cross_check', '')
    cc_badge    = ''
    if cross_chk == 'FLAGGED':
        cc_badge = ' <span class="sv sv-neg">Yahoo/EDGAR mismatch</span>'
    elif cross_chk == 'CLEAN':
        cc_badge = ' <span class="sv sv-pos">cross-checked</span>'
    edgar_status = (f"{s.get('years_of_data','?')} years of SEC-filed data{cc_badge}"
                    if edgar_ok else "No EDGAR data (foreign listing, ETF, or recent IPO)")

    card = f"""
<div class="rcard" style="border-left-color:#d4a020">
  <div class="rc-head">
    <div class="rc-left">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
        <span class="rc-ticker">{ticker}</span>
        &nbsp;{_t(tier)}
      </div>
      <div class="rc-company">{company}</div>
    </div>
    <div class="rc-right">
      <div class="rc-tier">Gate: {reason[:50]}</div>
      <div class="rc-status" style="color:#b87a20">Research pending — automatic generation in progress</div>
    </div>
  </div>
  <div class="rc-body">
"""
    if mt_lbl and mt_score >= 6:
        card += f'    {_mt_tag(mt_lbl, mt_score)}\n'

    card += f"""
    <table class="dtable"><caption>Fundamental Snapshot · Yahoo Finance</caption>
      <tr>
        <td class="k">ROIC</td><td class="{_cls(roic,0.15,0.08)}">{_pct(roic)}</td>
        <td class="k">Gross margin</td><td class="{_cls(gm,0.35,0.15)}">{_pct(gm)}</td>
      </tr>
      <tr>
        <td class="k">Revenue growth</td><td class="{_cls(rev_gr,0.10,-0.05)}">{_pct(rev_gr)}</td>
        <td class="k">FCF yield</td><td>{_val(fcf_y,'pct1') if fcf_y else '—'}</td>
      </tr>
      <tr>
        <td class="k">Reinvestment rate</td><td>{_val(reinv,'pct1') if reinv else '—'}</td>
        <td class="k">Recurring rev</td><td>{recur}</td>
      </tr>
      <tr>
        <td class="k">Earnings quality</td><td class="{eq_cls}">{eq}</td>
        <td class="k">Net cash</td><td class="{'pos' if (net_cash or 0)>0 else 'neg'}">{_money(net_cash)} ({net_flag})</td>
      </tr>
      <tr>
        <td class="k">D/E ratio</td><td>{_val(de,'x') if de else '—'}</td>
        <td class="k">Moat proxy</td><td>{moat_p}</td>
      </tr>
      <tr>
        <td class="k">Insider ownership</td><td>{_pct(insider)}</td>
        <td class="k">Dilution rate</td><td class="{'neg' if (dilution or 0)>0.15 else 'neu'}">{_pct(dilution)}</td>
      </tr>
      <tr>
        <td class="k">Valuation</td><td class="{_val_cls}">{val_lbl}{_val_peg_s}</td>
        <td class="k">Insider (6m)</td><td class="{_ins_cls}">{ins_sig}</td>
      </tr>
    </table>

    <table class="dtable"><caption>Technical Position</caption>
      <tr>
        <td class="k">200-day MA</td><td class="{above_cls}">{above_str}</td>
        <td class="k">1yr return</td><td class="{_cls(ret_1yr,0,-20) if ret_1yr else 'neu'}">{_pct2(ret_1yr)}</td>
      </tr>
      <tr>
        <td class="k">QQQ 1yr</td><td class="neu">{_pct2(qqq_ret)}</td>
        <td class="k">Trend</td><td>{s.get('trend','—')}</td>
      </tr>
    </table>

    <table class="dtable"><caption>5-Year Trajectory · SEC EDGAR Filed Data</caption>
      <tr>
        <td class="k">Revenue trend</td><td class="{rev_tr_cls}">{rev_tr}</td>
        <td class="k">ROIC trend</td><td class="{roic_tr_cls}">{roic_tr}</td>
      </tr>
      <tr>
        <td class="k">Gross margin trend</td><td class="{gm_tr_cls}">{gm_tr}</td>
        <td class="k">Dilution (5yr)</td><td class="{dil_tr_cls}">{dil_tr}</td>
      </tr>
      <tr><td colspan="4" style="color:#8a8a8a;font-size:10px">{edgar_status}</td></tr>
    </table>

    <table class="dtable"><caption>Sentiment · 30 Days</caption>
      <tr>
        <td class="k">Finnhub news</td><td>{_sent_badge(news_s)}</td><td style="color:#6a6a6a">{news_n} articles</td>
      </tr>
      <tr>
        <td class="k">Reddit</td><td></td><td style="color:#6a6a6a">{'unavailable' if reddit_src == 'blocked' else f'{reddit_n} mentions'}</td>
      </tr>
      <tr>
        <td class="k">Congress (Senate)</td><td class="{_cong_cls}"></td><td style="color:#6a6a6a">{_cong_disp}</td>
      </tr>
      <tr>
        <td class="k">SEC 8-K</td>
        <td class="{'neg' if sec_8k>0 else 'neu'}">{'MATERIAL EVENT' if sec_8k>0 else 'NONE'}</td>
        <td>{_sig_badge(signal)}</td>
      </tr>
      <tr><td colspan="3" style="color:#4a4a4a;font-style:italic">Themes: {themes_str}</td></tr>
    </table>

      <div style="padding:8px 0;font-size:11px;color:#8a6a00;border-top:1px solid #f0e8d0;margin-top:4px">
      Full thesis and scenarios will be generated automatically each month. No API credits required.
    </div>
  </div>
</div>"""
    return card


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


def _build_exec_summary(holdings: list) -> str:
    """
    Front-page analyst summary table \u2014 the whole book at a 15-20 year glance,
    the way a long-horizon research firm opens a note. No price targets: rating
    is the multi-decade stance, and the return columns are probabilistic.
    """
    if not holdings:
        return ''

    def _sort_key(h):
        t_order = {'T1': 0, 'T2': 1, 'T3': 2}.get(h.get('tier', 'T9'), 9)
        ep, cp = h.get('entry_price'), h.get('current_price')
        ret = ((cp - ep) / ep) if (ep and cp) else 0
        return (t_order, -ret)

    def _th(label, center=False):
        align = 'text-align:center;' if center else ''
        return (f'<td style="padding:6px 6px;font-size:8px;font-weight:700;color:#9ca3af;'
                f'text-transform:uppercase;letter-spacing:.06em;{align}">{label}</td>')

    rows = ''
    for h in sorted(holdings, key=_sort_key):
        tk   = h.get('ticker', '')
        tier = h.get('tier', '')
        rc, rbg, rlbl = _rating_style(h.get('verdict'))
        sect_dur = str(h.get('sector_durability_20yr', '') or '')
        sc = {'HIGH': '#15803d', 'MEDIUM': '#d97706', 'LOW': '#dc2626'}.get(sect_dur, '#9ca3af')
        moat = h.get('moat_durability_years')
        moat_s = f'{moat}y' if moat else '\u2014'
        dp = h.get('decade_probability')
        if isinstance(dp, (int, float)):
            dp_s = 'High' if dp >= 0.65 else ('Medium' if dp >= 0.45 else 'Lower')
            dp_c = '#15803d' if dp >= 0.65 else ('#d97706' if dp >= 0.45 else '#9ca3af')
        else:
            dp_s, dp_c = '\u2014', '#9ca3af'
        al = h.get('annual_alpha_estimate')
        al_num = isinstance(al, (int, float))
        if al_num:
            al_s = 'Ahead' if al >= 2 else ('Behind' if al <= -2 else 'In line')
            al_c = '#15803d' if al >= 2 else ('#dc2626' if al <= -2 else '#6b7280')
        else:
            al_s, al_c = '\u2014', '#9ca3af'
        thesis = (h.get('thesis_summary', '') or '')
        thesis_s = (thesis[:70] + '\u2026') if len(thesis) > 70 else (thesis or '\u2014')
        rows += (
            f'<tr style="border-bottom:1px solid #eef0f2">'
            f'<td style="padding:7px 6px;vertical-align:top;white-space:nowrap">'
            f'<strong style="font-size:12px;color:#111827">{tk}</strong>'
            f'<span style="font-size:8px;color:#9ca3af;margin-left:4px">{tier}</span></td>'
            f'<td style="padding:7px 6px;vertical-align:top;white-space:nowrap">'
            f'<span style="background:{rbg};color:{rc};font-size:8.5px;font-weight:700;'
            f'padding:2px 6px;border-radius:2px;border:1px solid {rc}33">{rlbl}</span></td>'
            f'<td style="padding:7px 6px;vertical-align:top;text-align:center;'
            f'font-size:10px;font-weight:700;color:{sc}">{sect_dur or "\u2014"}</td>'
            f'<td style="padding:7px 6px;vertical-align:top;text-align:center;font-size:10px;color:#374151">{moat_s}</td>'
            f'<td style="padding:7px 6px;vertical-align:top;text-align:center;font-size:10px;font-weight:700;color:{dp_c}">{dp_s}</td>'
            f'<td style="padding:7px 6px;vertical-align:top;text-align:center;font-size:10px;font-weight:700;color:{al_c}">{al_s}</td>'
            f'<td style="padding:7px 6px;vertical-align:top;font-size:9.5px;color:#6b7280;line-height:1.45">{thesis_s}</td>'
            f'</tr>'
        )

    return (
        '<div class="section" style="margin-bottom:14px">'
        '<div class="section-hdr">Executive summary &mdash; the book at a 15-20 year glance</div>'
        '<table style="width:100%;border-collapse:collapse">'
        '<tr style="border-bottom:2px solid #e5e7eb">'
        + _th('Stock') + _th('Rating') + _th('Sector 20y', True) + _th('Moat', True)
        + _th('Conviction', True) + _th('vs QQQ', True) + _th('Thesis') +
        '</tr>'
        f'{rows}'
        '</table>'
        '<div style="font-size:8.5px;color:#9ca3af;margin-top:8px">'
        'Rating = 15-20yr stance, not a trade. Decade odds &amp; vs-QQQ are the model\'s '
        'probabilistic estimates \u2014 not price targets.</div>'
        '</div>'
    )


def _build_concentration_view(holdings: list, screened: list) -> str:
    """
    Portfolio-level concentration analysis.
    A desk asks: am I secretly making one bet? Shows megatrend and sector weights,
    flags when any single theme exceeds 30% of the book.
    """
    if not holdings:
        return ""

    from collections import defaultdict
    mt_weight     = defaultdict(float)
    sector_weight = defaultdict(float)
    total_pos     = sum(h.get('position_size_pct', 0) or 0 for h in holdings) or 1

    for h in holdings:
        pos = h.get('position_size_pct', 0) or 0
        mt  = h.get('megatrend_label', 'Unclassified') or 'Unclassified'
        sec = h.get('sector', 'Unknown') or 'Unknown'
        mt_weight[mt]     += pos
        sector_weight[sec] += pos

    # Sort by weight
    mt_sorted  = sorted(mt_weight.items(), key=lambda x: -x[1])
    sec_sorted = sorted(sector_weight.items(), key=lambda x: -x[1])

    # Build rows with concentration flags
    mt_rows = ""
    for label, weight in mt_sorted:
        pct = weight / total_pos * 100
        flag = ""
        if pct > 30:
            flag = '<span style="color:#c0392b;font-weight:600"> ⚠ concentrated</span>'
        bar_w = min(pct, 100)
        mt_rows += f"""
        <tr>
          <td>{label}{flag}</td>
          <td style="text-align:right">{pct:.0f}%</td>
          <td style="width:100px"><div style="background:#e8e8e8;height:6px;border-radius:3px">
            <div style="background:{'#c0392b' if pct>30 else '#1a3a5c'};width:{bar_w:.0f}%;height:6px;border-radius:3px"></div>
          </div></td>
        </tr>"""

    max_mt_pct = (mt_sorted[0][1] / total_pos * 100) if mt_sorted else 0
    verdict = ('⚠ Concentrated — single megatrend exceeds 30% of book'
               if max_mt_pct > 30
               else '✓ Reasonably diversified across megatrends')
    verdict_color = '#c0392b' if max_mt_pct > 30 else '#2a7a4a'

    return f"""
<div class="section">
  <div class="section-hdr">Portfolio concentration — am I making one bet?</div>
  <div style="font-size:11px;color:{verdict_color};font-weight:600;margin-bottom:10px">{verdict}</div>
  <table style="width:100%;border-collapse:collapse;font-size:11px">
    <tr><th style="text-align:left;font-size:9px;color:#8a8a8a;text-transform:uppercase;letter-spacing:0.1em;padding-bottom:6px">Megatrend exposure</th><th></th><th></th></tr>
    {mt_rows}
  </table>
</div>"""


def _build_sector_outlook(megatrend_review: dict) -> str:
    """
    Surfaces the LLM's own sector-level decisions: any megatrend discovered,
    deprecated, or restored this quarter (quarterly_review.py), plus the
    current survival verdict for every tracked megatrend. Without this, that
    review runs and changes what gets screened (research_metrics.py skips
    deprecated sectors; screener.py's scoring nudges toward high-scoring
    ones) but the reader never sees why — this makes the decision visible.
    """
    if not megatrend_review:
        return ""
    detail = megatrend_review.get('detail', {})
    if not detail:
        return ""
    scores                 = megatrend_review.get('scores', {})
    new_this_run           = megatrend_review.get('new_this_run', [])
    new_keys                = {m.get('key') for m in new_this_run}
    deprecated_this_run    = megatrend_review.get('deprecated_this_run', [])
    undeprecated_this_run  = megatrend_review.get('undeprecated_this_run', [])
    last_reviewed          = (megatrend_review.get('last_reviewed') or '')[:10]

    changes_html = ""
    if new_this_run:
        names = ', '.join(m.get('label', m.get('key', '?')) for m in new_this_run)
        changes_html += (f'<div style="font-size:10.5px;color:#15803d;margin-bottom:4px">'
                          f'<strong>+ New sector{"s" if len(new_this_run) > 1 else ""} identified:</strong> {names}</div>')
    if deprecated_this_run:
        names = ', '.join(detail.get(k, {}).get('label', k) for k in deprecated_this_run)
        changes_html += (f'<div style="font-size:10.5px;color:#b91c1c;margin-bottom:4px">'
                          f'<strong>&minus; Sector{"s" if len(deprecated_this_run) > 1 else ""} downgraded (fails 10yr survival):</strong> {names}</div>')
    if undeprecated_this_run:
        names = ', '.join(detail.get(k, {}).get('label', k) for k in undeprecated_this_run)
        changes_html += (f'<div style="font-size:10.5px;color:#15803d;margin-bottom:4px">'
                          f'<strong>+ Sector{"s" if len(undeprecated_this_run) > 1 else ""} restored:</strong> {names}</div>')

    rows = ""
    for key, d in sorted(detail.items(), key=lambda kv: -scores.get(kv[0], 0)):
        score  = scores.get(key, '—')
        # A missing key means this entry predates the survival-verdict schema
        # (or its review call failed) — that's "not yet assessed", never treat
        # it as a pass or a fail.
        surv10 = d.get('survives_10yr')
        surv20 = d.get('survives_20yr')
        if surv10 is False:
            badge_color, surv_label = '#b91c1c', 'FAILS 10YR'
        elif surv20 is False:
            badge_color, surv_label = '#b45309', 'FAILS 20YR'
        elif surv10 is None or surv20 is None:
            badge_color, surv_label = '#9ca3af', 'NOT YET ASSESSED'
        else:
            badge_color, surv_label = '#15803d', 'SURVIVES 20YR'
        new_tag = ' <span style="color:#9ca3af;font-weight:400">(new)</span>' if key in new_keys else ''
        rows += f"""
        <tr>
          <td style="padding:4px 0">{d.get('label', key)}{new_tag}</td>
          <td style="text-align:center;padding:4px 0">{score}/10</td>
          <td style="text-align:right;padding:4px 0"><span style="color:{badge_color};font-weight:600;font-size:9px">{surv_label}</span></td>
        </tr>"""

    return f"""
<div class="section">
  <div class="section-hdr">Sector outlook — where the LLM thinks 10-20yr durability actually is</div>
  {changes_html}
  <div style="font-size:8.5px;color:#9ca3af;margin-bottom:8px">Last reviewed {last_reviewed or 'never'} &middot; re-reviewed quarterly</div>
  <table style="width:100%;border-collapse:collapse;font-size:11px">
    <tr><th style="text-align:left;font-size:9px;color:#8a8a8a;text-transform:uppercase;letter-spacing:0.1em;padding-bottom:6px">Megatrend</th>
        <th style="font-size:9px;color:#8a8a8a;text-transform:uppercase;letter-spacing:0.1em;padding-bottom:6px">Score</th>
        <th style="text-align:right;font-size:9px;color:#8a8a8a;text-transform:uppercase;letter-spacing:0.1em;padding-bottom:6px">Survival</th></tr>
    {rows}
  </table>
</div>"""


def _build_sector_survival_map(sector_survival: dict, holdings: list) -> str:
    """
    Surfaces the top-down sector survival decision (screener.build_sector_survival_map):
    for every Yahoo sector in play this run, the LLM's 15-20yr verdict, how many
    companies it thinks stay leaders, and how many the book currently holds. LOW
    verdicts hard-veto new buys and flag existing holdings for exit, so this is
    the "why" behind those actions.
    """
    sectors = (sector_survival or {}).get('sectors', {})
    if not sectors:
        return ""
    as_of = (sector_survival.get('as_of') or '')[:10]

    from collections import Counter
    held = Counter((h.get('sector') or 'Unknown') for h in holdings)

    order = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}
    rows = ""
    for sec, d in sorted(sectors.items(), key=lambda kv: (order.get(str(kv[1].get('survives_20yr', 'MEDIUM')).upper(), 1), kv[0])):
        surv = str(d.get('survives_20yr', 'MEDIUM')).upper()
        color = {'HIGH': '#15803d', 'MEDIUM': '#b45309', 'LOW': '#b91c1c'}.get(surv, '#6b7280')
        mx  = d.get('max_survivors', '—')
        n_h = held.get(sec, 0)
        rationale = (d.get('rationale') or '')[:140]
        mt_ctx    = (d.get('megatrend_context') or '')[:90]
        rows += f"""
        <tr>
          <td style="padding:6px 0;vertical-align:top">
            <div style="font-weight:600;color:#111827">{sec}</div>
            <div style="font-size:9.5px;color:#6b7280;margin-top:1px">{rationale}</div>
            {f'<div style="font-size:9px;color:#9ca3af;margin-top:1px">Theme: {mt_ctx}</div>' if mt_ctx else ''}
          </td>
          <td style="padding:6px 0;text-align:center;vertical-align:top;white-space:nowrap">
            <span style="color:{color};font-weight:700;font-size:9px">{surv}</span>
          </td>
          <td style="padding:6px 0;text-align:center;vertical-align:top;white-space:nowrap;color:#374151">{n_h} / {mx}</td>
        </tr>"""

    return f"""
<div class="section">
  <div class="section-hdr">Sector survival map — will this sector still be here in 15-20 years?</div>
  <div style="font-size:8.5px;color:#9ca3af;margin-bottom:8px">LLM top-down verdict &middot; LOW vetoes new buys and flags existing holdings for exit &middot; survivor count caps holdings per sector &middot; assessed {as_of or 'this run'}</div>
  <table style="width:100%;border-collapse:collapse;font-size:11px">
    <tr>
      <th style="text-align:left;font-size:9px;color:#8a8a8a;text-transform:uppercase;letter-spacing:0.1em;padding-bottom:6px">Sector</th>
      <th style="font-size:9px;color:#8a8a8a;text-transform:uppercase;letter-spacing:0.1em;padding-bottom:6px">20yr</th>
      <th style="font-size:9px;color:#8a8a8a;text-transform:uppercase;letter-spacing:0.1em;padding-bottom:6px">Held / Survivors</th>
    </tr>
    {rows}
  </table>
</div>"""


def _build_decision_review(decision_review: dict) -> str:
    """
    Surfaces the LLM's advisory self-review of this run's decisions
    (screener.review_decisions): the overall critique plus any ticker it flagged
    REVIEW or OVERRIDE. Advisory only — nothing here changed a verdict.
    """
    dr = decision_review or {}
    reviews = dr.get('reviews', {})
    note    = (dr.get('portfolio_note') or '').strip()
    flagged = {tk: v for tk, v in reviews.items()
               if str(v.get('flag', '')).upper() in ('REVIEW', 'OVERRIDE')}
    if not note and not flagged:
        return ""

    rows = ""
    for tk, v in sorted(flagged.items(), key=lambda kv: 0 if str(kv[1].get('flag')).upper() == 'OVERRIDE' else 1):
        flag = str(v.get('flag', '')).upper()
        color = '#b91c1c' if flag == 'OVERRIDE' else '#b45309'
        rows += f"""
        <tr>
          <td style="padding:5px 0;vertical-align:top;white-space:nowrap"><strong style="color:#111827">{tk}</strong></td>
          <td style="padding:5px 0 5px 8px;vertical-align:top"><span style="color:{color};font-weight:700;font-size:9px">{flag}</span>
            <span style="color:#374151"> &mdash; {(v.get('note') or '')[:180]}</span></td>
        </tr>"""

    summary = (f'<span style="color:#b45309;font-weight:600">{len(flagged)} decision{"s" if len(flagged) != 1 else ""} flagged for a second look</span>'
               if flagged else '<span style="color:#2a7a4a;font-weight:600">✓ All decisions internally consistent</span>')
    note_html = (f'<div style="font-size:11px;color:#334155;line-height:1.6;margin-bottom:{"10px" if flagged else "0"}">{note[:400]}</div>'
                 if note else '')
    table_html = (f'<table style="width:100%;border-collapse:collapse;font-size:11px">{rows}</table>'
                  if flagged else '')

    return f"""
<div class="section">
  <div class="section-hdr">Decision self-review — the model checking its own work</div>
  <div style="font-size:11px;margin-bottom:8px">{summary}</div>
  {note_html}
  {table_html}
  <div style="font-size:8.5px;color:#9ca3af;margin-top:8px">Advisory only &middot; flags do not change any verdict automatically</div>
</div>"""


def _build_whats_changed(decisions: dict, decision_review: dict) -> str:
    """
    'What changed this quarter' — the structural moves a long-horizon desk cares
    about: new positions, exits, and tier migrations. Steady-state is the norm
    for a 15-20yr book, so an empty quarter is reported as a feature, not a gap.
    """
    d = decisions or {}
    adds  = d.get('new_additions', []) or []
    exits = d.get('exits', []) or []
    migs  = d.get('migrations', []) or []

    dr = decision_review or {}
    flagged = {tk: v for tk, v in (dr.get('reviews', {}) or {}).items()
               if str(v.get('flag', '')).upper() in ('REVIEW', 'OVERRIDE')}

    if not (adds or exits or migs or flagged):
        return (
            '<div class="section" style="margin-bottom:14px">'
            '<div class="section-hdr">What changed this quarter</div>'
            '<div style="font-size:11px;color:#15803d;font-weight:600">'
            '&#10003; No structural changes &mdash; the book held steady. '
            '<span style="color:#6b7280;font-weight:400">For a 15-20 year strategy, '
            'inaction is usually the correct action.</span></div>'
            '</div>'
        )

    def _chip(label, color, bg):
        return (f'<span style="background:{bg};color:{color};font-size:8.5px;font-weight:700;'
                f'padding:2px 7px;border-radius:2px;margin-right:6px;white-space:nowrap">{label}</span>')

    rows = ''
    for it in adds:
        tk = it.get('ticker', ''); co = it.get('company_name', tk); tier = it.get('tier', '')
        rows += (f'<tr style="border-bottom:1px solid #f1f3f5"><td style="padding:7px 6px;white-space:nowrap">'
                 f'{_chip("NEW POSITION", "#15803d", "#f0fdf4")}</td>'
                 f'<td style="padding:7px 6px"><strong style="color:#111827">{tk}</strong> '
                 f'<span style="color:#9ca3af;font-size:9px">{tier}</span>'
                 f'<span style="color:#6b7280;font-size:10px"> &middot; {co}</span></td></tr>')
    for it in migs:
        tk = it.get('ticker', ''); ft = it.get('from_tier', '?'); tt = it.get('to_tier', '?')
        rows += (f'<tr style="border-bottom:1px solid #f1f3f5"><td style="padding:7px 6px;white-space:nowrap">'
                 f'{_chip("TIER MOVE", "#1d4ed8", "#eff4ff")}</td>'
                 f'<td style="padding:7px 6px"><strong style="color:#111827">{tk}</strong>'
                 f'<span style="color:#6b7280;font-size:10px"> &middot; {ft} &rarr; {tt}</span></td></tr>')
    for it in exits:
        tk = it.get('ticker', ''); note = (it.get('exit_reason', '') or '')[:80]
        note_html = f'<span style="color:#6b7280;font-size:10px"> &middot; {note}</span>' if note else ''
        rows += (f'<tr style="border-bottom:1px solid #f1f3f5"><td style="padding:7px 6px;white-space:nowrap">'
                 f'{_chip("EXITED", "#dc2626", "#fef2f2")}</td>'
                 f'<td style="padding:7px 6px"><strong style="color:#111827">{tk}</strong>'
                 f'{note_html}</td></tr>')
    for tk, v in sorted(flagged.items(), key=lambda kv: 0 if str(kv[1].get('flag')).upper() == 'OVERRIDE' else 1):
        flag = str(v.get('flag', '')).upper(); note = (v.get('note', '') or '')[:80]
        note_html = f'<span style="color:#6b7280;font-size:10px"> &middot; {note}</span>' if note else ''
        rows += (f'<tr style="border-bottom:1px solid #f1f3f5"><td style="padding:7px 6px;white-space:nowrap">'
                 f'{_chip("COMMITTEE " + flag, "#b45309", "#fffbeb")}</td>'
                 f'<td style="padding:7px 6px"><strong style="color:#111827">{tk}</strong>'
                 f'{note_html}</td></tr>')

    parts = []
    if adds:  parts.append(f'{len(adds)} new')
    if migs:  parts.append(f'{len(migs)} tier move{"s" if len(migs) != 1 else ""}')
    if exits: parts.append(f'{len(exits)} exit{"s" if len(exits) != 1 else ""}')
    if flagged: parts.append(f'{len(flagged)} flagged')
    summary = ' &middot; '.join(parts)

    return (
        '<div class="section" style="margin-bottom:14px">'
        '<div class="section-hdr">What changed this quarter</div>'
        f'<div style="font-size:10px;color:#6b7280;margin-bottom:8px">{summary}</div>'
        '<table style="width:100%;border-collapse:collapse;font-size:11px">'
        f'{rows}</table>'
        '</div>'
    )


def _build_disclosures() -> str:
    """Methodology & disclosures — what the ratings mean and their limits."""
    def _row(term, body):
        return (f'<tr><td style="padding:5px 10px 5px 0;vertical-align:top;white-space:nowrap;'
                f'font-size:9.5px;font-weight:700;color:#374151">{term}</td>'
                f'<td style="padding:5px 0;vertical-align:top;font-size:9.5px;color:#6b7280;'
                f'line-height:1.6">{body}</td></tr>')
    return (
        '<div class="section" style="margin-bottom:6px">'
        '<div class="section-hdr">Methodology &amp; disclosures</div>'
        '<div style="font-size:10px;color:#4b5563;line-height:1.6;margin-bottom:10px">'
        'Every position is assessed for a <strong>15-20 year</strong> hold. We do not set price '
        'targets or trade on momentum; the figures below are probabilistic estimates of how a '
        'business compounds over a decade-plus, not forecasts of next quarter.</div>'
        '<table style="width:100%;border-collapse:collapse">'
        + _row('Rating', 'A multi-decade stance &mdash; CORE HOLD, ACCUMULATE, MONITOR, AVOID '
               '(or MOONSHOT for T3). It is <em>not</em> a buy/sell trade signal.')
        + _row('Decade odds', 'The model&#39;s estimated probability that the investment thesis '
               'plays out over the next 10+ years. Subjective and model-generated.')
        + _row('vs QQQ/yr', 'Estimated annualised excess return versus the Nasdaq-100 over the hold. '
               'An expectation, not a promise; wide error bars apply.')
        + _row('Moat / Sector 20y', 'Durability of the competitive advantage and of the sector&#39;s '
               'relevance over a 15-20 year horizon.')
        + _row('News / 8-K / AI insights', 'Short-term (30-day) context only. These do <em>not</em> '
               'override a long-term thesis; they are background colour.')
        + '</table>'
        '<div style="font-size:8.5px;color:#9ca3af;margin-top:10px;line-height:1.6">'
        'Generated by an autonomous model (NVIDIA NIM) using Finnhub, SEC EDGAR and Yahoo Finance data. '
        'AI-written insights may contain errors &mdash; verify independently. '
        'For informational purposes only; not personalised financial advice.</div>'
        '</div>'
    )


def generate_full_report(decisions: dict, portfolio: dict, researched: dict,
                         ipo_watchlist: dict = None, fif_threshold: int = None,
                         megatrend_review: dict = None, sector_survival: dict = None,
                         decision_review: dict = None) -> tuple:
    """
    Email 2 — Full Research Brief.
    Professional, dense, analytical. Sunday reading standard.
    """
    month_str = datetime.now().strftime('%B %Y')
    date_str  = datetime.now().strftime('%d %b %Y')
    issue_n   = len(portfolio.get('run_history', [])) + 1
    subject   = f'Research Brief | {month_str} | Autonomous Capital'

    holdings  = [h for h in portfolio.get('holdings', []) if h.get('status') == 'ACTIVE']
    n_hold    = len(holdings)
    t1h = [h for h in holdings if h.get('tier') == 'T1']
    t2h = [h for h in holdings if h.get('tier') == 'T2']
    t3h = [h for h in holdings if h.get('tier') == 'T3']
    ks_yes = [h['ticker'] for h in holdings if h.get('kiwisaver_available')]
    ks_no  = [h['ticker'] for h in holdings if not h.get('kiwisaver_available')]
    screened   = decisions.get('screened_candidates', [])

    html = f"""<!DOCTYPE html><html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<style>{_CSS_BASE}</style></head><body>
<div class="w">

<!-- HEADER -->
<div style="background:#0d2137;padding:20px 16px 18px">
  <div style="font-size:9px;font-weight:600;color:#94a3b8;letter-spacing:.15em;text-transform:uppercase;margin-bottom:6px">Autonomous Capital</div>
  <table width="100%" border="0" cellpadding="0" cellspacing="0"><tr>
    <td style="vertical-align:bottom">
      <div style="font-size:26px;font-weight:800;color:#ffffff;letter-spacing:-.02em;line-height:1">Research Brief</div>
      <div style="font-size:10px;color:#64748b;margin-top:6px">{month_str} &middot; 20-year compounder analysis</div>
    </td>
    <td style="text-align:right;vertical-align:top;white-space:nowrap">
      <div style="font-size:9px;color:#475569">#{str(issue_n).zfill(2)}</div>
      <div style="font-size:9px;color:#475569;margin-top:2px">{date_str}</div>
    </td>
  </tr></table>
</div>

<!-- STATS BAR -->
<table width="100%" border="0" cellpadding="0" cellspacing="0" style="border-bottom:2px solid #eaecef">
  <tr>
    <td style="padding:13px 0;width:25%;text-align:center;border-right:1px solid #eaecef">
      <div style="font-size:8px;font-weight:600;color:#9ca3af;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px">Holdings</div>
      <div style="font-size:20px;font-weight:800;color:#111827">{n_hold}</div>
    </td>
    <td style="padding:13px 0;width:25%;text-align:center;border-right:1px solid #eaecef">
      <div style="font-size:8px;font-weight:600;color:#9ca3af;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px">T1 Quality</div>
      <div style="font-size:20px;font-weight:800;color:#15803d">{len(t1h)}</div>
    </td>
    <td style="padding:13px 0;width:25%;text-align:center;border-right:1px solid #eaecef">
      <div style="font-size:8px;font-weight:600;color:#9ca3af;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px">T2 Growth</div>
      <div style="font-size:20px;font-weight:800;color:#1d4ed8">{len(t2h)}</div>
    </td>
    <td style="padding:13px 0;width:25%;text-align:center">
      <div style="font-size:8px;font-weight:600;color:#9ca3af;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px">T3 Moonshot</div>
      <div style="font-size:20px;font-weight:800;color:#d97706">{len(t3h)}</div>
    </td>
  </tr>
</table>

<div style="padding:12px">"""

    html += _build_exec_summary(holdings)
    html += _build_whats_changed(decisions, decision_review)
    html += _build_sector_outlook(megatrend_review)
    html += _build_sector_survival_map(sector_survival, holdings)
    html += _build_decision_review(decision_review)
    html += _build_concentration_view(holdings, screened)

    # Holdings — sorted by tier then return descending
    def _sort_key(h):
        t_order = {'T1': 0, 'T2': 1, 'T3': 2}.get(h.get('tier', 'T9'), 9)
        ep, cp = h.get('entry_price'), h.get('current_price')
        ret = ((cp - ep) / ep) if (ep and cp) else 0
        return (t_order, -ret)

    if holdings:
        for h in sorted(holdings, key=_sort_key):
            html += _holding_card(h)

    # Screened candidates
    if screened:
        html += (
            f'<div style="margin-top:8px;margin-bottom:8px;padding:10px 14px;background:#fffbeb;'
            f'border-left:4px solid #d97706;font-size:8px;font-weight:700;color:#92400e;'
            f'letter-spacing:.1em;text-transform:uppercase">'
            f'Screened candidates &mdash; research pending ({len(screened)})</div>'
        )
        for s in screened:
            html += _screened_card(s)

    html += _build_disclosures()
    html += '</div>'  # padding:12px wrapper

    # FOOTER
    html += f"""
<table width="100%" border="0" cellpadding="0" cellspacing="0" style="border-top:1px solid #eaecef">
  <tr><td style="padding:12px 16px">
    <div style="font-size:9px;color:#9ca3af;line-height:1.8">
      <strong style="color:#374151">Autonomous Capital &middot; Research Brief</strong><br>
      Powered by NVIDIA NIM &middot; Finnhub &middot; SEC EDGAR &middot; Yahoo Finance<br>
      For informational purposes only. Not financial advice. Verify before acting.
    </div>
  </td></tr>
</table>
</div></body></html>"""

    return html, subject
