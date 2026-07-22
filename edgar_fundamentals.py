#!/usr/bin/env python3
"""
edgar_fundamentals.py
=====================
SEC EDGAR fundamentals — free, authoritative, no API key.

Pulls actual filed XBRL data from companyfacts API. Used to:
  1. Cross-check Yahoo Finance (flag disagreements)
  2. Compute 5-year trajectory (ROIC, margins, revenue trends)
  3. Detect serial dilution (share count over time)
  4. Extract customer concentration risk from 10-K text

Two-step lookup: ticker -> CIK -> companyfacts.
All endpoints are free and rate-limited to 10 req/sec by SEC (we stay well under).
"""

import os, json, time, logging, re
from datetime import datetime
from pathlib import Path
import requests

log = logging.getLogger('edgar')

HEADERS = {'User-Agent': 'LongTermScreener vishvesh.niyati@gmail.com'}

BASE_DIR     = Path(__file__).parent
CIK_MAP_FILE = BASE_DIR / 'data' / 'cik_map.json'
CIK_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)

# XBRL concept tags we care about (us-gaap taxonomy)
CONCEPTS = {
    'revenue':        ['Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax',
                       'SalesRevenueNet'],
    'net_income':     ['NetIncomeLoss'],
    'operating_income': ['OperatingIncomeLoss'],
    'operating_cashflow': ['NetCashProvidedByUsedInOperatingActivities',
                       'NetCashProvidedByUsedInOperatingActivitiesContinuingOperations'],
    'total_assets':   ['Assets'],
    'current_assets': ['AssetsCurrent'],
    'current_liab':   ['LiabilitiesCurrent'],
    'interest_expense': ['InterestExpense', 'InterestExpenseDebt',
                       'InterestIncomeExpenseNet'],
    'total_debt':     ['LongTermDebtNoncurrent', 'LongTermDebt'],
    'cash':           ['CashAndCashEquivalentsAtCarryingValue'],
    'shares':         ['CommonStockSharesOutstanding',
                       'WeightedAverageNumberOfDilutedSharesOutstanding'],
    'gross_profit':   ['GrossProfit'],
    'rd_expense':     ['ResearchAndDevelopmentExpense'],
    'stockholders_equity': ['StockholdersEquity',
                            'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'],
}


# ── CIK LOOKUP ────────────────────────────────────────────────────────────────
def _load_cik_map() -> dict:
    """Load cached ticker->CIK map, refreshing from SEC if missing/stale."""
    if CIK_MAP_FILE.exists():
        try:
            data = json.loads(CIK_MAP_FILE.read_text())
            # Refresh if older than 30 days
            if data.get('_fetched'):
                age_days = (datetime.now() - datetime.fromisoformat(data['_fetched'])).days
                if age_days < 30:
                    return data.get('map', {})
        except Exception:
            pass
    return _refresh_cik_map()


def _refresh_cik_map() -> dict:
    """Download the full ticker->CIK mapping from SEC (one file, ~500KB)."""
    try:
        resp = requests.get(
            'https://www.sec.gov/files/company_tickers.json',
            headers=HEADERS, timeout=20
        )
        if resp.status_code != 200:
            log.warning(f'  CIK map fetch failed: HTTP {resp.status_code}')
            return {}
        raw = resp.json()
        # Format: {"0":{"cik_str":320193,"ticker":"AAPL","title":"Apple Inc."}, ...}
        cik_map = {}
        for entry in raw.values():
            ticker = entry.get('ticker', '').upper()
            cik    = str(entry.get('cik_str', '')).zfill(10)
            if ticker:
                cik_map[ticker] = cik
        CIK_MAP_FILE.write_text(json.dumps({
            '_fetched': datetime.now().isoformat(),
            'map': cik_map
        }, indent=0))
        log.info(f'  CIK map refreshed: {len(cik_map):,} tickers')
        return cik_map
    except Exception as e:
        log.warning(f'  CIK map refresh error: {e}')
        return {}


_CIK_CACHE = None

def get_cik(ticker: str) -> str:
    """Resolve ticker to zero-padded CIK. Returns '' if not found."""
    global _CIK_CACHE
    if _CIK_CACHE is None:
        _CIK_CACHE = _load_cik_map()
    return _CIK_CACHE.get(ticker.upper(), '')


# ── COMPANYFACTS FETCH ────────────────────────────────────────────────────────
def fetch_company_facts(ticker: str) -> dict:
    """
    Fetch the full companyfacts XBRL blob for a ticker.
    Returns raw dict or {} on failure.
    """
    cik = get_cik(ticker)
    if not cik:
        return {}
    try:
        resp = requests.get(
            f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json',
            headers=HEADERS, timeout=20
        )
        if resp.status_code != 200:
            return {}
        time.sleep(0.15)   # SEC courtesy (10 req/sec limit)
        return resp.json()
    except Exception as e:
        log.debug(f'  companyfacts fetch failed for {ticker}: {e}')
        return {}


def _extract_annual_series(facts: dict, concept_tags: list) -> list:
    """
    Extract annual values for a concept, most recent first.
    Returns list of {'fy': year, 'val': value, 'end': date}.
    """
    us_gaap = facts.get('facts', {}).get('us-gaap', {})
    for tag in concept_tags:
        if tag not in us_gaap:
            continue
        units = us_gaap[tag].get('units', {})
        # Prefer USD, fall back to shares
        for unit_key in ['USD', 'shares', 'USD/shares']:
            if unit_key not in units:
                continue
            # Annual figures only (form 10-K, fp FY)
            annual = [
                {'fy': item.get('fy'), 'val': item.get('val'), 'end': item.get('end')}
                for item in units[unit_key]
                if item.get('form') == '10-K' and item.get('fp') == 'FY' and item.get('val') is not None
            ]
            # Dedupe by fiscal year, keep latest filed
            by_year = {}
            for a in annual:
                if a['fy'] and (a['fy'] not in by_year or a['end'] > by_year[a['fy']]['end']):
                    by_year[a['fy']] = a
            series = sorted(by_year.values(), key=lambda x: x['fy'], reverse=True)
            if series:
                return series
    return []


# ── 5-YEAR TRAJECTORY ─────────────────────────────────────────────────────────
def compute_trajectory(ticker: str) -> dict:
    """
    Compute 5-year trends from EDGAR filed data.
    A 20-year compounder should show improving or stable economics.

    Returns trend direction + slope for ROIC, gross margin, revenue,
    plus dilution trajectory (share count growth) and a data-quality note.
    """
    facts = fetch_company_facts(ticker)
    if not facts:
        return {'edgar_available': False, 'edgar_note': 'No EDGAR data (foreign/ETF/missing CIK)'}

    revenue   = _extract_annual_series(facts, CONCEPTS['revenue'])
    net_inc   = _extract_annual_series(facts, CONCEPTS['net_income'])
    op_inc    = _extract_annual_series(facts, CONCEPTS['operating_income'])
    assets    = _extract_annual_series(facts, CONCEPTS['total_assets'])
    curr_liab = _extract_annual_series(facts, CONCEPTS['current_liab'])
    gross     = _extract_annual_series(facts, CONCEPTS['gross_profit'])
    shares    = _extract_annual_series(facts, CONCEPTS['shares'])

    def _trend(series, years=5):
        """Direction + % change over available years (up to `years`)."""
        if len(series) < 2:
            return {'direction': 'INSUFFICIENT', 'pct_change': None, 'years': len(series)}
        recent = series[:years]
        newest = recent[0]['val']
        oldest = recent[-1]['val']
        n_yrs  = len(recent)
        if oldest is None or newest is None or oldest == 0:
            return {'direction': 'INSUFFICIENT', 'pct_change': None, 'years': n_yrs}
        pct = (newest - oldest) / abs(oldest) * 100
        direction = ('RISING' if pct > 5 else 'FALLING' if pct < -5 else 'STABLE')
        return {'direction': direction, 'pct_change': round(pct, 1), 'years': n_yrs}

    # Revenue trend
    rev_trend = _trend(revenue)

    # Gross margin trend (gross profit / revenue, year by year)
    gm_series = []
    rev_by_year = {r['fy']: r['val'] for r in revenue}
    for g in gross:
        rv = rev_by_year.get(g['fy'])
        if rv and rv != 0:
            gm_series.append({'fy': g['fy'], 'val': g['val'] / rv, 'end': g['end']})
    gm_trend = _trend(gm_series)

    # ROIC trend (NOPAT / invested capital, year by year)
    roic_series = []
    assets_by_year = {a['fy']: a['val'] for a in assets}
    cl_by_year     = {c['fy']: c['val'] for c in curr_liab}
    for oi in op_inc:
        ta = assets_by_year.get(oi['fy'])
        cl = cl_by_year.get(oi['fy'], 0)
        if ta and (ta - cl) > 0:
            nopat = oi['val'] * 0.79   # assume ~21% tax
            roic_series.append({'fy': oi['fy'], 'val': nopat / (ta - cl), 'end': oi['end']})
    roic_trend = _trend(roic_series)

    # Dilution trajectory (share count growth = bad)
    share_trend = _trend(shares)
    dilution_flag = 'NONE'
    if share_trend['pct_change'] is not None:
        if share_trend['pct_change'] > 30:    dilution_flag = 'SEVERE'
        elif share_trend['pct_change'] > 15:  dilution_flag = 'HIGH'
        elif share_trend['pct_change'] > 5:   dilution_flag = 'MODERATE'

    return {
        'edgar_available':    True,
        'years_of_data':      len(revenue),
        'revenue_trend':      rev_trend['direction'],
        'revenue_5yr_change': rev_trend['pct_change'],
        'gross_margin_trend': gm_trend['direction'],
        'gm_5yr_change':      gm_trend['pct_change'],
        'roic_trend':         roic_trend['direction'],
        'roic_5yr_change':    roic_trend['pct_change'],
        'share_count_trend':  share_trend['direction'],
        'share_5yr_change':   share_trend['pct_change'],
        'dilution_trajectory': dilution_flag,
        'edgar_note':         f'{len(revenue)} years of filed data',
    }


def compute_earnings_quality_trend(ticker: str) -> dict:
    """
    Multi-year (up to 3yr) earnings-quality trend from EDGAR filed data.

    A single-year OCF/Net-Income ratio can be flattered by a one-off working
    capital swing. Averaging the ratio across the last 3 filed years, and
    checking whether it is improving or deteriorating, distinguishes durable
    cash generation from an accounting one-off. Returns '' fields when EDGAR
    has no usable data (caller falls back to the single-year yfinance flag).
    """
    facts = fetch_company_facts(ticker)
    if not facts:
        return {'eq_trend_available': False}

    ocf = _extract_annual_series(facts, CONCEPTS['operating_cashflow'])
    ni  = _extract_annual_series(facts, CONCEPTS['net_income'])
    if not ocf or not ni:
        return {'eq_trend_available': False}

    ni_by_year = {n['fy']: n['val'] for n in ni}
    ratios = []   # (fy, ocf/ni) newest-first, only where NI is meaningfully positive
    for o in ocf:
        n = ni_by_year.get(o['fy'])
        if n and n > 0 and o['val'] is not None:
            ratios.append((o['fy'], o['val'] / n))
    ratios = ratios[:3]
    if not ratios:
        return {'eq_trend_available': False}

    vals = [r[1] for r in ratios]
    avg  = sum(vals) / len(vals)
    latest = vals[0]

    # Direction: compare newest year to the oldest available in the 3yr window.
    if len(vals) >= 2:
        oldest = vals[-1]
        if latest > oldest + 0.10:   direction = 'IMPROVING'
        elif latest < oldest - 0.10: direction = 'DETERIORATING'
        else:                        direction = 'STABLE'
    else:
        direction = 'STABLE'

    flag = ('CLEAN' if avg >= 1.1 else 'WATCH' if avg >= 0.8 else 'FLAG')
    return {
        'eq_trend_available':  True,
        'eq_years':            len(vals),
        'eq_ocf_ni_latest':    round(latest, 2),
        'eq_ocf_ni_3yr_avg':   round(avg, 2),
        'eq_trend_direction':  direction,
        'earnings_quality_3yr': flag,
    }


def get_edgar_statement_fields(ticker: str) -> dict:
    """
    Statement-level line items pulled from EDGAR filed XBRL, as a free,
    rate-limit-friendly fallback for the same fields yfinance's balance_sheet/
    income_stmt/cashflow properties fail to return under throttling. Returns a
    dict keyed the same way as screener.fetch_financial_statement_fields so it
    can be merged in as a drop-in backstop. Missing concepts are simply absent.
    """
    facts = fetch_company_facts(ticker)
    if not facts:
        return {}

    def _latest(key):
        s = _extract_annual_series(facts, CONCEPTS.get(key, []))
        return s[0]['val'] if s else None

    ta = _latest('total_assets')
    cl = _latest('current_liab')
    inv_cap = (ta - cl) if (ta is not None and cl is not None) else None
    out = {
        'operatingIncome':         _latest('operating_income'),
        'totalAssets':             ta,
        'totalCurrentAssets':      _latest('current_assets'),
        'totalCurrentLiabilities': cl,
        'interestExpense':         _latest('interest_expense'),
        'operatingCashflow':       _latest('operating_cashflow'),
        'investedCapital':         inv_cap,
    }
    return {k: v for k, v in out.items() if v is not None}


_EQUITY_CACHE: dict = {}

def get_stockholders_equity(ticker: str) -> float | None:
    """
    Most recent total stockholders' equity (USD) filed with SEC, for use as a
    fallback when Yahoo Finance has no usable equity figure (yfinance dropped
    'totalStockholderEquity' from its schema; 'bookValue' is per-share, not
    total). Cached per-run since gates may check the same ticker more than once.
    """
    if ticker in _EQUITY_CACHE:
        return _EQUITY_CACHE[ticker]
    equity = None
    try:
        facts  = fetch_company_facts(ticker)
        series = _extract_annual_series(facts, CONCEPTS['stockholders_equity'])
        if series:
            equity = series[0]['val']
    except Exception as e:
        log.debug(f'  EDGAR equity fetch failed for {ticker}: {e}')
    _EQUITY_CACHE[ticker] = equity
    return equity


# ── YAHOO CROSS-CHECK ─────────────────────────────────────────────────────────
def cross_check_yahoo(ticker: str, yahoo_info: dict) -> dict:
    """
    Compare Yahoo Finance figures against EDGAR filed data.
    Large disagreements are flagged — they often indicate data quality issues
    or recent corporate actions Yahoo hasn't caught up with.
    """
    facts = fetch_company_facts(ticker)
    if not facts:
        return {'cross_check': 'NO_EDGAR', 'discrepancies': []}

    revenue = _extract_annual_series(facts, CONCEPTS['revenue'])
    if not revenue:
        return {'cross_check': 'NO_DATA', 'discrepancies': []}

    edgar_rev  = revenue[0]['val']
    yahoo_rev  = yahoo_info.get('totalRevenue', 0) or 0
    discrepancies = []

    if edgar_rev and yahoo_rev:
        diff_pct = abs(edgar_rev - yahoo_rev) / max(edgar_rev, yahoo_rev) * 100
        if diff_pct > 15:
            discrepancies.append({
                'field':    'revenue',
                'yahoo':    yahoo_rev,
                'edgar':    edgar_rev,
                'diff_pct': round(diff_pct, 1),
            })

    return {
        'cross_check':    'FLAGGED' if discrepancies else 'CLEAN',
        'discrepancies':  discrepancies,
        'edgar_revenue':  edgar_rev,
        'edgar_fy':       revenue[0]['fy'],
    }



# ── CUSTOMER CONCENTRATION (10-K text) ────────────────────────────────────────
def fetch_customer_concentration(ticker: str) -> dict:
    """
    Scan the latest 10-K for customer concentration disclosure.
    Single-customer dependence above 10% is a material 20-year risk —
    companies are required to disclose customers exceeding 10% of revenue.
    Uses SEC full-text search (free) to find the relevant filing.
    """
    cik = get_cik(ticker)
    if not cik:
        return {'concentration_checked': False, 'concentration_note': 'No CIK'}

    try:
        # Get most recent 10-K filing reference
        resp = requests.get(
            f'https://data.sec.gov/submissions/CIK{cik}.json',
            headers=HEADERS, timeout=20
        )
        if resp.status_code != 200:
            return {'concentration_checked': False, 'concentration_note': 'No submissions data'}
        time.sleep(0.15)

        recent = resp.json().get('filings', {}).get('recent', {})
        forms  = recent.get('form', [])
        accns  = recent.get('accessionNumber', [])
        docs   = recent.get('primaryDocument', [])

        # Find latest 10-K
        tenk_idx = None
        for i, form in enumerate(forms):
            if form == '10-K':
                tenk_idx = i
                break
        if tenk_idx is None:
            return {'concentration_checked': False, 'concentration_note': 'No 10-K found'}

        accn = accns[tenk_idx].replace('-', '')
        doc  = docs[tenk_idx]
        url  = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/{doc}'

        filing = requests.get(url, headers=HEADERS, timeout=25)
        if filing.status_code != 200:
            return {'concentration_checked': False, 'concentration_note': 'Filing fetch failed'}
        time.sleep(0.15)

        text = re.sub(r'<[^>]+>', ' ', filing.text).lower()

        # Search for customer concentration language
        concentration_patterns = [
            r'one customer accounted for (?:approximately )?(\d+)%',
            r'largest customer (?:accounted for|represented) (?:approximately )?(\d+)%',
            r'(\d+)% of (?:our |total )?(?:net )?(?:revenue|sales)',
            r'customer represented (?:approximately )?(\d+)%',
        ]
        max_concentration = 0
        for pat in concentration_patterns:
            for m in re.finditer(pat, text):
                try:
                    pct = int(m.group(1))
                    if 10 <= pct <= 100:
                        max_concentration = max(max_concentration, pct)
                except (ValueError, IndexError):
                    pass

        # Detect explicit concentration risk language
        has_concentration_risk = any(phrase in text for phrase in [
            'customer concentration', 'dependent on a limited number of customers',
            'significant customer', 'loss of a major customer'
        ])

        flag = 'NONE'
        if max_concentration >= 30:   flag = 'HIGH'
        elif max_concentration >= 15: flag = 'MODERATE'
        elif max_concentration >= 10: flag = 'LOW'
        elif has_concentration_risk:  flag = 'DISCLOSED'

        return {
            'concentration_checked':   True,
            'max_customer_pct':        max_concentration if max_concentration else None,
            'concentration_flag':      flag,
            'concentration_risk_language': has_concentration_risk,
            'concentration_note':      (f'Largest customer ~{max_concentration}% of revenue'
                                        if max_concentration
                                        else 'Concentration risk disclosed' if has_concentration_risk
                                        else 'No material concentration found'),
        }
    except Exception as e:
        log.debug(f'  Concentration check failed for {ticker}: {e}')
        return {'concentration_checked': False, 'concentration_note': f'Error: {str(e)[:50]}'}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    # Quick self-test
    print("Testing EDGAR module with AAPL...")
    cik = get_cik('AAPL')
    print(f"  AAPL CIK: {cik}")
    traj = compute_trajectory('AAPL')
    print(f"  Trajectory: {json.dumps(traj, indent=2)}")
