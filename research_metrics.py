#!/usr/bin/env python3
"""
research_metrics.py
===================
Senior researcher quality metrics for 20-year holding analysis.
All computable from Yahoo Finance data — no Anthropic credits required.

Philosophy: A 20-year compounder is identified by the quality and durability
of its economics, not by its current price momentum.
"""

import os, requests, time, logging
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger('metrics')

HEADERS = {'User-Agent': 'LongTermScreener contact@example.com'}

# ── MEGATREND SCORING SYSTEM ─────────────────────────────────────────────────
# ALL megatrend definitions live in universe_config.json → megatrends
# No company names, no hardcoded keywords, no hardcoded scores in Python.
# To add a new megatrend or update keywords: edit universe_config.json.
# Scores are layered:
#   1. base_score from config (structural assessment, changes slowly)
#   2. data/megatrend_scores.json (Claude quarterly review, 90-day TTL)
#   3. universe_config.json megatrend_overrides (your manual override, highest priority)

import json as _json
from pathlib import Path as _Path

def _load_megatrend_definitions() -> dict:
    """
    Load megatrend definitions from universe_config.json.
    Falls back to a minimal hardcoded set ONLY if config is missing.
    """
    try:
        cfg_file = _Path(__file__).parent / 'universe_config.json'
        if cfg_file.exists():
            cfg = _json.loads(cfg_file.read_text())
            mt_cfg = cfg.get('megatrends', {})
            result = {}
            for k, v in mt_cfg.items():
                if k.startswith('_'): continue   # skip comment keys
                result[k] = {
                    'label':          v.get('label', k),
                    'base_score':     int(v.get('base_score', 7)),
                    'score':          int(v.get('base_score', 7)),  # default to base
                    'tailwind_years': int(v.get('tailwind_years', 15)),
                    'rationale':      v.get('rationale', ''),
                    'keywords':       [kw.lower() for kw in v.get('keywords', [])],
                }
            return result
    except Exception as e:
        pass
    # Minimal fallback — only if universe_config.json is truly missing
    # All keywords are category-descriptive, never company-specific
    return {
        'ai_infrastructure':  {'label':'AI Infrastructure','base_score':10,'score':10,'tailwind_years':20,'rationale':'','keywords':['artificial intelligence','machine learning','gpu','data center','semiconductor','networking','inference','hyperscale']},
        'nuclear_renaissance':{'label':'Nuclear Renaissance','base_score':9,'score':9,'tailwind_years':30,'rationale':'','keywords':['nuclear','reactor','uranium','small modular reactor','smr','nuclear fuel','enrichment','nuclear power']},
        'space_commercial':   {'label':'Space Commercialisation','base_score':9,'score':9,'tailwind_years':25,'rationale':'','keywords':['launch vehicle','satellite','rocket','orbit','spacecraft','constellation','reusable launch']},
        'synthetic_biology':  {'label':'Synthetic Biology','base_score':9,'score':9,'tailwind_years':25,'rationale':'','keywords':['rna','mrna','gene therapy','gene editing','crispr','biologics','cell therapy','immunotherapy','genomics']},
        'critical_minerals':  {'label':'Critical Minerals','base_score':8,'score':8,'tailwind_years':20,'rationale':'','keywords':['tungsten','lithium','cobalt','rare earth','nickel','critical mineral','strategic material','battery material']},
        'defense_technology': {'label':'Defense Technology','base_score':8,'score':8,'tailwind_years':20,'rationale':'','keywords':['autonomous systems','unmanned','drone','cyber security','defense','military','electronic warfare','hypersonic']},
        'aging_demographics': {'label':'Aging Demographics','base_score':8,'score':8,'tailwind_years':25,'rationale':'','keywords':['oncology','chronic disease','longevity','therapeutics','precision medicine','rare disease','orphan drug']},
        'energy_transition':  {'label':'Energy Transition','base_score':7,'score':7,'tailwind_years':20,'rationale':'','keywords':['solar','wind','battery storage','clean energy','renewable','hydrogen','fuel cell','energy storage']},
        'fintech_inclusion':  {'label':'Fintech and Inclusion','base_score':7,'score':7,'tailwind_years':15,'rationale':'','keywords':['digital payments','neobank','embedded finance','financial inclusion','digital banking','open banking']},
        'water_food_security':{'label':'Water and Food Security','base_score':7,'score':7,'tailwind_years':25,'rationale':'','keywords':['water treatment','desalination','water infrastructure','precision agriculture','food security','agritech']},
    }

def _load_megatrend_scores() -> dict:
    """
    Load effective scores.
    Priority: user config overrides > Claude quarterly review > base scores from config.
    """
    definitions = _load_megatrend_definitions()
    scores = {k: v['base_score'] for k, v in definitions.items()}

    # Layer 2: Claude quarterly review (data/megatrend_scores.json, 90-day TTL)
    try:
        q_file = _Path(__file__).parent / 'data' / 'megatrend_scores.json'
        if q_file.exists():
            q = _json.loads(q_file.read_text())
            for k, v in q.get('scores', {}).items():
                if k in scores:
                    scores[k] = int(v)
    except Exception:
        pass

    # Layer 1 (highest priority): user config overrides
    try:
        cfg_file = _Path(__file__).parent / 'universe_config.json'
        if cfg_file.exists():
            cfg = _json.loads(cfg_file.read_text())
            for k, v in cfg.get('megatrend_overrides', {}).items():
                if k in scores and not k.startswith('_'):
                    scores[k] = int(v)
    except Exception:
        pass

    return scores

def _build_megatrends() -> dict:
    """Build MEGATRENDS dict with effective scores applied."""
    definitions = _load_megatrend_definitions()
    effective   = _load_megatrend_scores()
    result = {}
    for k, v in definitions.items():
        result[k] = {**v, 'score': effective.get(k, v['base_score'])}
    return result

MEGATRENDS = _build_megatrends()


# ── MEGATREND ALIGNMENT ───────────────────────────────────────────────────────

def compute_megatrend_alignment(ticker: str, info: dict) -> dict:
    """
    Map a company to its primary megatrend.
    Uses company name, description, sector, and industry.
    """
    name    = (info.get('longName','') or info.get('shortName','')).lower()
    sector  = (info.get('sector','')  or '').lower()
    industry= (info.get('industry','') or '').lower()
    desc    = (info.get('longBusinessSummary','') or '')[:500].lower()
    ticker_l= ticker.lower()

    combined = f"{name} {sector} {industry} {desc} {ticker_l}"

    best_key   = None
    best_score = 0
    best_hits  = 0

    for key, mt in MEGATRENDS.items():
        hits = sum(1 for kw in mt['keywords'] if kw in combined)
        if hits > best_hits or (hits == best_hits and mt['score'] > best_score):
            best_hits  = hits
            best_score = mt['score']
            best_key   = key

    if best_hits == 0:
        return {
            'megatrend':       'general',
            'megatrend_label': 'General Market',
            'megatrend_score': 0,
            'tailwind_years':  0,
            'megatrend_note':  'No strong megatrend alignment identified',
        }

    mt = MEGATRENDS[best_key]
    return {
        'megatrend':       best_key,
        'megatrend_label': mt['label'],
        'megatrend_score': mt['score'],
        'tailwind_years':  mt['tailwind_years'],
        'megatrend_rationale': mt.get('rationale',''),
        'megatrend_note':  f'{best_hits} keyword matches',
    }

# ── FCF & CAPITAL METRICS ─────────────────────────────────────────────────────
def compute_fcf_metrics(info: dict, ticker: str = '') -> dict:
    """
    Free cash flow metrics — the most important valuation and quality check
    for a 20-year hold.

    FCF Yield = Free Cash Flow / Market Cap
    Net Cash  = Total Cash - Total Debt (positive = fortress, negative = leveraged)
    Capital Intensity = (Capex + R&D) / Revenue (lower = more scalable)
    Reinvestment Rate = (Capex + R&D) / Operating Cash Flow
    """
    try:
        mkt_cap  = info.get('marketCap', 0) or 0
        ocf      = info.get('operatingCashflow', 0) or 0
        capex    = abs(info.get('capitalExpenditures', 0) or 0)
        rd       = info.get('researchAndDevelopment', 0) or 0
        revenue  = max(info.get('totalRevenue', 1) or 1, 1)
        cash     = info.get('totalCash', 0) or 0
        debt     = info.get('totalDebt', 0) or 0

        # .info never has capitalExpenditures or researchAndDevelopment (same
        # gap as screener.py's compute_roic/compute_debt_ratios - see
        # fetch_financial_statement_fields there). Without this, FCF was
        # silently just OCF (capex never subtracted, overstating FCF Yield for
        # every capital-intensive company) and capital_intensity/
        # reinvestment_rate/rd_intensity were always 0. This function is only
        # ever called for existing holdings + newly-added candidates (a few
        # dozen tickers per run, not the full screened universe), so this
        # lazy fetch is cheap enough to always attempt here.
        if (not capex or not rd) and ticker:
            from screener import fetch_financial_statement_fields
            fin = fetch_financial_statement_fields(ticker)
            if not capex:
                capex = abs(fin.get('capitalExpenditures') or 0)
            if not rd:
                rd = fin.get('researchAndDevelopment') or 0

        fcf      = ocf - capex
        net_cash = cash - debt

        fcf_yield = round(fcf / mkt_cap * 100, 2) if mkt_cap > 0 else None
        net_cash_m = round(net_cash / 1e6, 0)
        cap_intensity = round((capex + rd) / revenue * 100, 1) if revenue > 0 else None
        reinvest_rate = round((capex + rd) / ocf * 100, 1) if ocf > 0 else None

        # Quality signal: is the company investing heavily in R&D relative to revenue?
        rd_intensity = round(rd / revenue * 100, 1) if revenue > 0 else 0

        return {
            'fcf':              fcf,
            'fcf_yield':        fcf_yield,
            'net_cash_m':       net_cash_m,
            'net_cash_flag':    'FORTRESS' if net_cash > 0 else 'LEVERAGED',
            'capital_intensity': cap_intensity,
            'reinvestment_rate': reinvest_rate,
            'rd_intensity':      rd_intensity,
        }
    except Exception as e:
        log.debug(f'FCF metrics error: {e}')
        return {
            'fcf': None, 'fcf_yield': None, 'net_cash_m': None,
            'net_cash_flag': 'UNKNOWN', 'capital_intensity': None,
            'reinvestment_rate': None, 'rd_intensity': 0,
        }

def compute_revenue_quality(info: dict) -> dict:
    """
    Revenue quality signals.
    High recurring revenue + low customer concentration = 20-year durability.
    Proxied from available Yahoo Finance fields.
    """
    revenue  = info.get('totalRevenue', 0) or 0
    ocf      = info.get('operatingCashflow', 0) or 0
    ni       = info.get('netIncomeToCommon', 0) or info.get('netIncome', 0) or 0
    rev_grow = info.get('revenueGrowth', 0) or 0
    gm       = info.get('grossMargins', 0) or 0
    sector   = (info.get('sector', '') or '').lower()
    industry = (info.get('industry', '') or '').lower()

    # Revenue type proxy based on sector/industry
    recurring_proxy = 'HIGH'
    if any(k in industry for k in ['software', 'saas', 'cloud', 'subscription']):
        recurring_proxy = 'HIGH'
    elif any(k in industry for k in ['retail', 'commodity', 'mining', 'oil', 'gas']):
        recurring_proxy = 'LOW'
    elif any(k in sector for k in ['technology', 'healthcare']):
        recurring_proxy = 'MEDIUM-HIGH'
    else:
        recurring_proxy = 'MEDIUM'

    # FCF conversion quality
    ocf_ni_ratio = round(ocf / ni, 2) if ni > 0 else None
    eq_flag = ('CLEAN' if (ocf_ni_ratio or 0) >= 1.1
               else 'WATCH' if (ocf_ni_ratio or 0) >= 0.8
               else 'FLAG')

    return {
        'recurring_revenue_proxy': recurring_proxy,
        'ocf_ni_ratio':            ocf_ni_ratio,
        'earnings_quality':        eq_flag,
        'rev_growth_signal':       ('ACCELERATING' if rev_grow > 0.30
                                    else 'GROWING' if rev_grow > 0.10
                                    else 'STABLE' if rev_grow > 0
                                    else 'DECLINING'),
    }

def compute_management_quality(info: dict) -> dict:
    """
    Management quality proxies.
    Founder-led + high insider ownership + low dilution = aligned operator.
    """
    insider_pct = float(info.get('heldPercentInsiders', 0) or 0)
    instit_pct  = float(info.get('heldPercentInstitutions', 0) or 0)
    shares_out  = info.get('sharesOutstanding', 0) or 0
    implied     = info.get('impliedSharesOutstanding', 0) or 0
    floats      = info.get('floatShares', 0) or 0

    dilution = 0.0
    if shares_out > 0 and implied > shares_out:
        dilution = (implied - shares_out) / shares_out
    elif shares_out > 0 and floats > shares_out:
        dilution = (floats - shares_out) / shares_out

    # Insider ownership signal
    if insider_pct > 0.10:
        insider_signal = 'FOUNDER-LEVEL'
    elif insider_pct > 0.03:
        insider_signal = 'ALIGNED'
    elif insider_pct > 0.01:
        insider_signal = 'TYPICAL'
    else:
        insider_signal = 'LOW'

    return {
        'insider_pct':      insider_pct,
        'insider_signal':   insider_signal,
        'institutional_pct': instit_pct,
        'dilution_rate':    dilution,
        'dilution_flag':    ('SEVERE' if dilution > 0.30
                             else 'HIGH' if dilution > 0.15
                             else 'MODERATE' if dilution > 0.05
                             else 'MINIMAL'),
    }

# ── INSIDER TRANSACTIONS (SEC Form 4 — FREE) ──────────────────────────────────
def fetch_insider_transactions(ticker: str) -> dict:
    """
    Fetch recent Form 4 insider transactions from SEC EDGAR.
    Insider buying is a strong bullish signal for long-term investors.
    Insider selling is routine (options, diversification) — less informative.
    """
    try:
        from_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
        to_date   = datetime.now().strftime('%Y-%m-%d')

        resp = requests.get(
            'https://efts.sec.gov/LATEST/search-index',
            params={
                'q':         f'"{ticker}"',
                'forms':     '4',
                'dateRange': 'custom',
                'startdt':   from_date,
                'enddt':     to_date,
            },
            headers=HEADERS,
            timeout=12
        )
        if resp.status_code != 200:
            return {'insider_buys': 0, 'insider_sells': 0, 'insider_signal': 'UNKNOWN'}

        hits = resp.json().get('hits', {}).get('hits', [])
        if not hits:
            return {'insider_buys': 0, 'insider_sells': 0, 'insider_signal': 'NEUTRAL'}

        # Form 4 hits indicate recent insider activity — we can't easily
        # distinguish buys from sells without parsing the actual form,
        # but the count and recency are informative signals
        recent_filings = len(hits)
        return {
            'insider_form4_90d': recent_filings,
            'insider_signal':    ('ACTIVE' if recent_filings > 3
                                  else 'SOME' if recent_filings > 0
                                  else 'NONE'),
            'insider_note':      f'{recent_filings} Form 4 filings in 90 days',
        }
    except Exception as e:
        log.debug(f'Form 4 fetch failed for {ticker}: {e}')
        return {'insider_form4_90d': 0, 'insider_signal': 'UNKNOWN', 'insider_note': ''}

# ── MOAT PROXY SCORING ────────────────────────────────────────────────────────
def compute_moat_proxy(info: dict) -> dict:
    """
    Proxy moat score from financial data alone (no 10-K reading required).

    High ROIC sustained + expanding margins + low dilution = strong moat signal.
    This is NOT a substitute for 10-K research, but it's directionally useful.
    """
    gm        = info.get('grossMargins', 0) or 0
    op_margin = info.get('operatingMargins', 0) or 0
    rev_grow  = info.get('revenueGrowth', 0) or 0

    try:
        op_income = info.get('operatingIncome', 0) or 0
        tax_rate  = max(0.0, min(float(info.get('effectiveTaxRate', 0.25) or 0.25), 0.5))
        tot_assets= info.get('totalAssets', 0) or 0
        curr_liab = info.get('totalCurrentLiabilities', 0) or 0
        inv_cap   = tot_assets - curr_liab
        roic = (op_income * (1 - tax_rate)) / inv_cap if inv_cap > 0 else 0
    except Exception:
        roic = info.get('returnOnEquity', 0) or 0

    # Pricing power proxy: high gross margin + growing with it maintained
    pricing_power = 'STRONG' if gm > 0.60 else ('MODERATE' if gm > 0.35 else 'WEAK')

    # Scalability proxy: growing revenue without proportional cost growth
    scalability = 'HIGH' if (gm > 0.50 and rev_grow > 0.15) else ('MEDIUM' if gm > 0.30 else 'LOW')

    # Overall moat proxy score 0-10
    score = 0
    if roic > 0.25: score += 4
    elif roic > 0.15: score += 2
    if gm > 0.60: score += 3
    elif gm > 0.40: score += 1
    if op_margin > 0.20: score += 2
    if rev_grow > 0.20: score += 1

    return {
        'roic':           round(roic, 4),
        'gross_margin':   gm,
        'op_margin':      op_margin,
        'pricing_power':  pricing_power,
        'scalability':    scalability,
        'moat_proxy_score': score,
        'moat_proxy_label': ('STRONG' if score >= 7
                              else 'MODERATE' if score >= 4
                              else 'WEAK'),
    }

def compute_all_metrics(ticker: str, info: dict) -> dict:
    """
    Compute all senior researcher metrics for a single candidate.
    Returns unified dict ready for email rendering.
    """
    megatrend  = compute_megatrend_alignment(ticker, info)
    fcf        = compute_fcf_metrics(info, ticker)
    rev_qual   = compute_revenue_quality(info)
    mgmt       = compute_management_quality(info)
    moat       = compute_moat_proxy(info)
    insiders   = fetch_insider_transactions(ticker)
    time.sleep(0.3)  # SEC rate limit courtesy

    return {
        **megatrend,
        **fcf,
        **rev_qual,
        **mgmt,
        **moat,
        **insiders,
    }
