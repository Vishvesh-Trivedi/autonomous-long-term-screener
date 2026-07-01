#!/usr/bin/env python3
"""
Offline validation for the long-term screener.
Run: python tests/test_offline.py   (no network/deps needed)
Checks syntax, prompt markers, history builder (US + foreign), long-term
fields, QQQ alpha, prompt formatting, requirements pins, and email render.
"""
import ast, os, sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, 'screener.py'), encoding='utf-8').read()
fails = []
def ok(name): print(f'PASS  {name}')
def bad(name, e): fails.append(name); print(f'FAIL  {name}: {e}')

# 1. syntax
try: ast.parse(SRC); ok('syntax')
except Exception as e: bad('syntax', e)

# 2. markers
markers = ['COMPANY HISTORY', 'THESIS-BREAK CHECK', '{company_history}', 'background only',
           'return_3yr_cagr', 'return_5yr_cagr', 'return_10yr_cagr', 'def build_company_history',
           'def get_qqq_cagrs', 'vs QQQ', 'long_term_alpha_pp', 'long_term_note', 'non-US filer', 'local ccy']
missing = [m for m in markers if m not in SRC]
ok('markers') if not missing else bad('markers', f'missing {missing}')

# isolate history builder (no third-party imports)
a, b = SRC.index('_QQQ_CAGR_CACHE'), SRC.index('def research_candidate')
def make_ns(edgar, yf=None):
    ns = {'datetime': datetime, 'compute_trajectory': lambda t: edgar}
    if yf: ns['yf'] = yf
    exec(SRC[a:b], ns)
    ns['build_company_history'].__globals__['get_qqq_cagrs'] = lambda: {3: 9.0, 5: 14.0, 10: 17.5}
    return ns

# 3. US history with QQQ alpha
try:
    ns = make_ns({'edgar_available': True, 'years_of_data': 10, 'revenue_trend': 'UP', 'revenue_5yr_change': 74,
                  'gross_margin_trend': 'STABLE', 'roic_trend': 'STABLE', 'roic_5yr_change': 3,
                  'share_count_trend': 'UP', 'share_5yr_change': 4, 'dilution_trajectory': 'LOW'})
    s = ns['build_company_history']('FNV', {'longName': 'FNV', 'fullTimeEmployees': 45},
        {'years_listed': 19, 'return_5yr_cagr': 9.7, 'return_10yr_cagr': 12.4, 'max_drawdown': -31.0, 'currency': 'USD'})
    assert 'vs QQQ' in s; ok('us history alpha')
except Exception as e: bad('us history alpha', e)

# 4. foreign fallback + local-ccy
try:
    class Row(list):
        def dropna(self): return self
        @property
        def iloc(self): return self
    class Fin: index = ['Total Revenue']; loc = {'Total Revenue': Row([200, 150, 100])}
    yf = type('Y', (), {'Ticker': staticmethod(lambda t: type('T', (), {'financials': Fin()})())})
    ns = make_ns({'edgar_available': False}, yf)
    s = ns['build_company_history']('TIGO', {'longName': 'Tigo'}, {'return_5yr_cagr': 5.0, 'max_drawdown': -20, 'currency': 'EUR'})
    assert 'non-US filer' in s and 'local ccy' in s; ok('foreign fallback')
except Exception as e: bad('foreign fallback', e)

# 5. prompts format
try:
    g = {}; exec(SRC[SRC.index('RESEARCH_PROMPT_T1_T2'):b].rsplit('def ', 1)[0], g)
    g['RESEARCH_PROMPT_T1_T2'].format(ticker='X', tier='T1', revenue=1, roic=.1, gm=.5, rev_growth=.1, mkt_cap=2,
        runway='ok', company_history='H', above_200ma='Y', return_1yr=1, vs_qqq=1, trend='UP', pct_from_high=-5,
        news_count=1, headlines='h', reddit_mentions=0, sec_8k_count=0, sec_8k_events='n', filing_text='f')
    g['RESEARCH_PROMPT_T3'].format(ticker='X', mkt_cap=2, cash=1, runway='ok', rd=1, revenue=1, company_history='H',
        above_200ma='Y', return_1yr=1, vs_qqq=1, trend='UP', reddit_mentions=0, reddit_titles='r', headlines='h',
        sec_8k_count=0, sec_8k_events='n', filing_text='f')
    ok('prompts format')
except Exception as e: bad('prompts format', e)

# 6. requirements pinned
try:
    reqs = open(os.path.join(ROOT, 'requirements.txt')).read()
    assert reqs.count('<') >= 8; ok('requirements pinned')
except Exception as e: bad('requirements pinned', e)

# 7. email renders with track record (stdlib only)
try:
    sys.path.insert(0, ROOT)
    from email_report import generate_full_report
    h = {'ticker': 'X', 'tier': 'T1', 'status': 'ACTIVE', 'company_name': 'X', 'position_size_pct': 5,
         'return_5yr_cagr': 9.7, 'return_10yr_cagr': 12.4, 'max_drawdown': -31,
         'long_term_alpha_pp': -5.1, 'long_term_note': 'lagged QQQ'}
    html, _ = generate_full_report({'screened_candidates': []}, {'holdings': [h]}, {})
    assert 'Track Record' in html; ok('email track record')
except Exception as e: bad('email track record', e)

print('\n' + ('ALL PASSED' if not fails else f'{len(fails)} FAILED: {fails}'))
sys.exit(1 if fails else 0)
