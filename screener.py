#!/usr/bin/env python3
"""
Long-Term Investment Screener v2.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Autonomous monthly screener for T1/T2/T3 stock classification.
Runs via GitHub Actions on the 1st of every month at 08:00 UTC.

v2.0 additions:
  - Step 3.5: Technicals (200MA, 52-week range, 1yr vs QQQ)
  - Step 3.5: Sentiment (Finnhub news, Reddit public API, SEC 8-K)
  - Claude research prompt enriched with sentiment context
  - Empty portfolio fallback to trial email
  - Bug fixes: company_name, thesis field, scenario tracking
  - Free NVIDIA NIM LLM integration
  - Sentiment confidence check
  - Moat lie detector
  - Scenario hallucination cap (cached + new)
  - Market cap & revenue stored for email display
  - Configurable scenario caps, D/E sanity, 10‑K highlights storage
  - Robust number parsing & forced scenario sanitisation
"""

from email_builder import generate_action_email, generate_exit_email, generate_trial_email
from email_report import generate_full_report
from research_metrics import compute_all_metrics, MEGATRENDS
from edgar_fundamentals import compute_trajectory, cross_check_yahoo, fetch_customer_concentration, get_stockholders_equity
from ipo_monitor import run_ipo_monitor, get_ipo_watchlist_summary, get_eligible_for_screening
from quarterly_review import run_quarterly_review, print_score_report
import os, json, time, pickle, logging, ssl, smtplib, re
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
import requests
import pandas as pd
import yfinance as yf
from llm_client import research_stock, call_llm

# ── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger('longterm')

# ── CONFIGURATION ──────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
FINNHUB_API_KEY   = os.environ.get('FINNHUB_API_KEY', '')
EMAIL_SENDER      = os.environ.get('GMAIL_SENDER', '')
EMAIL_PASSWORD    = os.environ.get('GMAIL_PASSWORD', '')
EMAIL_RECIPIENT   = os.environ.get('EMAIL_RECIPIENT', '')
EMAIL_CC_LIST     = []   # loaded from config — see _load_screening_config()
EMAIL_BCC_LIST    = []   # loaded from config — see _load_screening_config()
RUN_MODE          = os.environ.get('RUN_MODE', 'MONTHLY').upper()

BASE_DIR         = Path(__file__).parent
PORTFOLIO_FILE   = BASE_DIR / 'data' / 'portfolio.json'
KB_FILE          = BASE_DIR / 'data' / 'knowledge_base.json'
SCENARIOS_DIR    = BASE_DIR / 'data' / 'scenarios'
THESES_DIR       = BASE_DIR / 'data' / 'theses'
CKPT_DIR         = BASE_DIR / 'data' / 'checkpoints'
CONFIG_FILE      = BASE_DIR / 'universe_config.json'
BAD_SYMBOLS_FILE      = BASE_DIR / 'data' / 'bad_symbols.txt'
CONGRESS_CACHE_FILE   = BASE_DIR / 'data' / 'congress_disclosures_cache.json'
CONGRESS_CACHE_TTL    = 3   # days between re-fetches

for d in [BASE_DIR / 'data', SCENARIOS_DIR, THESES_DIR, CKPT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── ALL THRESHOLDS LOADED FROM universe_config.json ─────────────────────────
# No thresholds hardcoded here. Edit universe_config.json to change any value.

EXCLUDE_SIC_CODES = {6500, 6512, 6552, 6798, 6726, 6199}
EXCLUDE_PATTERNS  = []   # loaded from config in _load_screening_config()
_CFG: dict = {}          # populated on first load_config() call

def _load_screening_config() -> None:
    """Load all screening thresholds from universe_config.json into globals."""
    global _CFG, EXCLUDE_PATTERNS, EMAIL_CC_LIST, EMAIL_BCC_LIST, EMAIL_RECIPIENT, FIF_THRESHOLD
    cfg = load_config()
    _CFG = cfg

    EXCLUDE_PATTERNS = cfg.get('universe', {}).get('exclude_patterns', ['-W','-UN','-R','BULL','BEAR'])

    # Email settings from config (override env if config has them)
    email_cfg = cfg.get('email', {})
    EMAIL_CC_LIST[:]  = email_cfg.get('cc', [])
    EMAIL_BCC_LIST[:] = email_cfg.get('bcc', [])
    if not EMAIL_RECIPIENT and email_cfg.get('recipient'):
        EMAIL_RECIPIENT = email_cfg['recipient']

    # FIF threshold from config
    FIF_THRESHOLD = cfg.get('nz_fif', {}).get('threshold_nzd')

FIF_THRESHOLD = None   # NZD — populated from config by _load_screening_config()

def _c(section: str, key: str, default=None):
    """Read a flat config value: _c('email','recipient')"""
    return _CFG.get(section, {}).get(key, default)

def _cn(default=None, *keys):
    """Read a nested config value safely."""
    d = _CFG
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    return d

def _cs(tier: str, key: str, default=None):
    """Read a stock screening threshold: _cs('t1','min_market_cap')"""
    return _CFG.get('stock_screening', {}).get(tier, {}).get(key, default)

def _cu(key: str, default=None):
    """Read a universal stock screening value."""
    return _CFG.get('stock_screening', {}).get('universal', {}).get(key, default)

def _ce(tier: str, key: str, default=None):
    """Read an ETF screening threshold."""
    return _CFG.get('etf_screening', {}).get(tier, {}).get(key, default)

# ── HELPER: PARSE NUMBERS FROM LLM (robust) ──────────────────────────────────
def parse_number_from_llm(value) -> float:
    """
    Convert LLM output like '100.0T', '$50B', '10,000', or 123.4 to billions.
    Returns float in billions.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().upper()
    # Remove $, commas
    s = s.replace('$', '').replace(',', '')
    # Extract multiplier
    multiplier = 1.0
    if s.endswith('T'):
        multiplier = 1000.0   # trillions → billions
        s = s[:-1]
    elif s.endswith('B'):
        multiplier = 1.0
        s = s[:-1]
    elif s.endswith('M'):
        multiplier = 0.001
        s = s[:-1]
    try:
        return float(s) * multiplier
    except ValueError:
        return 0.0

def sanitize_scenario(scenario: dict, ticker: str, current_mkt_cap_b: float, tier: str, sector: str) -> dict:
    """
    Force-sanitise a scenario dictionary:
      - Parse mktcap_10yr_b and revenue_10yr_b using robust parser.
      - Apply relative cap (max_multiple of current, then cap_multiple)
      - Apply absolute global cap (configurable)
      - Apply sector-specific caps (configurable)
      - Clamp negative values to a small positive.
    Returns the mutated scenario dict.
    """
    if not scenario:
        return scenario

    # Read caps from config (with fallbacks)
    max_multiple = _cn(15, 'scenario_sanity', 'max_multiple_of_current')
    cap_multiple = _cn(8, 'scenario_sanity', 'cap_multiple')
    abs_max_b    = _cn(500, 'scenario_sanity', 'absolute_max_market_cap_b')

    # Sector overrides (can be placed in config under scenario_sanity.sector_caps)
    sector_caps = _cn({}, 'scenario_sanity', 'sector_caps')
    sector_max = sector_caps.get(sector, abs_max_b)

    # Case-specific multipliers so bull/base/bear caps are always differentiated
    _case_multipliers = {'bull': 1.0, 'base': 0.6, 'bear': 0.3}

    for case in ['bull', 'base', 'bear']:
        if case not in scenario:
            continue

        _mult = _case_multipliers[case]

        # --- Market cap ---
        raw = scenario[case].get('mktcap_10yr_b', 0)
        proj = parse_number_from_llm(raw)

        # Fallback for zero / negative
        if proj <= 0:
            proj = max(0.5, current_mkt_cap_b * 0.1)

        # Apply sector cap (case-scaled so bear < base < bull)
        case_sector_max = sector_max * _mult
        if proj > case_sector_max:
            log.warning(f'{ticker} {case} mkt cap {proj:.1f}B capped to sector max {case_sector_max:.1f}B')
            proj = case_sector_max

        # Apply relative cap (case-scaled)
        if current_mkt_cap_b > 0 and proj > current_mkt_cap_b * max_multiple * _mult:
            proj = current_mkt_cap_b * cap_multiple * _mult
            log.warning(f'{ticker} {case} relative cap applied: {proj:.1f}B (was {raw})')

        # Apply absolute global cap (case-scaled)
        if proj > abs_max_b * _mult:
            proj = abs_max_b * _mult

        scenario[case]['mktcap_10yr_b'] = proj

        # --- Revenue (if present) ---
        if 'revenue_10yr_b' in scenario[case]:
            rev_raw = scenario[case]['revenue_10yr_b']
            rev = parse_number_from_llm(rev_raw)
            if rev <= 0:
                rev = proj * 0.5
            # Revenue cannot exceed 2× market cap in long term (very generous)
            if rev > proj * 2:
                rev = proj * 2
            scenario[case]['revenue_10yr_b'] = rev

    return scenario

# ── CHECKPOINT SYSTEM ─────────────────────────────────────────────────────────
def save_checkpoint(step: int, data) -> None:
    path = CKPT_DIR / f'step_{step}.pkl'
    with open(path, 'wb') as f:
        pickle.dump(data, f)
    log.info(f'  ✓ Checkpoint step {step} saved')

def load_checkpoint(step: int):
    path = CKPT_DIR / f'step_{step}.pkl'
    if path.exists():
        with open(path, 'rb') as f:
            data = pickle.load(f)
        log.info(f'  ⚡ Resuming from step {step} checkpoint')
        return data
    return None

def clear_checkpoints() -> None:
    for f in CKPT_DIR.glob('step_*.pkl'):
        f.unlink()
    log.info('  Checkpoints cleared')

# ── DATA MANAGEMENT ───────────────────────────────────────────────────────────
def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}

def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2, default=str)

def load_portfolio() -> dict:   return load_json(PORTFOLIO_FILE)
def save_portfolio(p: dict):
    p['last_updated'] = datetime.now().isoformat()
    save_json(PORTFOLIO_FILE, p)
def load_kb() -> dict:          return load_json(KB_FILE)
def save_kb(kb: dict):
    kb['last_updated'] = datetime.now().isoformat()
    save_json(KB_FILE, kb)
def load_config() -> dict:      return load_json(CONFIG_FILE)
def load_scenario(t: str):      return load_json(SCENARIOS_DIR / f'{t}.json')
def save_scenario(t: str, d):   save_json(SCENARIOS_DIR / f'{t}.json', d)
def load_thesis(t: str):        return load_json(THESES_DIR / f'{t}.json')
def save_thesis(t: str, d):     save_json(THESES_DIR / f'{t}.json', d)

# ── STEP 1: UNIVERSE BUILDER ──────────────────────────────────────────────────
def build_universe(config: dict) -> list:
    log.info('Step 1/7: Building universe...')
    tickers = set()
    for exchange in ['nasdaq', 'nyse', 'amex']:
        try:
            resp = requests.get(
                f'https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=5000&exchange={exchange}',
                headers={'Accept': 'application/json', 'User-Agent': 'Mozilla/5.0'},
                timeout=30
            )
            if resp.status_code == 200:
                rows = resp.json().get('data', {}).get('table', {}).get('rows', [])
                batch = {r['symbol'] for r in rows if r.get('symbol')}
                tickers.update(batch)
                log.info(f'  NASDAQ API ({exchange.upper()}): {len(batch):,} tickers')
        except Exception as e:
            log.warning(f'  NASDAQ API ({exchange}) failed: {e}')
    try:
        resp = requests.get(
            'https://www.sec.gov/files/company_tickers.json',
            headers={'User-Agent': 'LongTermScreener vishvesh.niyati@gmail.com'},
            timeout=30
        )
        if resp.status_code == 200:
            sec_tickers = {v['ticker'] for v in resp.json().values() if v.get('ticker')}
            tickers.update(sec_tickers)
            log.info(f'  SEC EDGAR: {len(sec_tickers):,} tickers')
    except Exception as e:
        log.warning(f'  SEC EDGAR failed: {e}')

    # User custom tickers (from config — not hardcoded picks)
    tickers.update(config.get('user_custom', []))
    tickers -= set(config.get('blacklist', []))
    tickers = {
        t.strip().upper() for t in tickers
        if t and isinstance(t, str) and 1 <= len(t.strip()) <= 5
    }
    tickers = {
        t for t in tickers
        if not any(p in t for p in EXCLUDE_PATTERNS)
        and not t.endswith(('.A','.B','.C','.WS','.RT','.UN'))
    }
    portfolio = load_portfolio()
    for ipo in portfolio.get('ipo_pipeline', []):
        if ipo.get('status') == 'COOLING' and ipo.get('ticker'):
            ipo_date     = datetime.fromisoformat(ipo['s1_filed_date'])
            cooling_done = datetime.now() > ipo_date + timedelta(days=ipo['cooling_days'])
            if not cooling_done:
                tickers.discard(ipo['ticker'])
    result = sorted(tickers)
    log.info(f'  Universe ready: {len(result):,} tickers')
    return result

# ── STEP 2: DATA FETCHER ──────────────────────────────────────────────────────
def _log_bad_symbol(ticker: str, reason: str) -> None:
    log.warning(f'  Bad symbol {ticker}: {reason}')
    try:
        os.makedirs('data', exist_ok=True)
        with open('data/bad_symbols.txt', 'a') as f:
            f.write(f'{ticker}\t{reason}\n')
    except Exception:
        pass

def fetch_with_retry(ticker: str, retries: int = 3) -> tuple:
    for attempt in range(retries):
        try:
            data  = yf.Ticker(ticker).info
            price = data.get('regularMarketPrice') or data.get('currentPrice') or data.get('previousClose')
            qt    = data.get('quoteType', '')
            if not data or price is None or price <= 0:
                _log_bad_symbol(ticker, 'no price or empty info')
                return ticker, {}, 'FAILED'
            if qt not in ('EQUITY', 'ETF', ''):
                _log_bad_symbol(ticker, f'quoteType={qt}')
                return ticker, {}, 'FAILED'
            time.sleep(1.2)   # Yahoo Finance courtesy delay
            return ticker, data, 'OK'
        except Exception as e:
            err = str(e)
            if '404' in err or 'Not Found' in err or 'not found' in err.lower():
                _log_bad_symbol(ticker, f'404: {err[:120]}')
                return ticker, {}, 'FAILED'
            if attempt < retries - 1:
                time.sleep(2.0)
                continue
            log.debug(f'  Skipping {ticker}: {err}')
            return ticker, {}, 'FAILED'
    return ticker, {}, 'FAILED'

def _batch_download_prices(batch: list):
    """Download prices for a batch of tickers. Returns (hist, survivors_count)."""
    try:
        hist = yf.download(
            ' '.join(batch), period='5d', interval='1d',
            progress=False, auto_adjust=True, threads=True
        )
        return hist
    except Exception as e:
        log.debug(f'  Batch download error: {e}')
        return None


def _tickers_from_hist(hist, batch: list) -> list:
    """Extract tickers with valid prices from a yfinance history dataframe."""
    if hist is None or hist.empty:
        return []
    found = []
    close = hist['Close'] if 'Close' in hist.columns else hist
    for ticker in batch:
        try:
            prices = close[ticker].dropna() if ticker in close.columns else pd.Series()
            if len(prices) > 0 and float(prices.iloc[-1]) > 0.10:
                found.append(ticker)
        except Exception:
            pass
    return found


def pre_filter_universe(universe: list) -> list:
    """
    Fast batch pre-filter using yfinance.download().
    Processes 50 tickers per batch (reduced from 200) to avoid Yahoo Finance rate limits.
    On rate-limit detection (>70% of batch fails), waits 45s and retries in mini-batches of 15.
    Reduces ~10,000 tickers to ~4,000-5,000 viable candidates.
    """
    _batch_sz      = _cn(50,   'sentiment_data', 'pre_filter_batch_size')
    _batch_sleep   = _cn(2.0,  'sentiment_data', 'pre_filter_sleep_seconds')
    _retry_sleep   = _cn(45,   'sentiment_data', 'pre_filter_retry_sleep_seconds')
    _rl_threshold  = _cn(0.70, 'sentiment_data', 'pre_filter_rate_limit_threshold')

    log.info(f'  Pre-filtering {len(universe):,} tickers via batch price check (batch={_batch_sz})...')
    survivors  = []
    batches    = [universe[i:i+_batch_sz] for i in range(0, len(universe), _batch_sz)]

    for i, batch in enumerate(batches):
        hist  = _batch_download_prices(batch)
        found = _tickers_from_hist(hist, batch)

        # Rate-limit detection: if >threshold% of batch returned no data, retry with delay
        miss_rate = (len(batch) - len(found)) / len(batch) if batch else 0
        if miss_rate > _rl_threshold and len(batch) > 10:
            log.debug(f'  Batch {i+1}: {miss_rate:.0%} miss — rate limit suspected, waiting {_retry_sleep}s...')
            time.sleep(_retry_sleep)
            already_found = set(found)
            missing = [t for t in batch if t not in already_found]
            for m_start in range(0, len(missing), 15):
                mini = missing[m_start:m_start + 15]
                mini_hist  = _batch_download_prices(mini)
                mini_found = _tickers_from_hist(mini_hist, mini)
                if mini_found:
                    found.extend(mini_found)
                else:
                    found.extend(mini)  # Conservative: don't drop valid tickers
                time.sleep(3)

        survivors.extend(found)

        if (i + 1) % 20 == 0:
            log.info(f'  Pre-filter: {(i+1)/len(batches)*100:.0f}% — {len(survivors):,} survivors so far')
        time.sleep(_batch_sleep)

    log.info(f'  Pre-filter complete: {len(survivors):,} viable from {len(universe):,}')
    return survivors


def fetch_all_fundamentals(universe: list) -> dict:
    """
    Two-pass fundamentals fetch.
    Pass 1: Fast batch price check — eliminates shells and dead tickers (~25 min)
    Pass 2: Slow .info fetch for viable tickers only — 1 worker, 1.2s delay (~1.5 hrs)
    Total: ~1.75 hours. Well within 3-hour GitHub Actions timeout.
    """
    log.info(f'Step 2/7: Fetching fundamentals — {len(universe):,} tickers (two-pass)')

    viable = pre_filter_universe(universe)
    log.info(f'  Viable after pre-filter: {len(viable):,} — saving {len(universe)-len(viable):,} slow fetches')

    results = {}
    failed  = 0
    total   = len(viable)

    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = {executor.submit(fetch_with_retry, t): t for t in viable}
        for i, future in enumerate(as_completed(futures)):
            ticker, info, status = future.result()
            if status == 'OK':
                results[ticker] = info
            else:
                failed += 1
            completed = i + 1
            if completed % 500 == 0 or completed == total:
                log.info(f'  Progress: {completed:,}/{total:,} ({completed/total*100:.1f}%) — {len(results):,} valid, {failed:,} skipped')
            if completed % 2000 == 0:
                save_checkpoint(2, results)

    log.info(f'  COMPLETE: {len(results):,} valid from {total:,} viable ({len(universe):,} universe)')
    return results

def is_excluded_instrument(ticker: str, info: dict) -> tuple:
    sic  = info.get('sectorKey', '') or ''
    if 'reit' in sic.lower():
        return True, 'REIT'
    name = (info.get('longName','') or info.get('shortName','')).lower()
    for p in ['2x','3x','ultra','inverse','leveraged','proshares','direxion']:
        if p in name:
            return True, f'LEVERAGED_ETF ({p})'
    if info.get('industry','') in ['Shell Companies','Blank Checks']:
        return True, 'SPAC'
    employees = info.get('fullTimeEmployees', 0) or 0
    revenue   = info.get('totalRevenue', 0) or 0
    rd        = info.get('researchAndDevelopment', 0) or 0
    if employees < 5 and revenue == 0 and rd == 0:
        return True, 'SHELL'
    return False, ''

# ── JPM HELPERS ───────────────────────────────────────────────────────────────
_FIN_STATEMENTS_CACHE: dict = {}

def fetch_financial_statement_fields(ticker: str) -> dict:
    """
    Fallback for balance-sheet/income-statement/cash-flow line items yfinance's
    '.info' endpoint no longer returns (confirmed 100% absent from .info across
    8 diverse large-caps): operatingIncome, totalAssets, current assets/
    liabilities, interestExpense, capitalExpenditures, researchAndDevelopment,
    effective tax rate. '.info' still works for most other fields (marketCap,
    grossMargins, totalRevenue, debtToEquity, etc.) - only these detailed
    statement-level items moved to separate DataFrame properties.

    Only call this lazily (after cheaper .info-based checks already ran) -
    each call is 3 extra yfinance requests, and yfinance has no documented
    rate limit but empirically throttles hard under sustained load (observed
    YFRateLimitError repeatedly in this pipeline's own logs), same class of
    restriction as any other free scraped endpoint here. Cached per ticker for
    the run since T1 then T2 gates may both need the same ticker's data.
    """
    if ticker in _FIN_STATEMENTS_CACHE:
        return _FIN_STATEMENTS_CACHE[ticker]

    def _latest(df, label):
        if df is None or df.empty or label not in df.index:
            return None
        v = df.loc[label, df.columns[0]]
        if v is None or (isinstance(v, float) and v != v):  # v != v is the NaN check
            return None
        return float(v)

    result = {}
    for attempt in range(2):
        try:
            t = yf.Ticker(ticker)
            bs, inc, cf = t.balance_sheet, t.income_stmt, t.cashflow
            result = {
                'totalAssets':             _latest(bs, 'Total Assets'),
                'totalCurrentAssets':      _latest(bs, 'Current Assets'),
                'totalCurrentLiabilities': _latest(bs, 'Current Liabilities'),
                'investedCapital':         _latest(bs, 'Invested Capital'),
                'operatingIncome':         _latest(inc, 'Operating Income'),
                'interestExpense':         _latest(inc, 'Interest Expense'),
                'effectiveTaxRate':        _latest(inc, 'Tax Rate For Calcs'),
                'capitalExpenditures':     _latest(cf, 'Capital Expenditure'),
                'researchAndDevelopment':  _latest(inc, 'Research And Development'),
            }
            time.sleep(1.2)  # Yahoo Finance courtesy delay, matching fetch_with_retry
            break
        except Exception as e:
            if attempt == 0:
                time.sleep(2.0)
                continue
            log.debug(f'  Financial statements fetch failed for {ticker}: {e}')
            result = {}
    _FIN_STATEMENTS_CACHE[ticker] = result
    return result


def compute_roic(info: dict, ticker: str = '') -> float:
    try:
        op_income  = info.get('operatingIncome', 0) or 0
        tax_rate_raw = info.get('effectiveTaxRate')
        tot_assets = info.get('totalAssets', 0) or 0
        curr_liab  = info.get('totalCurrentLiabilities', 0) or 0
        inv_cap    = 0.0

        # .info never has these (see fetch_financial_statement_fields docstring)
        # so this fallback fires for essentially every ticker that reaches here.
        if (not op_income or not tot_assets) and ticker:
            fin = fetch_financial_statement_fields(ticker)
            op_income  = op_income  or fin.get('operatingIncome') or 0
            tot_assets = tot_assets or fin.get('totalAssets') or 0
            curr_liab  = curr_liab  or fin.get('totalCurrentLiabilities') or 0
            inv_cap    = fin.get('investedCapital') or 0
            if tax_rate_raw is None:
                tax_rate_raw = fin.get('effectiveTaxRate')

        tax_rate = max(0.0, min(float(tax_rate_raw if tax_rate_raw is not None else 0.25), 0.50))
        if not inv_cap:
            # Fallback proxy when the direct 'Invested Capital' line is unavailable
            inv_cap = tot_assets - curr_liab
        if inv_cap > 0 and op_income != 0:
            return (op_income * (1 - tax_rate)) / inv_cap
    except Exception:
        pass
    return info.get('returnOnEquity', 0) or 0

def get_adv_usd(info: dict) -> float:
    try:
        vol   = info.get('averageVolume', 0) or info.get('averageDailyVolume10Day', 0) or 0
        price = info.get('regularMarketPrice', 0) or info.get('currentPrice', 0) or info.get('previousClose', 0) or 0
        return float(vol) * float(price)
    except Exception:
        return 0.0

def get_sector_gm_threshold(info: dict) -> float:
    """Sector-adjusted gross margin minimum. Thresholds and keywords read from config."""
    ctx         = (info.get('sector','') or '').lower() + ' ' + (info.get('industry','') or '').lower()
    gm_cfg      = _CFG.get('stock_screening', {}).get('sector_gm_thresholds', {})
    keywords    = gm_cfg.get('sector_keywords', {})
    thresholds  = {
        'retail_distribution':    gm_cfg.get('retail_distribution', 0.12),
        'industrial_manufacturing': gm_cfg.get('industrial_manufacturing', 0.18),
        'energy_materials':       gm_cfg.get('energy_materials', 0.18),
        'financial_banking':      gm_cfg.get('financial_banking', 0.15),
    }
    for sector_key, kws in keywords.items():
        if any(k in ctx for k in kws):
            return thresholds.get(sector_key, 0.30)
    return gm_cfg.get('default', 0.30)

def compute_debt_ratios(info: dict, ticker: str = '') -> dict:
    try:
        debt     = info.get('totalDebt', 0) or 0
        ebitda   = info.get('ebitda', 0) or 0
        interest = abs(info.get('interestExpense', 0) or 0)
        c_assets = info.get('totalCurrentAssets', 0) or 0
        c_liab   = info.get('totalCurrentLiabilities', 0) or 0

        # .info doesn't carry interestExpense or current assets/liabilities
        # anymore either (see fetch_financial_statement_fields) - without this,
        # 'coverage' always defaulted to the 999.0 "safe" sentinel and
        # 'curr_ratio' always defaulted to 2.0, meaning those two gate checks
        # could never actually fail for any ticker. Reuses the same cached
        # fetch compute_roic may have already made for this ticker.
        if (not interest or not c_liab) and ticker:
            fin = fetch_financial_statement_fields(ticker)
            if not interest:
                interest = abs(fin.get('interestExpense') or 0)
            if not c_assets:
                c_assets = fin.get('totalCurrentAssets') or 0
            if not c_liab:
                c_liab = fin.get('totalCurrentLiabilities') or 0

        # yfinance no longer exposes 'totalStockholderEquity'. Prefer its own
        # 'debtToEquity' (reported as a percentage, e.g. 79.5 == 0.795x), then
        # bookValue (equity PER SHARE) * sharesOutstanding for total equity in
        # dollars — using bookValue alone as if it were total equity produced a
        # units mismatch (debt in dollars / equity per-share) that always
        # exceeded the sentinel threshold, silently zeroing out every T1/T2
        # candidate. If Yahoo has neither, fall back to SEC EDGAR's filed
        # StockholdersEquity (authoritative, no rate limits, but a network call
        # — only worth it once Yahoo has already come up empty).
        yf_de = info.get('debtToEquity')
        if yf_de is not None and yf_de >= 0:
            de_ratio = round(yf_de / 100, 2)
        else:
            equity = (info.get('bookValue', 0) or 0) * (info.get('sharesOutstanding', 0) or 0)
            if equity < 1e6 and ticker:
                equity = get_stockholders_equity(ticker) or 0
            de_ratio = round(debt / equity, 2) if equity >= 1e6 else 999.0
        if de_ratio > 100:
            de_ratio = 999.0

        return {
            'de_ratio':   de_ratio,
            'coverage':   round((ebitda/interest) if interest > 0 else 999.0, 2),
            'curr_ratio': round((c_assets/c_liab) if c_liab  > 0 else 2.0,  2),
        }
    except Exception:
        return {'de_ratio': 0.0, 'coverage': 999.0, 'curr_ratio': 1.5}

def get_insider_ownership(info: dict) -> float:
    return float(info.get('heldPercentInsiders', 0) or 0)

def compute_dilution_rate(info: dict) -> float:
    try:
        shares  = info.get('sharesOutstanding', 0) or 0
        implied = info.get('impliedSharesOutstanding', 0) or 0
        floats  = info.get('floatShares', 0) or 0
        if shares > 0 and implied > shares: return (implied - shares) / shares
        if shares > 0 and floats  > shares: return (floats  - shares) / shares
    except Exception:
        pass
    return 0.0

def get_t3_factor_group(ticker: str, info: dict) -> str:
    """Map T3 holding to its correlated factor group. Groups loaded from config."""
    factor_groups = _CFG.get('t3_factor_groups', {})
    name = (info.get('longName','') or info.get('shortName','')).lower()
    desc = (info.get('longBusinessSummary','') or '')[:200].lower()
    ctx  = f"{name} {desc}"
    for group, keywords in factor_groups.items():
        if group.startswith('_'): continue
        if any(k.lower() in ctx for k in keywords):
            return group
    return 'other'


# ── EARNINGS QUALITY ──────────────────────────────────────────────────────────
def compute_earnings_quality(info: dict) -> str:
    """
    OCF / Net Income ratio.
    > 1.1  = CLEAN  — cash earnings exceed reported earnings
    0.8-1.1 = WATCH  — minor divergence, monitor
    < 0.8  = FLAG   — reported profit not converting to cash (red flag)
    """
    try:
        ocf = info.get('operatingCashflow', 0) or 0
        ni  = info.get('netIncomeToCommon', 0) or info.get('netIncome', 0) or 0
        if ni <= 0: return 'WATCH'
        ratio = ocf / ni
        if ratio >= 1.1:  return 'CLEAN'
        if ratio >= 0.8:  return 'WATCH'
        return 'FLAG'
    except Exception:
        return 'WATCH'

# ── SENTIMENT CLASSIFIER ──────────────────────────────────────────────────────
POSITIVE_KEYWORDS = [
    'record','beat','growth','revenue','partnership','contract','wins',
    'expansion','upgrade','strong','launch','milestone','approved','signed',
    'deal','demand','accelerat','surge','profit','guidance raised',
    'outperform','buy','overweight','raised','momentum'
]
NEGATIVE_KEYWORDS = [
    'miss','decline','cut','layoff','investigation','lawsuit','recall',
    'warning','downgrade','delay','cancel','fine','penalty','loss',
    'breach','hack','fraud','resign','fired','bankrupt','default',
    'reduce','below','concern','risk','sell','underperform','lowered'
]

def classify_sentiment(headlines: list, reddit_titles: list, sec_8k_count: int, tier: str = 'T2') -> dict:
    """
    Classify sentiment from news + Reddit sources.
    Returns sentiment labels (POSITIVE/NEGATIVE/NEUTRAL/MIXED)
    and SIGNAL vs NOISE verdict per tier.
    """
    def score_texts(texts):
        pos = neg = 0
        for text in texts:
            t = text.lower()
            for k in POSITIVE_KEYWORDS:
                if k in t: pos += 1; break
            for k in NEGATIVE_KEYWORDS:
                if k in t: neg += 1; break
        total = pos + neg
        if total == 0:          return 'NEUTRAL', pos, neg
        r = pos / total
        if r >= 0.70:           return 'POSITIVE', pos, neg
        if r <= 0.30:           return 'NEGATIVE', pos, neg
        return 'MIXED', pos, neg

    news_sent, np, nn = score_texts(headlines)
    red_sent,  rp, rn = score_texts(reddit_titles)

    total_pos = np + rp
    total_neg = nn + rn
    total     = total_pos + total_neg
    if total == 0:
        overall = 'NEUTRAL'
    elif total_pos / total >= 0.70:
        overall = 'POSITIVE'
    elif total_neg / total >= 0.70:
        overall = 'NEGATIVE'
    else:
        overall = 'MIXED'

    # SIGNAL: material event, negative sentiment, or T3 community milestone tracking
    # NOISE:  routine positive coverage on large caps, neutral activity
    if sec_8k_count > 0:
        signal = 'SIGNAL'
    elif overall == 'NEGATIVE':
        signal = 'SIGNAL'
    elif tier == 'T3' and overall in ('POSITIVE', 'MIXED'):
        signal = 'SIGNAL'
    elif overall == 'POSITIVE' and tier in ('T1', 'T2'):
        signal = 'NOISE'
    elif overall == 'NEUTRAL':
        signal = 'NOISE'
    else:
        signal = 'MIXED'

    # Extract key themes
    theme_map = {
        'AI demand':       ['ai ','artificial intelligence','machine learning','llm','gpu'],
        'Revenue beat':    ['beat','exceeded','revenue beat','earnings beat'],
        'Partnership':     ['partnership','deal','agreement','signed','contract'],
        'Regulatory':      ['fda','sec ','nrc','regulation','approval','licence','license'],
        'Layoffs':         ['layoff','cut jobs','reduce workforce','restructur'],
        'Product launch':  ['launch','new product','announced','release'],
        'Data centre':     ['data cent','cloud','hyperscal','server'],
        'Acquisition':     ['acqui','merger','takeover','buyout'],
        'Guidance':        ['guidance','outlook','forecast'],
        'Nuclear/Energy':  ['nuclear','reactor','nrc','micro-reactor'],
        'Space/Launch':    ['rocket','launch','satellite','orbit','neutron'],
        'Insider activity':['insider','ceo','executive','resign','appoint','depart'],
        'Competition':     ['competi','rival','market share','disrupt'],
    }
    all_text    = ' '.join(headlines + reddit_titles).lower()
    found_themes = [t for t, kws in theme_map.items() if any(k in all_text for k in kws)]

    return {
        'news_sentiment':    news_sent,
        'reddit_sentiment':  red_sent,
        'overall_sentiment': overall,
        'signal_or_noise':   signal,
        'key_themes':        found_themes[:4],
    }


def get_news_intelligence(ticker: str, company_name: str, headlines: list, reddit_titles: list, thesis: str = '') -> dict:
    """Use LLM to extract investor-grade intelligence from news + Reddit for a 20-year holder."""
    _max_items = _cn(30, 'sentiment_data', 'finnhub_headlines_for_llm') + _cn(15, 'sentiment_data', 'reddit_titles_for_llm')
    all_items = [h for h in (headlines + reddit_titles) if h][:_max_items]
    if not all_items:
        return {'_status': 'no_data'}
    try:
        from llm_client import call_llm
        all_text  = '\n'.join(f'• {h}' for h in all_items)
        thesis_ctx = f'\nInvestment thesis: {thesis[:200]}' if thesis else ''
        prompt = f"""You are a 20-year long-term investment analyst reviewing recent news for {ticker} ({company_name}).{thesis_ctx}

Recent news and community posts (last 30 days):
{all_text}

For a 20-YEAR investor, return ONLY valid JSON:
{{"thesis_impact":"STRENGTHENS|NEUTRAL|THREATENS","impact_reason":"one sentence why","key_insights":["specific insight with names/amounts (20 words max)","specific insight with names/amounts (20 words max)","specific insight with names/amounts (20 words max)"],"watch_flag":"specific catalyst or risk to watch, or empty string","sentiment_summary":"2-sentence summary of what market is focused on"}}"""
        result = call_llm(prompt, system='Long-term investment analyst. Return ONLY valid JSON.', max_tokens=450)
        if result['success'] and isinstance(result['data'], dict):
            return {**result['data'], '_status': 'ok'}
        err = result.get('error', 'unknown error')
        log.warning(f'  News intelligence failed for {ticker}: {err}')
        return {'_status': 'failed', '_error': str(err)[:150]}
    except Exception as e:
        log.warning(f'  News intelligence failed for {ticker}: {e}')
        return {'_status': 'failed', '_error': str(e)[:150]}


# ── STEP 3: SCREENING ─────────────────────────────────────────────────────────
def passes_t1_gate(info: dict, ticker: str = '') -> tuple:
    mkt_cap = info.get('marketCap', 0) or 0
    revenue = info.get('totalRevenue', 0) or 0
    ocf     = info.get('operatingCashflow', 0) or 0
    gm      = info.get('grossMargins', 0) or 0
    adv     = get_adv_usd(info)
    if adv     < _cs("t1","min_adv_usd",500_000):    return False, f'ADV ${adv/1e3:.0f}K < $500K'
    if mkt_cap < _cs("t1","min_market_cap",5_000_000_000):     return False, f'mktcap ${mkt_cap/1e9:.1f}B < $5B'
    if revenue < _cs("t1","min_revenue",500_000_000):    return False, f'revenue ${revenue/1e6:.0f}M < $500M'
    if ocf     < 0:                  return False, 'negative OCF'
    gm_min = get_sector_gm_threshold(info)
    if gm < gm_min:                  return False, f'GM {gm:.0%} < {gm_min:.0%}'
    roic = compute_roic(info, ticker)
    if roic < _cs("t1","min_roic",0.10):                  return False, f'ROIC {roic:.0%} < 10%'
    debt = compute_debt_ratios(info, ticker)
    if debt['de_ratio']  > _cs("t1","max_de_ratio",3.0): return False, f'D/E {debt["de_ratio"]:.1f}x > 3x'
    if 0 < debt['coverage'] < _cs("t1","min_interest_coverage",2.0): return False, f'coverage {debt["coverage"]:.1f}x < 2x'
    if debt['curr_ratio'] < _cs("t1","min_current_ratio",0.80):    return False, f'curr ratio {debt["curr_ratio"]:.1f}x < 0.8'
    score = 0
    if roic > 0.25:           score += 4
    elif roic > 0.15:         score += 2
    if gm > 0.60:             score += 2
    elif gm > 0.40:           score += 1
    if revenue > 5e9:         score += 2
    if ocf > revenue * 0.10:  score += 1
    if get_insider_ownership(info) > 0.05: score += 1
    return score >= _cs("t1","min_score",3), f'T1 score {score}/10 | ROIC {roic:.0%} | D/E {debt["de_ratio"]:.1f}x'

def passes_t2_gate(info: dict, ticker: str = '') -> tuple:
    mkt_cap  = info.get('marketCap', 0) or 0
    revenue  = info.get('totalRevenue', 0) or 0
    rev_grow = info.get('revenueGrowth', 0) or 0
    gm       = info.get('grossMargins', 0) or 0
    ocf      = info.get('operatingCashflow', 0) or 0
    cash     = info.get('totalCash', 0) or 0
    adv      = get_adv_usd(info)
    if adv     < _cs("t2","min_adv_usd",250_000): return False, f'ADV ${adv/1e3:.0f}K < $250K'
    if mkt_cap < _cs("t2","min_market_cap",500_000_000):  return False, f'mktcap ${mkt_cap/1e6:.0f}M < $500M'
    if revenue < _cs("t2","min_revenue",50_000_000): return False, f'revenue ${revenue/1e6:.0f}M < $50M'
    if rev_grow < _cs("t2","min_rev_growth",0.15):           return False, f'rev growth {rev_grow:.0%} < 15%'
    if gm < _cs("t2","min_gross_margin",0.35):                 return False, f'GM {gm:.0%} < 35%'
    monthly_burn = abs(ocf) / 12 if ocf < 0 else 0
    runway = (cash / monthly_burn) if monthly_burn > 0 else 999
    if runway < _cs("t2","min_cash_runway_months",12) and ocf < 0:   return False, f'only {runway:.0f}mo runway'
    debt = compute_debt_ratios(info, ticker)
    if debt['de_ratio'] > _cs("t2","max_de_ratio",5.0): return False, f'D/E {debt["de_ratio"]:.1f}x > 5x'
    if 0 < debt['coverage'] < 1.5:         return False, f'coverage {debt["coverage"]:.1f}x < 1.5x'
    score = 0
    if rev_grow > 0.30: score += 3
    if gm > 0.60:       score += 3
    elif gm > 0.50:     score += 2
    elif gm > 0.40:     score += 1
    if ocf > 0:         score += 2
    return score >= 3, f'T2 score {score}/8 | CAGR {rev_grow:.0%} | D/E {debt["de_ratio"]:.1f}x'

def passes_t3_gate(info: dict) -> tuple:
    mkt_cap   = info.get('marketCap', 0) or 0
    revenue   = info.get('totalRevenue', 0) or 0
    cash      = info.get('totalCash', 0) or 0
    ocf       = info.get('operatingCashflow', 0) or 0
    rd        = info.get('researchAndDevelopment', 0) or 0
    employees = info.get('fullTimeEmployees', 0) or 0
    adv       = get_adv_usd(info)
    if adv     < _cs("t3","min_adv_usd",100_000): return False, f'ADV ${adv/1e3:.0f}K < $100K'
    if mkt_cap < _cs("t3","min_market_cap",200_000_000):  return False, f'mktcap ${mkt_cap/1e6:.0f}M < $200M'
    monthly_burn = abs(ocf) / 12 if ocf < 0 else 0
    if monthly_burn > 0:
        runway = cash / monthly_burn
        if runway < _cs("t3","min_cash_runway_months",18): return False, f'only {runway:.0f}mo runway'
    elif revenue == 0 and cash < _cs('t3', 'min_cash_nzd', 10_000_000):
        return False, f'pre-revenue, cash ${cash/1e6:.1f}M insufficient'
    if revenue == 0 and rd == 0 and employees < 20:
        return False, 'no R&D, no revenue, <20 employees'
    dilution = compute_dilution_rate(info)
    if dilution > _cs("t3","max_dilution_rate",0.40): return False, f'dilution {dilution:.0%} > 40%'
    if revenue > 5_000_000:
        gm = info.get('grossMargins', 0) or 0
        if gm < _cs("t3","min_gross_margin_if_revenue",0.20): return False, f'GM {gm:.0%} < 20%'
    pre_rev  = revenue == 0 or revenue < 5_000_000
    dil_note = f' | ⚠ diluting {dilution:.0%}/yr' if dilution > _cs("t3","flag_dilution_rate",0.15) else ''
    ins_note = f' | founders {get_insider_ownership(info):.0%}' if get_insider_ownership(info) > 0.03 else ''
    return True, f'T3 PASS ({"pre-revenue" if pre_rev else "early-revenue"}){dil_note}{ins_note}'

def compute_t1_score(info: dict, ticker: str = '') -> float:
    roic  = compute_roic(info, ticker)
    gm    = info.get('grossMargins', 0) or 0
    rev   = info.get('totalRevenue', 0) or 0
    ocf   = info.get('operatingCashflow', 0) or 0
    score = min(roic * 100, 35) + min(gm * 40, 20) + min(rev / 1e9, 15) + min((ocf / max(rev,1)) * 30, 15)
    score += min(get_insider_ownership(info) * 30, 5)
    if compute_debt_ratios(info, ticker)['de_ratio'] > 2.0: score -= 5
    return round(score, 2)

def compute_t2_score(info: dict) -> float:
    score  = min((info.get('revenueGrowth', 0) or 0) * 60, 30)
    score += min((info.get('grossMargins', 0) or 0) * 40, 20)
    score += min(((info.get('marketCap', 0) or 0) / 1e9), 20)
    if (info.get('operatingCashflow', 0) or 0) > 0: score += 10
    return round(score, 2)

def compute_t3_score(info: dict) -> float:
    mkt_cap      = info.get('marketCap', 0) or 0
    cash         = info.get('totalCash', 0) or 0
    ocf          = info.get('operatingCashflow', 0) or 0
    rd           = info.get('researchAndDevelopment', 0) or 0
    rev          = max(info.get('totalRevenue', 1) or 1, 1)
    monthly_burn = abs(ocf) / 12 if ocf < 0 else 0
    runway       = (cash / monthly_burn) if monthly_burn > 0 else 99
    score  = min(mkt_cap / 1e8, 20) + min(runway * 0.4, 25) + min((rd/rev) * 10, 15)
    rev_gr = info.get('revenueGrowth', 0) or 0
    if rev_gr > 0: score += min(rev_gr * 20, 15)
    score += min(get_insider_ownership(info) * 30, 10)
    score -= min(compute_dilution_rate(info) * 50, 20)
    return round(max(score, 0), 2)

def run_screening(fundamentals: dict) -> dict:
    log.info('Step 3/7: Screening...')
    t1_cands, t2_cands, t3_cands, excl = {}, {}, {}, 0
    for ticker, info in fundamentals.items():
        excluded, _ = is_excluded_instrument(ticker, info)
        if excluded: excl += 1; continue
        if (info.get('marketCap', 0) or 0) < _cu("min_market_cap_absolute", 50_000_000): continue
        t1_pass, t1_reason = passes_t1_gate(info, ticker)
        if t1_pass:
            t1_cands[ticker] = {'tier':'T1','score':compute_t1_score(info, ticker),'reason':t1_reason,'info':info}
            continue
        t2_pass, t2_reason = passes_t2_gate(info, ticker)
        if t2_pass:
            t2_cands[ticker] = {'tier':'T2','score':compute_t2_score(info),'reason':t2_reason,'info':info}
            continue
        t3_pass, t3_reason = passes_t3_gate(info)
        if t3_pass:
            t3_cands[ticker] = {'tier':'T3','score':compute_t3_score(info),'reason':t3_reason,'info':info}
    log.info(f'  Excluded: {excl:,} | T1: {len(t1_cands)} | T2: {len(t2_cands)} | T3: {len(t3_cands)}')
    MAX = _cn(15, 'stock_screening', 'max_candidates_per_tier')
    def top_n(d, n): return dict(sorted(d.items(), key=lambda x: x[1]['score'], reverse=True)[:n])
    candidates = {}
    candidates.update(top_n(t1_cands, MAX))
    candidates.update(top_n(t2_cands, MAX))
    candidates.update(top_n(t3_cands, MAX))
    log.info(f'  Selected for research: {len(candidates)} candidates')
    return candidates

# ── STEP 3.5: TECHNICALS ──────────────────────────────────────────────────────
def fetch_technicals(ticker: str) -> dict:
    """
    Long-term relevant technicals only.
    200MA, 52-week range, 1-year return. No RSI/MACD — those are short-term noise.
    """
    try:
        # yfinance can silently return far fewer rows than requested under Yahoo
        # rate-limiting, with no error raised — a period='10y' request should give
        # ~2512 rows. Retry a couple of times before accepting a truncated result,
        # since this is usually transient throttling, not genuinely short history.
        close = None
        for attempt in range(3):
            hist = yf.Ticker(ticker).history(period='10y')
            if hist.empty or len(hist) < 50:
                return {}
            close = hist['Close']
            if len(close) >= 756 or attempt == 2:
                break
            log.warning(f'  {ticker}: got only {len(close)} rows on attempt {attempt+1}/3 '
                        f'(expected ~2512 for 10y) — retrying...')
            time.sleep(5)
        if len(close) < 756:
            log.warning(f'  {ticker}: requested 10y history but got only {len(close)} rows '
                        f'after 3 attempts — CAGR will be limited')
        current_price = float(close.iloc[-1])
        ma_200        = float(close.tail(200).mean()) if len(close) >= 200 else float(close.mean())
        above_200ma   = current_price > ma_200
        pct_from_200ma = round((current_price - ma_200) / ma_200 * 100, 1) if ma_200 else None
        hist_1yr      = close.tail(252)
        high_52w      = float(hist_1yr.max())
        low_52w       = float(hist_1yr.min())
        pct_from_high = round((current_price - high_52w) / high_52w * 100, 1)
        price_1yr_ago = float(hist_1yr.iloc[0]) if len(hist_1yr) > 0 else current_price
        return_1yr    = round((current_price - price_1yr_ago) / price_1yr_ago * 100, 1) if price_1yr_ago > 0 else 0.0
        ma_126        = float(close.tail(126).mean()) if len(close) >= 126 else float(close.mean())
        trend         = 'UP' if current_price > ma_126 else 'DOWN'

        # Multi-year history (long-term context) — CAGR per year held + max drawdown
        # Uses 250 trading days/yr (not 252) since yfinance's period='Ny' request
        # typically returns slightly fewer than N*252 rows (~2512 for '10y').
        def _cagr(years):
            n = years * 250
            if len(close) < n + 1:
                return None
            start = float(close.iloc[-n]); end = current_price
            if start <= 0:
                return None
            return round(((end / start) ** (1 / years) - 1) * 100, 1)
        return_3yr_cagr  = _cagr(3)
        return_5yr_cagr  = _cagr(5)
        return_10yr_cagr = _cagr(10)
        peak             = float(close.max())
        max_drawdown     = round((current_price - peak) / peak * 100, 1) if peak > 0 else None
        years_listed     = round(len(close) / 252, 1)
        try:
            currency = (yf.Ticker(ticker).fast_info.get('currency') or 'USD').upper()
        except Exception:
            currency = 'USD'
        return {
            'current_price': round(current_price, 2),
            'above_200ma':   above_200ma,
            'ma_200':        round(ma_200, 2),
            'high_52w':      round(high_52w, 2),
            'low_52w':       round(low_52w, 2),
            'pct_from_high': pct_from_high,
            'pct_from_200ma': pct_from_200ma,
            'return_1yr':    return_1yr,
            'return_3yr_cagr':  return_3yr_cagr,
            'return_5yr_cagr':  return_5yr_cagr,
            'return_10yr_cagr': return_10yr_cagr,
            'max_drawdown':  max_drawdown,
            'years_listed':  years_listed,
            'currency':      currency,
            'trend':         trend,
        }
    except Exception as e:
        log.warning(f'  Technicals failed for {ticker}: {e}')
        return {}

# ── STEP 3.5: SENTIMENT ───────────────────────────────────────────────────────
def fetch_finnhub_news(ticker: str) -> dict:
    """
    Fetch last 30 days of company news from Finnhub.
    Free tier: 60 calls/min. Returns headlines for Claude context.
    """
    if not FINNHUB_API_KEY:
        return {}
    try:
        from_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        to_date   = datetime.now().strftime('%Y-%m-%d')
        resp = requests.get(
            'https://finnhub.io/api/v1/company-news',
            params={'symbol': ticker, 'from': from_date, 'to': to_date, 'token': FINNHUB_API_KEY},
            timeout=10
        )
        if resp.status_code != 200:
            return {}
        _fetch_n = _cn(20, 'sentiment_data', 'finnhub_articles_fetch')
        _llm_n   = _cn(15, 'sentiment_data', 'finnhub_headlines_for_llm')
        articles  = resp.json()[:_fetch_n]
        if not articles:
            return {'news_count': 0, 'headlines': []}
        headlines = [a.get('headline','') for a in articles if a.get('headline')]
        sources   = list(set(a.get('source','') for a in articles if a.get('source')))
        return {
            'news_count': len(articles),
            'headlines':  headlines[:_llm_n],
            'sources':    sources[:5]
        }
    except Exception as e:
        log.debug(f'  Finnhub failed for {ticker}: {e}')
        return {}

_REDDIT_BLOCK_WARNED = False   # log the 403/blocked-source warning once per run, not once per ticker

def fetch_reddit_mentions(ticker: str, company_name: str = '') -> dict:
    """
    Reddit mentions via public JSON API — no key required.
    Most useful for T3 moonshots where community tracks milestones.

    Reddit tightened anti-scraping enforcement after its 2023 API pricing
    changes and now returns 403 to unauthenticated .json requests from many
    cloud/datacenter IP ranges (confirmed live — same class of block as the
    Senate EFD source in fetch_congress_disclosures). This is a source-side
    restriction, not a bug — logged once per run rather than raised, since
    Reddit sentiment is a soft signal and the pipeline should keep going with
    an empty result.
    """
    global _REDDIT_BLOCK_WARNED
    headers    = {'User-Agent': 'LongTermScreener/2.0 (personal research tool)'}
    all_titles = []
    _posts_per_sub = _cn(15, 'sentiment_data', 'reddit_posts_per_subreddit')
    _titles_for_llm = _cn(15, 'sentiment_data', 'reddit_titles_for_llm')
    subreddits = ['investing', 'stocks', 'SecurityAnalysis']
    for sub in subreddits:
        try:
            resp = requests.get(
                f'https://www.reddit.com/r/{sub}/search.json',
                params={'q': ticker, 'sort': 'new', 'limit': _posts_per_sub, 't': 'month'},
                headers=headers, timeout=8
            )
            if resp.status_code == 200:
                posts = resp.json().get('data', {}).get('children', [])
                for p in posts:
                    title = p['data'].get('title', '')
                    if ticker.upper() in title.upper():
                        all_titles.append(title)
            elif resp.status_code == 403 and not _REDDIT_BLOCK_WARNED:
                log.warning('  Reddit: HTTP 403 — this IP range is blocked by Reddit\'s '
                            'anti-scraping policy, not a code issue. Reddit sentiment will '
                            'be empty for this run (further 403s suppressed).')
                _REDDIT_BLOCK_WARNED = True
            elif resp.status_code not in (200, 403) and not _REDDIT_BLOCK_WARNED:
                log.warning(f'  Reddit: unexpected HTTP {resp.status_code} for r/{sub} '
                            f'(further non-200s this run logged at debug only)')
            time.sleep(0.6)
        except Exception as e:
            log.debug(f'  Reddit fetch failed for r/{sub}/{ticker}: {e}')
    return {
        'reddit_mentions_30d': len(all_titles),
        'reddit_titles':       all_titles[:_titles_for_llm],
    }

_8K_ITEMS = {
    '1.01': 'Material agreement entered',
    '1.02': 'Material agreement terminated',
    '1.03': 'Bankruptcy or receivership',
    '2.01': 'Acquisition or disposition completed',
    '2.02': 'Results of operations / earnings',
    '2.03': 'Direct financial obligation created',
    '2.06': 'Material impairment',
    '3.01': 'Exchange delisting notice',
    '4.01': 'Auditor change',
    '5.01': 'Change in control',
    '5.02': 'Director/officer departure or appointment',
    '5.03': 'Amendment to articles/bylaws',
    '7.01': 'Regulation FD disclosure',
    '8.01': 'Other material event',
    '9.01': 'Financial statements attached',
}

def _clean_filing_text(raw: str) -> str:
    """Strip HTML tags, HTML entities, and collapse whitespace from filing text."""
    import html
    text = re.sub(r'<[^>]+>', ' ', raw)
    text = html.unescape(text)            # convert &#8220; → " etc.
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def _fetch_8k_text(cik: str, accession: str, primary_doc: str) -> str:
    """
    Fetch 8-K text. For earnings filings, also fetches Exhibit 99.1 (press release)
    which contains the actual revenue/EPS numbers the main 8-K body only references.
    """
    headers = {'User-Agent': 'LongTermScreener vishvesh.niyati@gmail.com'}
    acc_nodash = accession.replace('-', '')
    base_url   = f'https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}'

    # 1. Primary 8-K document (always fetch, use as baseline)
    primary_text = ''
    try:
        resp = requests.get(f'{base_url}/{primary_doc}', headers=headers, timeout=20)
        if resp.status_code == 200:
            primary_text = _clean_filing_text(resp.text)
    except Exception:
        pass

    # 2. Try to find Exhibit 99.1 via the EDGAR filing index HTML
    exhibit_text = ''
    try:
        idx_url  = f'{base_url}/{accession}-index.htm'
        idx_resp = requests.get(idx_url, headers=headers, timeout=10)
        if idx_resp.status_code == 200:
            # Strategy 1: parse table row-by-row — find a row containing EX-99
            # and extract the first htm/txt Archive link within that row.
            # This handles non-standard exhibit filenames (e.g. "pressrelease3312026.htm")
            ex_url = ''
            rows = re.findall(r'<tr[^>]*>.*?</tr>', idx_resp.text, re.IGNORECASE | re.DOTALL)
            for row in rows:
                if re.search(r'EX-?99', row, re.IGNORECASE):
                    # Try direct /Archives link first
                    m = re.search(r'href="(/Archives/edgar/data/[^"]+\.(?:htm|txt))"', row, re.IGNORECASE)
                    if not m:
                        # Fallback: strip /ix?doc= XBRL viewer prefix
                        m = re.search(r'href="/ix\?doc=(/Archives/edgar/data/[^"]+\.htm)"', row, re.IGNORECASE)
                    if m:
                        ex_url = 'https://www.sec.gov' + m.group(1)
                        break
            # Strategy 2: filename pattern fallback (ex99, ex-99, dex991, etc.)
            if not ex_url:
                m2 = re.search(r'href="(/Archives/edgar/data/[^"]*ex[-_d]?99[^"]*\.(?:htm|txt))"',
                               idx_resp.text, re.IGNORECASE)
                if m2:
                    ex_url = 'https://www.sec.gov' + m2.group(1)
            if ex_url:
                ex_matches = [ex_url]
            else:
                ex_matches = []
            if ex_matches:
                ex_url = ex_matches[0]
                if ex_url.startswith('/'):
                    ex_url = 'https://www.sec.gov' + ex_url
                ex_resp = requests.get(ex_url, headers=headers, timeout=15)
                if ex_resp.status_code == 200:
                    exhibit_text = _clean_filing_text(ex_resp.text)
    except Exception:
        pass

    if exhibit_text:
        # Exhibit has the actual numbers — lead with it, append primary for context
        combined = exhibit_text[:3500] + '\n\n' + primary_text[:1000]
    else:
        combined = primary_text[:4000]

    return combined.strip()

def _extract_8k_highlights(ticker: str, filing_date: str, text: str) -> list:
    """Use LLM to extract up to 7 investor-relevant points from 8-K text."""
    if not text:
        return []
    try:
        from llm_client import call_llm
        prompt = f"""Extract investor-relevant facts from this SEC 8-K filing for {ticker} (filed {filing_date}).

CRITICAL RULE: Only state facts that are EXPLICITLY written in the filing text below.
Do NOT estimate, infer, calculate, or assume any number or fact not directly stated in the text.
If a number is not in the text, do not write it.

Extract up to 7 highlights in this priority order:
1. ACTUAL REPORTED results first — revenue, EPS, net income, margins for the period just ended (not forecasts)
2. Forward guidance — next quarter revenue/margin outlook, only if actual results already captured
3. CEO/CFO changes — exact name, effective date, new/old role (only if stated)
4. M&A, contracts, deals — exact amounts and counterparties as written
5. Capital raises or debt changes — exact amounts and terms as written
6. Regulatory actions, lawsuits — as described in the filing
7. Strategic announcements — only what is explicitly stated

Additional rules:
- Skip SEC legal boilerplate (Exchange Act references, "furnished vs filed" disclaimers, party definitions)
- Skip director election vote counts (e.g. "Votes For: 216,983,424") — if the filing only contains annual meeting votes, write "Annual meeting: routine director elections and auditor ratification only."
- Keep each highlight to one concise sentence — do not write one long paragraph as a single bullet
- For credit amendments: summarize as "Reduced interest rate by X bps; increased LC sublimit to $Y" not the full legal text
- Mark material risks with [RISK]
- If a detail is unclear or not in the text, omit it entirely rather than guess

Return JSON: {{"highlights": ["sentence 1", "sentence 2", ...]}}

Filing content:
{text}"""

        NOISE_PHRASES = [
            # Negative / nothing-happened statements
            'no m&a', 'no regulatory', 'no ceo', 'ceo unchanged', 'no strategic',
            'no guidance', 'no material', 'no capital raises', 'no debt', 'no earnings',
            'no lawsuits', 'no acquisitions', 'no major deals', 'no mergers',
            'was not reported', 'were not disclosed', 'were not provided',
            'did not provide', 'did not disclose', 'did not announce', 'did not mention',
            'did not report any material', 'has not announced', 'not announced any',
            # Conference-only filings
            'is furnishing the information', 'incorporated by reference in this item',
            'is not a new development',
            # SEC legal boilerplate
            'shall not be deemed', 'securities exchange act', 'regulation s',
            'not subject to the liabilities', 'not incorporated by reference',
            'furnished information', 'pursuant to item', 'pursuant to regulation',
            'is not an emerging growth company', 'extended transition period',
            'section 13(a) of the exchange act',
            # Corporate boilerplate
            'principal executive offices are located', 'common stock is listed',
            'incorporated on', 'fiscal year ending on december', 'fiscal year ending on',
            # Director vote counts from proxy exhibits
            'votes for', 'votes withheld', 'broker non-votes', 'shares were represented',
            'constituted a quorum', 'shareholders were asked to vote',
            'no changes to the ceo', 'no cfo change', 'no explicit', 'no specific risks',
            # Securities offering / forward-looking statement boilerplate
            'there can be no assurance', 'undertakes no obligation to update',
            'not been registered under the securities act', 'may not be offered or sold',
            'absent registration or an applicable exemption',
            'forward-looking statements', 'changes in circumstances',
            # Affiliate / related-party boilerplate
            'commercial financial arrangements with certain of its affiliates',
            # Remaining negatives and meta-statements
            'no specific material risks', 'no changes in ceo', 'no changes in cfo',
            'no ceo/cfo', 'no changes to ceo', 'risks include risks relating',
            'but the actual numbers are not provided', 'numbers are not provided in',
            'specific numbers are not provided', 'not provided in the filing text',
            'not provided in the text', 'no highlights available',
            'not explicitly stated in the filing', 'omitting.',
            'but the actual revenue amount is not stated',
            'but the actual numbers are not stated',
            'annual report contains consolidated statements',
            'annual report also contains parent company',
            'no forward guidance, m&a, contracts',
            'about cmb.tech', 'is one of the largest listed',
            'does not provide actual reported results',
            'no reported results for the period',
            'no actual reported results',
            'no forward guidance or next quarter',
            'is available on the company',
            'annual report can be downloaded',
            'issued a press release announcing its financial results',
            'shareholders can request a hard copy',
            'annual report for the year ended',
            'questions should be directed to',
            'please visit our website', 'for more information, please visit',
            'contact:', 'chief executive officer,', 'chief financial officer,',
            # Marketing / brand slogans that slip through from company filings
            'is the gold investment that works', 'is the leading gold',
            'is debt-free and uses its free cash flow',
            'it trades under the symbol', 'trades under the symbol',
            # Administrative / future date announcements
            'announcement q', 'results will be announced', 'minutes of the agm',
            'will be published as soon as', 'on the millicom website',
            # Securities offering disclaimers
            'not and does not form part of any offer',
            'hedging transactions involving the securities',
            'all of the agm resolutions',
        ]

        ROUTINE_MEETING = 'annual meeting: routine director elections and auditor ratification only'

        def _extract(prompt_text):
            res = call_llm(prompt_text, system='Senior equity analyst. Return only valid JSON.',
                           max_tokens=800, model_override='meta/llama-3.1-8b-instruct')
            if res['success'] and isinstance(res.get('data'), dict):
                raw = res['data'].get('highlights', [])
                out = [str(p) for p in raw[:7] if p]
                out = [p for p in out if not any(ph in p.lower() for ph in NOISE_PHRASES)]
                return out
            return None

        pts = _extract(prompt)
        # Retry once if any point has [REDACTED] (model's inconsistent content filter)
        if pts is None or any('[REDACTED]' in p or '[redacted]' in p.lower() for p in (pts or [])):
            pts = _extract(prompt) or []
        # Drop [REDACTED] lines — better no point than broken data
        pts = [p for p in pts if '[REDACTED]' not in p and '[redacted]' not in p.lower()]
        # Strip "ITEM X.XX [DESCRIPTION]." prefixes left by EDGAR form headers
        item_prefix = re.compile(r'^ITEM\s+\d+\.\d+\s+[A-Z\s/;,]+\.\s*', re.IGNORECASE)
        pts = [item_prefix.sub('', p).strip() for p in pts]
        pts = [p for p in pts if p]  # drop any that became empty
        # Deduplicate identical sentences (LLM sometimes repeats)
        seen, deduped = set(), []
        for p in pts:
            key = p.strip().lower()
            if key not in seen:
                seen.add(key); deduped.append(p)
        pts = deduped
        # Drop "Annual meeting: routine..." if there are other real highlights
        real = [p for p in pts if ROUTINE_MEETING not in p.lower()]
        pts = real if real else pts[:1]  # keep it only if it's the only thing
        return pts
    except Exception as e:
        log.debug(f'_extract_8k_highlights {ticker}: {e}')
        return []

def extract_news_highlights(ticker: str, headlines: list) -> list:
    """Select up to 5 investor-relevant headlines verbatim — no inference or invented numbers."""
    if not headlines:
        return []
    try:
        from llm_client import call_llm
        numbered = '\n'.join(f'{i+1}. {h}' for i, h in enumerate(headlines[:15]))
        prompt = f"""You are filtering news headlines for {ticker}.

From the list below, pick the headline numbers that contain MATERIAL, COMPANY-SPECIFIC events.
Return ONLY the indexes of the most relevant headlines (up to 5).

INCLUDE if headline mentions:
- Earnings results, revenue, EPS, guidance
- CEO/CFO change, leadership appointment
- Acquisition, merger, major contract or deal
- Regulatory action, lawsuit, settlement
- Product launch, major partnership

EXCLUDE:
- Analyst upgrades/downgrades, price targets, ratings
- Generic market commentary not specific to {ticker}
- Conference appearances with no financial disclosures
- Index additions/removals

Headlines:
{numbered}

Return JSON: {{"selected": [1, 3, 5]}}  (list of 1-based headline numbers, empty list if none qualify)"""

        result = call_llm(prompt, system='Return only valid JSON. No commentary.',
                          max_tokens=200, model_override='meta/llama-3.1-8b-instruct')
        if result['success'] and isinstance(result.get('data'), dict):
            selected_idx = result['data'].get('selected', [])
            chosen = [headlines[i - 1] for i in selected_idx
                      if isinstance(i, int) and 1 <= i <= len(headlines)]
            # Drop any headline that doesn't mention the ticker — wrong company leaked in
            chosen = [h for h in chosen if ticker.upper() in h.upper()]
            # Drop technical-screen and non-material conference headlines
            _NEWS_NOISE = (
                'minervini', 'momentum screen', 'trend template',
                '- slideshow', 'shareholder/analyst call', 'high growth momentum',
            )
            chosen = [h for h in chosen if not any(n in h.lower() for n in _NEWS_NOISE)]
            return chosen
        return []
    except Exception as e:
        log.debug(f'extract_news_highlights {ticker}: {e}')
        return []


def fetch_sec_8k(ticker: str) -> dict:
    """
    Fetch recent 8-K filings using CIK-based lookup (company's own filings only).
    For the most recent filing, extracts 5 key investor-relevant highlights via LLM.
    """
    try:
        from edgar_fundamentals import _load_cik_map
        cik_map = _load_cik_map()
        cik = cik_map.get(ticker.upper())
        if not cik:
            return {'sec_8k_count': 0, 'sec_8k_events': [], 'sec_8k_highlights': [], 'sec_8k_latest_date': ''}

        cik_padded = str(cik).zfill(10)
        resp = requests.get(
            f'https://data.sec.gov/submissions/CIK{cik_padded}.json',
            headers={'User-Agent': 'LongTermScreener vishvesh.niyati@gmail.com'},
            timeout=15
        )
        if resp.status_code != 200:
            return {'sec_8k_count': 0, 'sec_8k_events': [], 'sec_8k_highlights': [], 'sec_8k_latest_date': ''}

        recent       = resp.json().get('filings', {}).get('recent', {})
        forms        = recent.get('form', [])
        dates        = recent.get('filingDate', [])
        items        = recent.get('items', [])
        accessions   = recent.get('accessionNumber', [])
        primary_docs = recent.get('primaryDocument', [])

        _ADMIN_PHRASES_8K = (
            'annual meeting: routine',
            're-appointed as auditor',
            'will arrange to mail paper copies',
            'annual report for the year ended',
            'does not provide actual reported results',
        )

        def _admin_only(hl: list) -> bool:
            """True only when hl has exactly 1 item that is a known admin phrase.
            Empty list is NOT admin-only — it means LLM failed on a real filing."""
            if not hl:
                return False
            return len(hl) == 1 and any(p in hl[0].lower() for p in _ADMIN_PHRASES_8K)

        # Try 90 days first; expand to 180 if no 8-K found
        _first_text_len = 0  # length of text fetched for first filing (detect image-only filings)
        for lookback_days in (90, 180):
            cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
            events, count = [], 0
            highlights, latest_date = [], ''
            _first_text_len = 0

            for i, form in enumerate(forms):
                if form in ('8-K', '6-K') and i < len(dates) and dates[i] >= cutoff:
                    count += 1
                    raw_items = (items[i] if i < len(items) else '') or ''
                    desc = ', '.join(
                        _8K_ITEMS.get(it.strip(), f'Item {it.strip()}')
                        for it in raw_items.split(',') if it.strip()
                    ) or 'Material event filed'

                    # Decide whether to attempt extraction on this filing:
                    # - Always try the first (most recent) filing
                    # - For filings 2-3: only fall through if first had POSITIVE admin content
                    #   OR first filing text was too short (image-only/stub), never just because LLM returned empty
                    if count == 1:
                        _should_extract = True
                    elif count <= 3:
                        _positive_admin = _admin_only(highlights)
                        _image_only_stub = not highlights and _first_text_len < 500
                        _should_extract = _positive_admin or _image_only_stub
                    else:
                        _should_extract = False

                    if _should_extract:
                        acc = accessions[i] if i < len(accessions) else ''
                        doc = primary_docs[i] if i < len(primary_docs) else ''
                        if acc and doc:
                            text = _fetch_8k_text(str(cik), acc, doc)
                            candidate = _extract_8k_highlights(ticker, dates[i], text)
                            if count == 1:
                                highlights = candidate
                                latest_date = dates[i]
                                # Use actual text length, UNLESS this is a pure meeting-vote or
                                # routine-report filing (items 5.07/8.01 only) — in that case
                                # force text_len=0 so the fallthrough triggers if LLM returns empty
                                _meeting_items = {'5.07', '8.01'}
                                _substantive_items = {'2.02', '4.02', '5.02', '1.01', '1.02',
                                                      '2.01', '2.06', '7.01', '8.02'}
                                _raw_item_set = {it.strip() for it in raw_items.split(',') if it.strip()}
                                if _raw_item_set and not (_raw_item_set - _meeting_items) and \
                                        not (_raw_item_set & _substantive_items):
                                    _first_text_len = 0  # annual meeting vote only — allow fallthrough
                                else:
                                    _first_text_len = len(text)
                            elif candidate and not _admin_only(candidate):
                                # Only upgrade to a later filing if it has genuinely better content
                                highlights = candidate
                                latest_date = dates[i]

                    if not latest_date and count == 1:
                        latest_date = dates[i]

                    if len(events) < 3:
                        events.append({'date': dates[i], 'description': desc})

            if count > 0:
                break  # found filings in this window — no need to expand

        return {
            'sec_8k_count':       count,
            'sec_8k_events':      events,
            'sec_8k_highlights':  highlights,
            'sec_8k_latest_date': latest_date,
        }
    except Exception as e:
        log.debug(f'fetch_sec_8k {ticker}: {e}')
        return {'sec_8k_count': 0, 'sec_8k_events': [], 'sec_8k_highlights': [], 'sec_8k_latest_date': ''}

def get_sentiment_confidence(ticker: str, thesis: str, filing_text: str, headlines: str, sec_8k_events: str) -> dict:
    prompt = f"""You are an investment risk analyst. A company has the following thesis and 10‑K risks. Recent news headlines and 8‑K events are also provided.

Thesis: {thesis}
10‑K Risks (from Item 1A): {filing_text[:2000]}

Recent news headlines: {headlines}
Recent 8‑K events: {sec_8k_events}

Question: Do any of these news items directly threaten the thesis? Answer with a single sentence explanation and a confidence score (1‑10, where 10 means "highly threatening to thesis" and 1 means "completely irrelevant"). Return ONLY valid JSON: {{"reason":"string","confidence_score":number}}"""

    system = "You are a risk analyst. Return ONLY valid JSON."
    result = call_llm(prompt, system=system, max_tokens=150)
    if result['success']:
        return result['data']
    return {'reason': 'Could not evaluate', 'confidence_score': 5}

def fetch_institutional_holders(ticker: str) -> dict:
    """Top-3 institutional and mutual fund holders from yfinance (quarterly data)."""
    try:
        t = yf.Ticker(ticker)
        inst_list, mf_list = [], []
        for df, lst in [(t.institutional_holders, inst_list), (t.mutualfund_holders, mf_list)]:
            if df is None or df.empty:
                continue
            for _, row in df.head(3).iterrows():
                # yfinance uses '% Out' or 'pctHeld' depending on version
                pct = row.get('% Out', row.get('pctHeld', None))
                name = str(row.get('Holder', row.get('Name', ''))).strip()
                if name:
                    lst.append({'name': name, 'pct': float(pct) if pct is not None else None})
        return {'institutional_holders': inst_list, 'mutualfund_holders': mf_list}
    except Exception as e:
        log.debug(f'  {ticker}: institutional fetch failed — {e}')
        return {'institutional_holders': [], 'mutualfund_holders': []}


def _doh_resolve_hostname(hostname: str) -> str | None:
    """
    Resolve hostname via Cloudflare DoH using urllib (no requests, no socket patching).
    Connects directly to 1.1.1.1 by IP so system DNS is never involved.
    """
    import urllib.request, ssl as _ssl, json as _json
    for doh_ip in ['1.1.1.1', '8.8.8.8']:
        try:
            url = f'https://{doh_ip}/dns-query?name={hostname}&type=A'
            req = urllib.request.Request(url, headers={'Accept': 'application/dns-json'})
            ctx = _ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode    = _ssl.CERT_NONE
            with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
                data = _json.loads(resp.read())
                for ans in data.get('Answer', []):
                    if ans.get('type') == 1:
                        return ans['data']
        except Exception as e:
            log.warning(f'  DoH via {doh_ip} failed for {hostname}: {type(e).__name__}: {e}')
            continue
    return None


def fetch_congress_disclosures() -> dict:
    """
    Download House and Senate stock transaction disclosures.
    Sources tried in order:
    1. housestockwatcher.com + senatestockwatcher.com (community aggregators, via DoH if
       needed). As of 2026 both are dead — verified via direct DoH query, they return
       NOERROR with zero A records, i.e. genuinely abandoned, not just DNS-blocked here.
    2. efdsearch.senate.gov (official Senate EFD search, Senate-only fallback — House has
       no equivalent official structured-data source). This site is live and resolves
       fine, but its Akamai WAF returns 403 "Access Denied" to traffic from cloud/
       datacenter IP ranges (confirmed here even with full browser headers; a control
       request to sec.gov from the same environment succeeds normally) — so this source
       may also fail from GitHub Actions runners. This is a source-side access
       restriction, not a bug in the request logic below.
    Returns {TICKER: [{"name","chamber","type","amount","date"}]} for the last 90 days.
    Cached locally for CONGRESS_CACHE_TTL days. Returns {} (not an exception) if every
    source is unavailable — callers already treat congressional data as optional.
    """
    if CONGRESS_CACHE_FILE.exists():
        age = (datetime.now() - datetime.fromtimestamp(CONGRESS_CACHE_FILE.stat().st_mtime)).days
        if age < CONGRESS_CACHE_TTL:
            try:
                return json.loads(CONGRESS_CACHE_FILE.read_text(encoding='utf-8'))
            except Exception:
                pass

    by_ticker: dict = {}
    cutoff     = datetime.now() - timedelta(days=90)
    cutoff_str = cutoff.strftime('%Y-%m-%d')
    today_str  = datetime.now().strftime('%Y-%m-%d')
    hdrs       = {'User-Agent': 'LongTermScreener vishvesh.niyati@gmail.com', 'Accept': 'application/json'}

    # Pre-resolve community site hostnames via DoH before touching socket
    import socket as _sock
    _congress_hosts = {
        'housestockwatcher.com':     None,
        'www.senatestockwatcher.com': None,
    }
    for _h in list(_congress_hosts):
        _ip = _doh_resolve_hostname(_h)
        if _ip:
            _congress_hosts[_h] = _ip
            log.info(f'  Congress DoH: {_h} → {_ip}')
        else:
            log.warning(f'  Congress DoH: could not resolve {_h}')

    _orig_getaddrinfo = _sock.getaddrinfo
    if any(_congress_hosts.values()):
        def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            ip = _congress_hosts.get(host)
            if ip:
                return _orig_getaddrinfo(ip, port, family, type, proto, flags)
            return _orig_getaddrinfo(host, port, family, type, proto, flags)
        _sock.getaddrinfo = _patched_getaddrinfo
        log.info('  Congress: socket patched with DoH-resolved IPs')

    try:
        # ── House (community aggregator) ──
        try:
            r = requests.get('https://housestockwatcher.com/api/transactions_flat.json', headers=hdrs, timeout=15)
            if r.ok:
                for tx in r.json():
                    tk = str(tx.get('ticker', '')).upper().strip()
                    if not tk or tk in ('--', 'N/A', 'NONE', ''):
                        continue
                    raw_date = tx.get('transaction_date') or tx.get('disclosure_date', '')
                    try:
                        tx_date = datetime.strptime(raw_date[:10], '%Y-%m-%d')
                    except Exception:
                        continue
                    if tx_date < cutoff:
                        continue
                    tx_type_raw = str(tx.get('type', '')).lower()
                    tx_type = 'Purchase' if 'purchase' in tx_type_raw else ('Sale' if 'sale' in tx_type_raw or 'sold' in tx_type_raw else tx_type_raw.title())
                    by_ticker.setdefault(tk, []).append({
                        'name': tx.get('representative', ''),
                        'chamber': 'House',
                        'type': tx_type,
                        'amount': tx.get('amount', ''),
                        'date': raw_date[:10],
                    })
            log.info(f'  Congress House: {sum(len(v) for v in by_ticker.values())} recent tx')
        except Exception as e:
            log.warning(f'  Congress House fetch failed: {e}')

        # ── Senate (community aggregator) ──
        try:
            r = requests.get('https://www.senatestockwatcher.com/api/transactions', headers=hdrs, timeout=15)
            if r.ok:
                data = r.json()
                txns = data if isinstance(data, list) else data.get('transactions', data.get('data', []))
                for tx in txns:
                    tk = str(tx.get('ticker', '')).upper().strip()
                    if not tk or tk in ('--', 'N/A', 'NONE', ''):
                        continue
                    raw_date = tx.get('transaction_date') or tx.get('transactionDate', '')
                    try:
                        tx_date = datetime.strptime(raw_date[:10], '%Y-%m-%d')
                    except Exception:
                        continue
                    if tx_date < cutoff:
                        continue
                    tx_type_raw = str(tx.get('type', '')).lower()
                    tx_type = 'Purchase' if 'purchase' in tx_type_raw or 'buy' in tx_type_raw else ('Sale' if 'sale' in tx_type_raw or 'sold' in tx_type_raw else tx_type_raw.title())
                    senator_name = tx.get('senator', '') or f"{tx.get('first_name','')} {tx.get('last_name','')}".strip()
                    by_ticker.setdefault(tk, []).append({
                        'name': senator_name,
                        'chamber': 'Senate',
                        'type': tx_type,
                        'amount': tx.get('amount', ''),
                        'date': raw_date[:10],
                    })
            log.info(f'  Congress community sites total: {sum(len(v) for v in by_ticker.values())} recent tx')
        except Exception as e:
            log.warning(f'  Congress Senate fetch failed: {e}')
    finally:
        _sock.getaddrinfo = _orig_getaddrinfo

    # ── Senate EFD fallback (official US Senate source) ──
    # Runs whenever the community Senate site returned nothing. As of 2026 both
    # community sites (housestockwatcher.com, senatestockwatcher.com) and their
    # underlying GitHub data mirror (last updated 2021) appear defunct — dead
    # DNS, no data. The previous fallback here pointed at efts.us.senate.gov,
    # which is NXDOMAIN and never existed; the actual official disclosure
    # system is a session/CSRF-protected search app at efdsearch.senate.gov,
    # not a plain JSON API. This reverse-engineers that flow (verified against
    # the documented approach used by github.com/neelsomani/senator-filings):
    # accept the site's click-through agreement to get a session + CSRF token,
    # POST to the search endpoint for PTR (Periodic Transaction Report)
    # filings, then fetch each electronically-filed report's HTML for the
    # actual per-transaction ticker/type/amount. Paper (scanned PDF) filings
    # are skipped — they aren't structured data.
    senate_count = sum(1 for txs in by_ticker.values() for t in txs if t.get('chamber') == 'Senate')
    if senate_count == 0:
        log.info('  Congress: Senate community site empty — trying official efdsearch.senate.gov...')
        try:
            from bs4 import BeautifulSoup
            sess = requests.Session()
            sess.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': 'https://efdsearch.senate.gov/search/'})
            home_url = 'https://efdsearch.senate.gov/search/home/'
            home = sess.get(home_url, timeout=20)
            if home.status_code == 403:
                raise RuntimeError(
                    'Akamai WAF blocked this request (HTTP 403) — efdsearch.senate.gov '
                    'is rejecting this IP range, not a code/header problem. Retrying '
                    'will not help; this needs a different egress IP.'
                )
            token_tag = BeautifulSoup(home.text, 'html.parser').find(attrs={'name': 'csrfmiddlewaretoken'})
            if not token_tag:
                raise RuntimeError('csrfmiddlewaretoken not found on landing page')
            csrf_token = token_tag['value']
            sess.post(home_url, data={'csrfmiddlewaretoken': csrf_token, 'prohibition_agreement': '1'}, timeout=20)
            csrf_token = sess.cookies.get('csrftoken', csrf_token)

            resp = sess.post('https://efdsearch.senate.gov/search/report/data/', data={
                'start': '0', 'length': '100',
                'report_types': '[11]',   # 11 = Periodic Transaction Report
                'filer_types': '[]',
                'submitted_start_date': cutoff.strftime('%m/%d/%Y 00:00:00'),
                'submitted_end_date': '',
                'candidate_state': '', 'senator_state': '', 'office_id': '',
                'first_name': '', 'last_name': '',
                'csrfmiddlewaretoken': csrf_token,
            }, timeout=20)
            rows = resp.json().get('data', []) if resp.ok else []
            log.info(f'  Congress Senate EFD: {len(rows)} PTR filings found since {cutoff_str}')

            for row in rows[:100]:
                try:
                    first, last, _, link_html, _date_received = row
                    link = BeautifulSoup(link_html, 'html.parser').a.get('href')
                except Exception:
                    continue
                if not link or link.startswith('/search/view/paper/'):
                    continue  # scanned PDF — not parseable as structured data
                try:
                    report = sess.get(f'https://efdsearch.senate.gov{link}', timeout=20)
                    tbodies = BeautifulSoup(report.text, 'html.parser').find_all('tbody')
                    if not tbodies:
                        continue
                    for tr in tbodies[0].find_all('tr'):
                        cols = [c.get_text(strip=True) for c in tr.find_all('td')]
                        if len(cols) < 8:
                            continue
                        tx_date_raw, ticker, _asset_name, asset_type, order_type, tx_amount = \
                            cols[1], cols[3], cols[4], cols[5], cols[6], cols[7]
                        ticker = ticker.strip().upper()
                        if asset_type.strip().lower() != 'stock' or not ticker or ticker in ('--', 'N/A'):
                            continue
                        try:
                            tx_date = datetime.strptime(tx_date_raw.strip(), '%m/%d/%Y')
                        except Exception:
                            continue
                        if tx_date < cutoff:
                            continue
                        order_lower = order_type.lower()
                        tx_type = 'Purchase' if 'purchase' in order_lower or 'buy' in order_lower else \
                                  ('Sale' if 'sale' in order_lower else order_type.title())
                        by_ticker.setdefault(ticker, []).append({
                            'name': f'{first} {last}'.strip(),
                            'chamber': 'Senate',
                            'type': tx_type,
                            'amount': tx_amount,
                            'date': tx_date.strftime('%Y-%m-%d'),
                        })
                    time.sleep(1)  # courtesy delay between filing detail fetches
                except Exception as e:
                    log.debug(f'  Senate EFD filing fetch failed for {link}: {e}')
                    continue
            new_senate = sum(1 for txs in by_ticker.values() for t in txs if t.get('chamber') == 'Senate')
            log.info(f'  Congress Senate EFD: {new_senate} Senate transactions added')
        except Exception as e:
            log.warning(f'  Congress Senate EFD failed: {e}')

    for tk in by_ticker:
        by_ticker[tk].sort(key=lambda x: x.get('date', ''), reverse=True)

    total = sum(len(v) for v in by_ticker.values())
    log.info(f'  Congress final: {total} transactions across {len(by_ticker)} tickers')

    # Only write cache when we actually got data — prevents a failed fetch
    # from poisoning the cache for 3 days
    if by_ticker:
        try:
            CONGRESS_CACHE_FILE.write_text(json.dumps(by_ticker), encoding='utf-8')
        except Exception:
            pass
    else:
        log.warning('  Congress: no data fetched — skipping cache write so next run retries')

    return by_ticker


def run_sentiment_technicals(candidates: dict, portfolio: dict) -> dict:
    """
    Step 3.5: Technicals + Sentiment for all candidates and existing holdings.
    Finnhub: 60 calls/min → 1 sec sleep between calls.
    Reddit: public API, 0.6s courtesy sleep.
    """
    log.info('Step 3.5/7: Technicals & Sentiment collection...')
    if not FINNHUB_API_KEY:
        log.warning('  FINNHUB_API_KEY not set — news headlines will be empty')

    all_tickers = set(candidates.keys())
    for h in portfolio.get('holdings', []):
        all_tickers.add(h['ticker'])

    # Fetch QQQ 1yr return once for relative strength
    qqq_return_1yr = 0.0
    try:
        qqq = yf.Ticker('QQQ').history(period='1y')
        if not qqq.empty:
            qqq_return_1yr = (float(qqq['Close'].iloc[-1]) - float(qqq['Close'].iloc[0])) / float(qqq['Close'].iloc[0]) * 100
        log.info(f'  QQQ 1yr return: {qqq_return_1yr:.1f}%')
    except Exception:
        pass

    total   = len(all_tickers)
    results = {}

    # Pre-build thesis lookup from existing holdings (new candidates have no thesis yet)
    existing_thesis = {h.get('ticker', ''): h.get('thesis_summary', '') for h in portfolio.get('holdings', [])}

    for i, ticker in enumerate(sorted(all_tickers)):
        log.info(f'  [{i+1}/{total}] {ticker}')

        tech = fetch_technicals(ticker)
        if tech and qqq_return_1yr:
            tech['return_vs_qqq_1yr'] = round(tech.get('return_1yr', 0) - qqq_return_1yr, 1)

        company_name = ''
        if ticker in candidates:
            info = candidates[ticker].get('info', {})
            company_name = info.get('longName', info.get('shortName', ''))

        news    = fetch_finnhub_news(ticker)
        reddit  = fetch_reddit_mentions(ticker, company_name)
        sec_8k  = fetch_sec_8k(ticker)
        holders = fetch_institutional_holders(ticker)

        # Classify combined sentiment
        all_headlines   = news.get('headlines', [])
        all_reddit      = reddit.get('reddit_titles', [])
        sec_8k_cnt      = sec_8k.get('sec_8k_count', 0)
        tier_for_signal = candidates[ticker]['tier'] if ticker in candidates else 'T2'
        classification  = classify_sentiment(all_headlines, all_reddit, sec_8k_cnt, tier_for_signal)

        # LLM-powered intelligence: extract named facts + 20-year thesis impact
        thesis_text  = existing_thesis.get(ticker, '')
        intelligence = get_news_intelligence(ticker, company_name, all_headlines, all_reddit, thesis_text)

        results[ticker] = {
            'technicals': tech,
            'sentiment':  {**news, **reddit, **sec_8k, **classification, 'news_intelligence': intelligence, **holders}
        }
        time.sleep(1.1)  # Finnhub rate limit

    # Attach to candidates
    for ticker, cand in candidates.items():
        if ticker in results:
            cand['technicals'] = results[ticker]['technicals']
            cand['sentiment']  = results[ticker]['sentiment']

    log.info(f'  Step 3.5 complete: {total} tickers processed')
    return candidates, results  # return results for existing holdings too

# ── STEP 4: 10-K EXTRACTION ───────────────────────────────────────────────────
def fetch_10k_targeted(ticker: str, tier: str = 'T3') -> str:
    cache_file = THESES_DIR.parent / 'sec_cache' / f'{ticker}_10K_extracted.txt'
    cache_file.parent.mkdir(exist_ok=True)
    if cache_file.exists():
        age_days = (datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)).days
        ttl = 90 if tier == 'T3' else 180
        if age_days < ttl:
            return cache_file.read_text(encoding='utf-8', errors='replace')
    try:
        search_url = (
            f'https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22'
            f'&forms=10-K&dateRange=custom&startdt=2025-01-01&enddt=2026-12-31'
        )
        resp = requests.get(search_url, headers={'User-Agent': 'LongTermScreener vishvesh.niyati@gmail.com'}, timeout=20)
        if resp.status_code != 200: return ''
        hits = resp.json().get('hits', {}).get('hits', [])
        if not hits: return ''
        filing    = hits[0]['_source']
        entity_id = filing.get('entity_id', '')
        sub_resp  = requests.get(
            f'https://data.sec.gov/submissions/CIK{entity_id.zfill(10)}.json',
            headers={'User-Agent': 'LongTermScreener vishvesh.niyati@gmail.com'}, timeout=20
        )
        if sub_resp.status_code != 200: return ''
        filings_data = sub_resp.json().get('filings', {}).get('recent', {})
        forms        = filings_data.get('form', [])
        accessions   = filings_data.get('accessionNumber', [])
        docs         = filings_data.get('primaryDocument', [])
        ten_k_idx    = next((i for i, f in enumerate(forms) if f == '10-K'), None)
        if ten_k_idx is None: return ''
        accession = accessions[ten_k_idx].replace('-', '')
        doc_name  = docs[ten_k_idx]
        doc_url   = f'https://www.sec.gov/Archives/edgar/data/{int(entity_id)}/{accession}/{doc_name}'
        doc_resp  = requests.get(doc_url, headers={'User-Agent': 'LongTermScreener vishvesh.niyati@gmail.com'}, timeout=60)
        if doc_resp.status_code != 200: return ''
        extracted = extract_10k_sections(doc_resp.text, ticker)
        cache_file.write_text(extracted, encoding='utf-8')
        return extracted
    except Exception as e:
        log.warning(f'  10-K fetch failed for {ticker}: {e}')
        return ''

def extract_10k_sections(raw_text: str, ticker: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', raw_text)
    text = re.sub(r'\s+', ' ', text)
    text = text[:500_000]
    sections   = {}
    items_to_find = {
        'ITEM_1_BUSINESS': (r'item\s*1[\.\s]*business', r'item\s*1a'),
        'ITEM_1A_RISK':    (r'item\s*1a[\.\s]*risk',    r'item\s*1b'),
        'ITEM_7_MDA':      (r'item\s*7[\.\s]*management', r'item\s*7a'),
    }
    text_lower = text.lower()
    for section_name, (start_pat, end_pat) in items_to_find.items():
        try:
            start_match = re.search(start_pat, text_lower)
            end_match   = re.search(end_pat, text_lower[start_match.end():]) if start_match else None
            if start_match:
                start_pos    = start_match.start()
                end_pos      = start_match.end() + end_match.start() if end_match else start_pos + 30_000
                sections[section_name] = text[start_pos:min(end_pos, start_pos + 30_000)].strip()
        except Exception:
            pass
    combined = '\n\n'.join(f'=== {k} ===\n{v}' for k, v in sections.items())
    return f'TICKER: {ticker}\n\n{combined}' if combined else f'TICKER: {ticker}\n\n{text[:20_000]}'

# ── STEP 5: RESEARCH ─────────────────────────────────────────────────────────
RESEARCH_PROMPT_T1_T2 = """You are a senior long‑term equity analyst. You must ground your analysis in the company's 10‑K extract provided below.

Ticker: {ticker} | Tier: {tier}
Current Market Cap: ${mkt_cap:.1f}B | Revenue: ${revenue:.0f}M
ROIC: {roic:.0%} | Gross Margin: {gm:.0%} | Revenue Growth: {rev_growth:.0%}
Cash Runway: {runway}

COMPANY HISTORY & TRACK RECORD (use this to judge durability — this is what matters for a 10–15yr hold):
{company_history}

Short-term context (background only — DO NOT let this drive a 10–15yr decision): 200MA {above_200ma}, 1yr {return_1yr}%, vs QQQ {vs_qqq}%, Trend {trend}; {news_count} news, 8‑K: {sec_8k_count} {sec_8k_events}; headlines: {headlines}

10‑K Extract (Item 1, 1A, 7):
{filing_text}

This is a 10–15 YEAR investment. Ignore short-term price moves, news cycles, and 8-K noise unless they structurally change the next decade. Weight company history and durability above all.

Your job:
1. MOAT: What is the company's specific competitive advantage? Quote a sentence from Item 1 that supports this.
2. DURABILITY & 20-YEAR SURVIVAL: How many years can this moat last? Using the company's own multi-year track record above PLUS 30-year sector history (1995–2025), what share of companies in this sector are still independent market leaders? Rate survival: HIGH (dominant in 20 years), MEDIUM (survives but faces disruption), or LOW (sector faces structural replacement). Give one sentence explaining why.
3. MANAGEMENT: Capital allocation skill over the history shown? Any clues in the filing?
4. GROWTH RUNWAY: Years before the market is saturated? Use a business segment from Item 1.
5. THESIS-BREAK CHECK: Do the 8-K/news items represent a STRUCTURAL change to the 10–15yr thesis, or just short-term noise to ignore? State which.
6. PRIMARY RISK: Most likely failure mode over 20 years. Reference a specific risk from Item 1A.
7. TEN‑K HIGHLIGHTS: Give exactly 3 bullet points from the filing that every long‑term investor should know. Each must quote or closely paraphrase the document.
8. THESIS: One sentence that names the company's actual product/service, its specific moat, and the big trend it rides.

Return ONLY valid JSON:
{{"moat_type":"string","moat_durability_years":number,"management_grade":"A|B|C|D",
"growth_runway_years":number,"primary_risk":"string",
"sector_durability_20yr":"HIGH|MEDIUM|LOW","sector_survival_note":"string",
"thesis_summary":"string","thesis_breaks_if":"string",
"sentiment_note":"string","decade_probability":0.0-1.0,"annual_alpha_estimate":number,
"verdict":"CORE_HOLD|ACCUMULATE|MONITOR|AVOID","position_size_pct":number,
"ten_k_highlights":["highlight1","highlight2","highlight3"]}}"""

RESEARCH_PROMPT_T3 = """You are a senior long‑term equity analyst evaluating a pre‑revenue or early‑revenue company for a 10‑15 year hold. Your analysis must be grounded in the company's SEC filing extract below.

Ticker: {ticker} | PRE/EARLY-REVENUE Moonshot
Market Cap: ${mkt_cap}B | Cash: ${cash}M | Cash Runway: {runway}
R&D: ${rd}M | Revenue: ${revenue}M

COMPANY HISTORY & TRACK RECORD (judge survival and execution from this, not from short-term noise):
{company_history}

Short-term context (background only — a 10–15yr moonshot, do NOT decide on this): 200MA {above_200ma}, 1yr {return_1yr}%, vs QQQ {vs_qqq}%, Trend {trend}; Reddit 30d {reddit_mentions}; 8-K: {sec_8k_count} {sec_8k_events}; news: {headlines}; reddit: {reddit_titles}

10-K/S-1 Extract:
{filing_text}

Your job:
1. CATEGORY: What market could this company own? What is the TAM estimate?
2. UNFAIR ADVANTAGE: What can competitors not replicate in 5 years? Reference the filing.
3. MILESTONES: 3 specific milestones to first significant revenue. Reference filing if possible.
4. SURVIVAL: Can they reach milestone 1 with current cash/burn? Be explicit about the numbers.
5. COMMUNITY SIGNAL: Is Reddit/news sentiment tracking real milestones or just hype? Explain.
6. KILL RISK: Most likely path to zero. Reference a risk from the filing.
7. TEN‑K HIGHLIGHTS: Give exactly 3 bullet points from the filing that every long‑term investor should know. Each must quote or closely paraphrase the document.
8. THESIS: One sentence investment thesis.

Return ONLY valid JSON:
{{"category":"string","tam_estimate_b":number,"unfair_advantage":"string",
"milestone_1":"string","milestone_2":"string","milestone_3":"string",
"survival_probability":0.0-1.0,"community_signal_quality":"SIGNAL|NOISE|MIXED",
"bull_revenue_10yr_b":number,"bull_mktcap_10yr_b":number,"bull_multiple":number,
"base_revenue_10yr_b":number,"base_mktcap_10yr_b":number,"base_multiple":number,
"kill_risk":"string","thesis_summary":"one sentence",
"thesis_breaks_if":"specific testable exit condition",
"moonshot_score":0-10,"verdict":"MOONSHOT|SPECULATIVE|AVOID","position_size_pct":number,
"ten_k_highlights":["highlight1","highlight2","highlight3"]}}"""

_QQQ_CAGR_CACHE: dict = {}
def get_qqq_cagrs() -> dict:
    """3/5/10yr QQQ CAGR (%), fetched once and cached, for long-term relative alpha."""
    if _QQQ_CAGR_CACHE:
        return _QQQ_CAGR_CACHE
    try:
        close = yf.Ticker('QQQ').history(period='10y')['Close']
        cur = float(close.iloc[-1])
        for y in (3, 5, 10):
            n = y * 252
            if len(close) >= n + 1 and float(close.iloc[-n]) > 0:
                _QQQ_CAGR_CACHE[y] = round(((cur / float(close.iloc[-n])) ** (1 / y) - 1) * 100, 1)
    except Exception:
        pass
    return _QQQ_CAGR_CACHE

def build_company_history(ticker: str, info: dict, technicals: dict) -> str:
    """
    Assemble multi-year company history for the LLM: company age, IPO year,
    EDGAR 5-yr trajectory (revenue/ROIC/margin/dilution), and multi-year price CAGRs.
    All long-term — no short-term noise. Used to ground 10–15yr decisions.
    """
    lines = []
    # Company age / IPO
    name  = info.get('longName') or info.get('shortName') or ticker
    epoch = info.get('firstTradeDateEpochUtc')
    yrs_listed = technicals.get('years_listed')
    if epoch:
        try:
            ipo_yr = datetime.fromtimestamp(epoch).year
            lines.append(f'Public since {ipo_yr} (~{datetime.now().year - ipo_yr} years listed)')
        except Exception:
            pass
    elif yrs_listed:
        lines.append(f'~{yrs_listed} years of price history')
    emp = info.get('fullTimeEmployees')
    if emp:
        lines.append(f'{emp:,} employees')
    # EDGAR multi-year trajectory
    try:
        traj = compute_trajectory(ticker)
        if traj.get('edgar_available'):
            lines.append(f"{traj.get('years_of_data','?')} yrs filed data: "
                         f"revenue {traj.get('revenue_trend','?')} ({traj.get('revenue_5yr_change','?')}%/5yr), "
                         f"gross margin {traj.get('gross_margin_trend','?')}, "
                         f"ROIC {traj.get('roic_trend','?')} ({traj.get('roic_5yr_change','?')}%/5yr), "
                         f"share count {traj.get('share_count_trend','?')} ({traj.get('share_5yr_change','?')}%/5yr, dilution {traj.get('dilution_trajectory','?')})")
        else:
            # Foreign/ADR fallback: revenue history from yfinance financials
            try:
                fin = yf.Ticker(ticker).financials
                rev = fin.loc['Total Revenue'].dropna() if 'Total Revenue' in fin.index else None
                if rev is not None and len(rev) >= 2:
                    chg = (float(rev.iloc[0]) - float(rev.iloc[-1])) / abs(float(rev.iloc[-1])) * 100
                    lines.append(f'{len(rev)}yr revenue (non-US filer): {"UP" if chg>=0 else "DOWN"} ({chg:+.0f}%)')
            except Exception:
                pass
    except Exception:
        pass
    # Multi-year price compounding (how it behaved through cycles) vs QQQ
    c3, c5, c10 = technicals.get('return_3yr_cagr'), technicals.get('return_5yr_cagr'), technicals.get('return_10yr_cagr')
    usd = technicals.get('currency', 'USD') == 'USD'
    if any(v is not None for v in (c3, c5, c10)):
        q = get_qqq_cagrs()
        def _a(c, y):
            if c is None: return f'{c}%'
            if not usd: return f'{c}% (local ccy)'
            return f'{c}% (vs QQQ {round(c - q[y], 1):+}pp)' if q.get(y) is not None else f'{c}%'
        lines.append(f'Price CAGR: 3yr {_a(c3,3)} | 5yr {_a(c5,5)} | 10yr {_a(c10,10)} | max drawdown {technicals.get("max_drawdown")}%')
    return f'{name}\n- ' + '\n- '.join(lines) if lines else f'{name}\n- No multi-year history available (recent IPO or foreign listing)'

def research_candidate(ticker: str, tier: str, info: dict, filing_text: str, sentiment: dict, technicals: dict) -> dict:
    # If no LLM provider is available at all, return the fallback immediately
    from llm_client import get_active_provider
    provider, _ = get_active_provider()
    if not provider:
        return {'verdict': 'NO_API_KEY', 'thesis_summary': 'No LLM provider configured'}

    # ── Build the prompt ──
    revenue  = (info.get('totalRevenue', 0) or 0) / 1e6
    mkt_cap  = (info.get('marketCap', 0) or 0) / 1e9
    gm       = info.get('grossMargins', 0) or 0
    roic     = compute_roic(info, ticker)
    rev_grow = info.get('revenueGrowth', 0) or 0
    cash     = (info.get('totalCash', 0) or 0) / 1e6
    rd       = (info.get('researchAndDevelopment', 0) or 0) / 1e6
    ocf      = info.get('operatingCashflow', 0) or 0
    monthly_burn = abs(ocf) / 12 if ocf < 0 else 0
    runway_str   = f'{(cash / monthly_burn):.0f} months' if monthly_burn > 0 else 'FCF positive'

    above_200ma  = '✅' if technicals.get('above_200ma') else '❌'
    return_1yr   = technicals.get('return_1yr', '—')
    vs_qqq       = technicals.get('return_vs_qqq_1yr', '—')
    trend        = technicals.get('trend', '—')
    pct_from_high = technicals.get('pct_from_high', '—')

    news_count   = sentiment.get('news_count', 0)
    headlines    = ' | '.join(sentiment.get('headlines', [])[:3]) or 'None available'
    reddit_m     = sentiment.get('reddit_mentions_30d', 0)
    reddit_t     = ' | '.join(sentiment.get('reddit_titles', [])[:2]) or 'None'
    sec_8k_count = sentiment.get('sec_8k_count', 0)
    sec_8k_events = '; '.join(e.get('description','') for e in sentiment.get('sec_8k_events', [])[:2]) or 'None'

    company_history = build_company_history(ticker, info, technicals)

    if tier in ('T1', 'T2'):
        prompt = RESEARCH_PROMPT_T1_T2.format(
            ticker=ticker, tier=tier, revenue=revenue, roic=roic, gm=gm,
            rev_growth=rev_grow, mkt_cap=mkt_cap, runway=runway_str,
            company_history=company_history,
            above_200ma=above_200ma, return_1yr=return_1yr, vs_qqq=vs_qqq,
            trend=trend, pct_from_high=pct_from_high,
            news_count=news_count, headlines=headlines,
            reddit_mentions=reddit_m, sec_8k_count=sec_8k_count,
            sec_8k_events=sec_8k_events,
            filing_text=filing_text[:15000] or 'Filing not available.'
        )
    else:
        prompt = RESEARCH_PROMPT_T3.format(
            ticker=ticker, mkt_cap=mkt_cap, cash=cash,
            runway=runway_str, rd=rd, revenue=revenue,
            company_history=company_history,
            above_200ma=above_200ma, return_1yr=return_1yr, vs_qqq=vs_qqq, trend=trend,
            reddit_mentions=reddit_m, reddit_titles=reddit_t,
            headlines=headlines, sec_8k_count=sec_8k_count, sec_8k_events=sec_8k_events,
            filing_text=filing_text[:15000] or 'Filing not available.'
        )

    system = "You are a long-term investment analyst. Return ONLY valid JSON."
    # 2200: the T1/T2 schema alone runs ~900-1200 tokens once the model adds any
    # preamble despite "ONLY JSON" — 1400 was truncating responses before the
    # closing brace, which _parse() then silently turned into an empty string
    # (see llm_client.py) instead of a real truncation error.
    research = research_stock(prompt, system=system, max_tokens=2200)

    # Moat lie detector
    gm = info.get('grossMargins', 0) or 0
    moat = research.get('moat_type', '').lower()
    if 'cost' in moat and gm < 0.25:
        research['moat_type'] = 'MODERATE COST (verify)'
        research['moat_durability_years'] = min(research.get('moat_durability_years', 15), 10)

    # Long-term tilt: weight 10yr (else 5yr) compounding vs QQQ into conviction (USD only)
    lt_cagr = technicals.get('return_10yr_cagr') or technicals.get('return_5yr_cagr')
    horizon = 10 if technicals.get('return_10yr_cagr') is not None else 5
    q = get_qqq_cagrs().get(horizon)
    if lt_cagr is not None and q is not None and technicals.get('currency', 'USD') == 'USD':
        alpha = round(lt_cagr - q, 1)
        research['long_term_alpha_pp'] = alpha
        if alpha <= -5 and research.get('verdict') in ('CORE_HOLD', 'ACCUMULATE'):
            research['verdict'] = 'MONITOR'
            research['position_size_pct'] = min(research.get('position_size_pct', 2) or 2, 2)
            research['long_term_note'] = f'{horizon}yr CAGR lagged QQQ by {abs(alpha)}pp — downgraded'

    return research

def run_research(candidates: dict) -> dict:
    log.info(f'Step 4-5/7: Running research ({len(candidates)} candidates)...')
    results     = {}
    to_research = []
    for ticker, cand in candidates.items():
        tier            = cand['tier']
        existing_thesis = load_thesis(ticker)
        # A failed call (ERROR/PARSE_ERROR/NO_API_KEY) is not a real thesis —
        # caching it as one would strand good candidates for the full 90/180-day
        # TTL every time the LLM has a bad day. Always retry these instead.
        if existing_thesis and existing_thesis.get('verdict') not in ('ERROR', 'PARSE_ERROR', 'NO_API_KEY'):
            ttl_days = 90 if tier == 'T3' else 180
            if 'research_date' in existing_thesis:
                age = (datetime.now() - datetime.fromisoformat(existing_thesis['research_date'])).days
                if age < ttl_days:
                    log.info(f'  {ticker}: cache hit ({age}d old)')
                    results[ticker] = {**cand, 'research': existing_thesis}
                    continue
        to_research.append((ticker, cand))
    log.info(f'  Cache hits: {len(results)}, New research: {len(to_research)}')
    for i in range(0, len(to_research), 3):
        batch = to_research[i:i+3]
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {}
            for ticker, cand in batch:
                filing   = fetch_10k_targeted(ticker, cand['tier'])
                sentiment  = cand.get('sentiment', {})
                technicals = cand.get('technicals', {})
                fut = executor.submit(research_candidate, ticker, cand['tier'], cand['info'], filing, sentiment, technicals)
                futures[fut] = (ticker, cand, filing)
            for fut in as_completed(futures):
                ticker, cand, filing = futures[fut]
                research = fut.result()
                research['research_date'] = datetime.now().isoformat()
                research['ticker']        = ticker
                save_thesis(ticker, research)

                # Sentiment confidence
                sent_data = cand.get('sentiment', {})
                headlines_str = ' | '.join(sent_data.get('headlines', [])[:5])
                sec_8k_str = '; '.join(e.get('description','') for e in sent_data.get('sec_8k_events', [])[:2])
                sent_conf = get_sentiment_confidence(
                    ticker=ticker,
                    thesis=research.get('thesis_summary',''),
                    filing_text=filing or '',
                    headlines=headlines_str,
                    sec_8k_events=sec_8k_str
                )
                research['sentiment_confidence'] = sent_conf.get('confidence_score', 5)
                research['sentiment_reason'] = sent_conf.get('reason', 'LLM confidence evaluation unavailable')

                verdict = research.get('verdict', 'UNKNOWN')
                if verdict in ('ERROR', 'PARSE_ERROR'):
                    log.warning(f'  {ticker} ERROR details: {research.get("error", "none")}')
                log.info(f'  {ticker} [{cand["tier"]}]: {verdict} — {research.get("thesis_summary","")[:60]}')
                results[ticker] = {**cand, 'research': research}
        time.sleep(2)
    return results

# ── STEP 5.5: SCENARIO MODELING ───────────────────────────────────────────────
SCENARIO_PROMPT = """Write Bull/Base/Bear 10-year scenarios for {ticker} ({tier}).

CURRENT FINANCIALS — ground all projections to these numbers, do not ignore:
  Market cap today : ${current_mkt_cap_b:.1f}B
  Revenue (TTM)    : ${current_revenue_b:.2f}B
  Sector           : {sector}

Thesis     : {thesis_summary}
Verdict    : {verdict}
Breaks if  : {thesis_breaks_if}
{extra_context}
Return ONLY valid JSON:
{{"bull":{{"narrative":"string","revenue_10yr_b":number,"mktcap_10yr_b":number,"multiple":number,"probability":0.0-1.0}},
"base":{{"narrative":"string","revenue_10yr_b":number,"mktcap_10yr_b":number,"multiple":number,"probability":0.0-1.0}},
"bear":{{"narrative":"string","mktcap_10yr_b":number,"multiple":number,"probability":0.0-1.0}},
"current_tracking":"BULL|BASE|BEAR","tracking_note":"string",
"thesis_breaks_if":"string","natural_eval_window_days":number}}"""

def run_scenario_modeling(researched: dict) -> dict:
    log.info(f'Step 5.5/7: Scenario modeling ({len(researched)} candidates)...')
    from llm_client import get_active_provider
    provider, _ = get_active_provider()
    if not provider:
        log.warning('  No LLM provider available — skipping scenario modeling')
        return researched

    for ticker, cand in researched.items():
        existing = load_scenario(ticker)
        current_mkt_cap = (cand.get('info',{}).get('marketCap',0) or 0) / 1e9
        sector = cand.get('info',{}).get('sector', 'Unknown')
        tier   = cand.get('tier', 'T2')

        # If existing scenario is fresh, still sanitise it (overwrites any corrupt fields)
        if existing and 'written_date' in existing:
            age = (datetime.now() - datetime.fromisoformat(existing['written_date'])).days
            if age < (90 if tier == 'T3' else 180):
                # Sanitise the cached scenario
                existing = sanitize_scenario(existing, ticker, current_mkt_cap, tier, sector)
                cand['scenario'] = existing
                continue

        # Generate new scenario
        research = cand.get('research', {})
        verdict  = research.get('verdict', 'UNKNOWN')
        if verdict in ('AVOID', 'ERROR', 'NO_API_KEY'):
            continue
        if current_mkt_cap <= 0:
            log.warning(f'  {ticker}: skipping scenario — market cap unknown')
            continue
        extra = ''
        if tier == 'T3':
            extra = f"Milestone 1: {research.get('milestone_1','')}\nKill risk: {research.get('kill_risk','')}"
        current_revenue_b = (cand.get('info',{}).get('totalRevenue',0) or 0) / 1e9
        prompt = SCENARIO_PROMPT.format(
            ticker=ticker, tier=tier,
            current_mkt_cap_b=current_mkt_cap,
            current_revenue_b=current_revenue_b,
            sector=sector,
            thesis_summary=research.get('thesis_summary',''),
            verdict=verdict,
            thesis_breaks_if=research.get('thesis_breaks_if','Moat permanently eroded'),
            extra_context=extra
        )
        try:
            system = "Investment scenario analyst. Return ONLY valid JSON."
            result = call_llm(prompt, system=system, max_tokens=600)
            if result['success']:
                scenario = result['data']
                # Sanitise the freshly generated scenario
                scenario = sanitize_scenario(scenario, ticker, current_mkt_cap, tier, sector)
            else:
                raise ValueError(result.get('error', 'LLM call failed'))
            scenario['written_date'] = datetime.now().isoformat()
            scenario['ticker']       = ticker
            save_scenario(ticker, scenario)
            cand['scenario'] = scenario
            log.info(f'  {ticker}: Bull×{scenario.get("bull",{}).get("multiple","?")} Base×{scenario.get("base",{}).get("multiple","?")}')
            time.sleep(1)
        except Exception as e:
            log.warning(f'  Scenario failed for {ticker}: {e}')
    return researched

# ── STEP 6: PORTFOLIO CONSTRUCTOR ─────────────────────────────────────────────
def check_kiwisaver_availability(ticker: str, config: dict) -> dict:
    ks      = config.get('sharesies_kiwisaver_available', {})
    stocks  = ks.get('individual_stocks', [])
    etfs    = ks.get('etfs', [])
    nz      = ks.get('nz_stocks_and_funds', [])
    if ticker in stocks: return {'available': True,  'type': 'INDIVIDUAL_STOCK', 'route': 'KIWISAVER_OR_MANUAL'}
    if ticker in etfs:   return {'available': True,  'type': 'ETF',              'route': 'KIWISAVER_OR_MANUAL'}
    if ticker in nz:     return {'available': True,  'type': 'NZ_STOCK',         'route': 'KIWISAVER_OR_MANUAL'}
    return {'available': False, 'type': None, 'route': 'MANUAL_SHARESIES_ONLY'}

def construct_portfolio(researched: dict, portfolio: dict, config: dict) -> dict:
    log.info('Step 6/7: Portfolio construction...')
    decisions = {
        'new_additions':       [],
        'hold':                [],
        'exits':               [],
        'migrations':          [],
        'avoided':             [],
        'screened_candidates': []
    }
    existing_tickers = {h['ticker'] for h in portfolio.get('holdings', [])}

    for holding in portfolio.get('holdings', []):
        ticker   = holding['ticker']
        research = load_thesis(ticker)
        scenario = load_scenario(ticker)
        if not research:
            decisions['hold'].append({**holding, 'status': 'HOLD', 'note': 'No research update this month'})
            continue
        verdict = research.get('verdict', 'UNKNOWN')
        if verdict == 'AVOID':
            decisions['exits'].append({**holding, 'status': 'EXIT_RECOMMENDED',
                                       'exit_reason': f'Reassessment: AVOID — {research.get("primary_risk","")}',
                                       'research': research})
        elif verdict in ('CORE_HOLD', 'ACCUMULATE', 'MOONSHOT'):
            current_tier = holding.get('tier', 'T3')
            new_tier     = None
            for t, cand in researched.items():
                if t == ticker:
                    if current_tier == 'T3' and cand.get('tier') == 'T2': new_tier = 'T2'
                    if current_tier == 'T2' and cand.get('tier') == 'T1': new_tier = 'T1'
                    break
            if new_tier:
                decisions['migrations'].append({**holding, 'status': 'TIER_MIGRATION',
                                                'from_tier': current_tier, 'to_tier': new_tier,
                                                'research': research})
            else:
                decisions['hold'].append({**holding, 'status': 'HOLD',
                                          'research': research, 'scenario': scenario})

    sector_count = {}
    for h in portfolio.get('holdings', []):
        s = h.get('sector', 'Unknown')
        sector_count[s] = sector_count.get(s, 0) + 1

    for ticker, cand in researched.items():
        if ticker in existing_tickers:
            continue
        research = cand.get('research', {})
        verdict  = research.get('verdict', 'UNKNOWN')
        tier     = cand['tier']
        info     = cand.get('info', {})
        company_name = info.get('longName') or info.get('shortName') or ticker

        if verdict in ('ERROR', 'PARSE_ERROR', 'NO_API_KEY'):
            tech = cand.get('technicals', {})
            sent = cand.get('sentiment', {})
            all_metrics = compute_all_metrics(ticker, info)
            try:
                edgar_traj = compute_trajectory(ticker)
                edgar_cc   = cross_check_yahoo(ticker, info)
            except Exception as e:
                log.debug(f'  EDGAR fetch failed for {ticker}: {e}')
                edgar_traj, edgar_cc = {}, {}
            decisions['screened_candidates'].append({
                'ticker':             ticker,
                'company_name':       company_name,
                'tier':               tier,
                'score':              cand.get('score', 0),
                'reason':             cand.get('reason', ''),
                'megatrend':          all_metrics.get('megatrend'),
                'megatrend_label':    all_metrics.get('megatrend_label',''),
                'megatrend_score':    all_metrics.get('megatrend_score', 0),
                'tailwind_years':     all_metrics.get('tailwind_years', 0),
                'roic':               all_metrics.get('roic'),
                'gross_margin':       all_metrics.get('gross_margin'),
                'op_margin':          all_metrics.get('op_margin'),
                'rev_growth':         info.get('revenueGrowth', 0) or 0,
                'rev_growth_signal':  all_metrics.get('rev_growth_signal','—'),
                'earnings_quality':   all_metrics.get('earnings_quality','—'),
                'fcf_yield':          all_metrics.get('fcf_yield'),
                'ocf_ni_ratio':       all_metrics.get('ocf_ni_ratio'),
                'net_cash_m':         all_metrics.get('net_cash_m'),
                'net_cash_flag':      all_metrics.get('net_cash_flag','—'),
                'de_ratio':           all_metrics.get('de_ratio') or (compute_debt_ratios(info, ticker)['de_ratio']),
                'capital_intensity':  all_metrics.get('capital_intensity'),
                'rd_intensity':       all_metrics.get('rd_intensity', 0),
                'reinvestment_rate':  all_metrics.get('reinvestment_rate'),
                'moat_proxy_label':   all_metrics.get('moat_proxy_label','—'),
                'pricing_power':      all_metrics.get('pricing_power','—'),
                'recurring_revenue_proxy': all_metrics.get('recurring_revenue_proxy','—'),
                'insider_pct':        all_metrics.get('insider_pct'),
                'insider_signal':     all_metrics.get('insider_signal','—'),
                'dilution_rate':      all_metrics.get('dilution_rate'),
                'dilution_flag':      all_metrics.get('dilution_flag','—'),
                'insider_form4_90d':  all_metrics.get('insider_form4_90d', 0),
                'current_price':      tech.get('current_price'),
                'entry_price':        tech.get('current_price'),
                'above_200ma':        tech.get('above_200ma'),
                'pct_from_high':      tech.get('pct_from_high'),
                'pct_from_200ma':     tech.get('pct_from_200ma'),
                'return_1yr':         tech.get('return_1yr'),
                'return_vs_qqq':      tech.get('return_vs_qqq_1yr'),
                'trend':              tech.get('trend','—'),
                'news_count':         sent.get('news_count', 0),
                'news_sentiment':     sent.get('news_sentiment','NEUTRAL'),
                'reddit_mentions':    sent.get('reddit_mentions_30d', 0),
                'reddit_sentiment':   sent.get('reddit_sentiment','NEUTRAL'),
                'overall_sentiment':  sent.get('overall_sentiment','NEUTRAL'),
                'signal_or_noise':    sent.get('signal_or_noise','NOISE'),
                'key_themes':         sent.get('key_themes', []),
                'sec_8k_count':       sent.get('sec_8k_count', 0),
                'edgar_available':    edgar_traj.get('edgar_available', False),
                'revenue_trend':      edgar_traj.get('revenue_trend'),
                'revenue_5yr_change': edgar_traj.get('revenue_5yr_change'),
                'roic_trend':         edgar_traj.get('roic_trend'),
                'roic_5yr_change':    edgar_traj.get('roic_5yr_change'),
                'gross_margin_trend': edgar_traj.get('gross_margin_trend'),
                'dilution_trajectory': edgar_traj.get('dilution_trajectory'),
                'share_5yr_change':   edgar_traj.get('share_5yr_change'),
                'years_of_data':      edgar_traj.get('years_of_data'),
                'cross_check':        edgar_cc.get('cross_check'),
                'edgar_discrepancies': edgar_cc.get('discrepancies', []),
            })
            continue

        if verdict in ('AVOID', 'SPECULATIVE'):
            decisions['avoided'].append({'ticker': ticker, 'tier': tier,
                                         'verdict': verdict,
                                         'reason': research.get('thesis_summary','Screened out')})
            continue

        sector = info.get('sector', 'Unknown')
        if sector_count.get(sector, 0) >= 3:
            decisions['avoided'].append({'ticker': ticker, 'tier': tier, 'verdict': verdict,
                                         'reason': f'Sector concentration: already 3 {sector} holdings'})
            continue

        if tier == 'T3':
            factor_group = get_t3_factor_group(ticker, info)
            if factor_group != 'other':
                existing_factor_count = sum(
                    1 for h in portfolio.get('holdings', [])
                    if h.get('tier') == 'T3' and h.get('status') == 'ACTIVE'
                    and get_t3_factor_group(h['ticker'], info) == factor_group
                )
                if existing_factor_count >= _cu("max_same_factor_t3_holdings", 3):
                    decisions['avoided'].append({'ticker': ticker, 'tier': tier, 'verdict': verdict,
                                                 'reason': f'T3 factor cap: {factor_group} at max'})
                    continue

        position_pct = max(1.0, min(8.0, {
            'T1': research.get('position_size_pct', 6.0),
            'T2': research.get('position_size_pct', 4.0),
            'T3': research.get('position_size_pct', 1.5),
        }.get(tier, 2.0)))

        ks_check    = check_kiwisaver_availability(ticker, config)
        technicals  = cand.get('technicals', {})
        sentiment   = cand.get('sentiment', {})
        eq_flag     = compute_earnings_quality(info)
        debt        = compute_debt_ratios(info, ticker)
        all_metrics = compute_all_metrics(ticker, info)

        new_holding = {
            'ticker':             ticker,
            'company_name':       company_name,
            'tier':               tier,
            'date_added':         datetime.now().strftime('%Y-%m-%d'),
            'sector':             sector,
            'market_cap':         info.get('marketCap', 0) or 0,
            'revenue':            info.get('totalRevenue', 0) or 0,
            'sentiment_confidence': research.get('sentiment_confidence', '—'),
            'megatrend':          all_metrics.get('megatrend'),
            'megatrend_label':    all_metrics.get('megatrend_label',''),
            'megatrend_score':    all_metrics.get('megatrend_score', 0),
            'tailwind_years':     all_metrics.get('tailwind_years', 0),
            'thesis_summary':     research.get('thesis_summary', ''),
            'thesis_breaks_if':   research.get('thesis_breaks_if', ''),
            'sentiment_note':     research.get('sentiment_note', ''),
            'moat_type':          research.get('moat_type', ''),
            'moat_durability_years': research.get('moat_durability_years', ''),
            'management_grade':   research.get('management_grade', ''),
            'growth_runway_years': research.get('growth_runway_years', ''),
            'primary_risk':       research.get('primary_risk', ''),
            'annual_alpha_estimate': research.get('annual_alpha_estimate', 0),
            'ten_k_highlights':   research.get('ten_k_highlights', []),
            'position_size_pct':  position_pct,
            'status':             'ACTIVE',
            'verdict':            verdict,
            'decade_probability': research.get('decade_probability', 0),
            'roic':               compute_roic(info, ticker),
            'gross_margin':       info.get('grossMargins', 0) or 0,
            'rev_growth':         info.get('revenueGrowth', 0) or 0,
            'de_ratio':           debt['de_ratio'],
            'interest_coverage':  debt['coverage'],
            'dilution_rate':      compute_dilution_rate(info),
            'insider_ownership':  get_insider_ownership(info),
            'earnings_quality':   eq_flag,
            'entry_price':        technicals.get('current_price'),
            'current_price':      technicals.get('current_price'),
            'above_200ma':        technicals.get('above_200ma'),
            'pct_from_high':      technicals.get('pct_from_high'),
            'pct_from_200ma':     technicals.get('pct_from_200ma'),
            'return_1yr':         technicals.get('return_1yr'),
            'return_vs_qqq':      technicals.get('return_vs_qqq_1yr'),
            'return_3yr_cagr':    technicals.get('return_3yr_cagr'),
            'return_5yr_cagr':    technicals.get('return_5yr_cagr'),
            'return_10yr_cagr':   technicals.get('return_10yr_cagr'),
            'max_drawdown':       technicals.get('max_drawdown'),
            'long_term_alpha_pp': research.get('long_term_alpha_pp'),
            'long_term_note':     research.get('long_term_note', ''),
            'trend':              technicals.get('trend'),
            'news_count':         sentiment.get('news_count', 0),
            'news_sentiment':     sentiment.get('news_sentiment', 'NEUTRAL'),
            'reddit_mentions':    sentiment.get('reddit_mentions_30d', 0),
            'reddit_sentiment':   sentiment.get('reddit_sentiment', 'NEUTRAL'),
            'overall_sentiment':  sentiment.get('overall_sentiment', 'NEUTRAL'),
            'signal_or_noise':    sentiment.get('signal_or_noise', 'NOISE'),
            'key_themes':         sentiment.get('key_themes', []),
            'sec_8k_count':       sentiment.get('sec_8k_count', 0),
            'sec_8k_events':      sentiment.get('sec_8k_events', []),
            'sec_8k_highlights':  sentiment.get('sec_8k_highlights', []),
            'sec_8k_latest_date': sentiment.get('sec_8k_latest_date', ''),
            'news_intelligence':  sentiment.get('news_intelligence', {}),
            'sector_durability_20yr': research.get('sector_durability_20yr', ''),
            'sector_survival_note':   research.get('sector_survival_note', ''),
            'qqq_price_at_entry': None,
            'spy_price_at_entry': None,
            'usdnzd_at_entry':    None,
            'kiwisaver_available': ks_check['available'],
            'kiwisaver_route':     ks_check['route'],
            'kiwisaver_type':      ks_check.get('type'),
            'conflict_flag':       ticker == 'ANTHROPIC',
            'research':           research,
            'scenario':           cand.get('scenario', {}),
        }

        try:
            bench = yf.download(['QQQ','SPY','NZDUSD=X'], period='1d', progress=False)
            if not bench.empty:
                new_holding['qqq_price_at_entry'] = float(bench['Close']['QQQ'].iloc[-1])
                new_holding['spy_price_at_entry'] = float(bench['Close']['SPY'].iloc[-1])
                new_holding['usdnzd_at_entry']    = float(bench['Close']['NZDUSD=X'].iloc[-1])
        except Exception:
            pass

        decisions['new_additions'].append(new_holding)
        sector_count[sector] = sector_count.get(sector, 0) + 1
        route_note = '→ KiwiSaver or manual' if ks_check['available'] else '→ Manual Sharesies only'
        log.info(f'  NEW [{tier}] {ticker}: {verdict} | {position_pct}% | {route_note}')

    return decisions

# ── EMAIL HELPERS (used by email_report.py) ────────────────────────────────────
def format_currency(v: float, prefix: str = '$') -> str:
    if v is None: return '—'
    if v >= 1e9:  return f'{prefix}{v/1e9:.1f}B'
    if v >= 1e6:  return f'{prefix}{v/1e6:.0f}M'
    return f'{prefix}{v:,.0f}'

def send_email(html: str, subject: str) -> bool:
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        log.warning('  Email not configured — skipping send')
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f'Autonomous Capital <{EMAIL_SENDER}>'
        msg['To']      = EMAIL_RECIPIENT
        if EMAIL_CC_LIST:
            msg['Cc'] = ', '.join(EMAIL_CC_LIST)
        # BCC: include in sendmail recipients but NOT in headers (invisible to all recipients)
        all_recipients = [EMAIL_RECIPIENT] + EMAIL_CC_LIST + EMAIL_BCC_LIST
        msg.attach(MIMEText(html, 'html'))
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=ctx) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, all_recipients, msg.as_string())
        log.info(f'  ✓ Email sent: {subject}')
        return True
    except Exception as e:
        log.error(f'  Email failed: {e}')
        return False

# ── EMAIL CSS (kept for completeness, but email_report.py uses its own) ─────────
EMAIL_CSS = (
    "*{margin:0;padding:0;box-sizing:border-box}"
    "body{background:#f0eff4;font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;padding:16px;color:#1c1c1e}"
    ".w{max-width:600px;margin:0 auto;background:#fff;border-radius:2px;overflow:hidden;box-shadow:0 2px 24px rgba(0,0,0,.08)}"
    ".mast{background:#0b1f3a;padding:0}"
    ".mast-top{padding:24px 28px 0}"
    ".issue-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}"
    ".issue-tag{font-size:9px;letter-spacing:.2em;text-transform:uppercase;color:#7ca3c8}"
    ".issue-num{font-size:9px;letter-spacing:.15em;color:#5a7a96}"
    ".brand{font-size:22px;font-weight:800;color:#fff;letter-spacing:-.02em;margin-bottom:3px}"
    ".brand span{color:#5b9bd6}"
    ".tagline{font-size:10px;color:#5a7a96;letter-spacing:.05em;text-transform:uppercase;margin-bottom:16px}"
    ".mast-bar{height:3px;background:linear-gradient(90deg,#1a6abf,#5b9bd6 40%,#34a89c 70%,#e8a020)}"
    ".strip{background:#0e2847;padding:12px 28px;display:flex;gap:20px;flex-wrap:wrap}"
    ".stat-l{font-size:8px;letter-spacing:.2em;text-transform:uppercase;color:#5a7a96;margin-bottom:2px}"
    ".stat-v{font-size:15px;font-weight:700;color:#fff;letter-spacing:-.02em}"
    ".stat-v.g{color:#4caf7d}.stat-v.a{color:#e8a020}.stat-v.r{color:#e05555}"
    ".body{padding:0 24px 24px}"
    ".sec{padding-top:22px}"
    ".sec-hdr{display:flex;align-items:center;gap:8px;margin-bottom:12px}"
    ".sec-txt{font-size:8px;font-weight:700;letter-spacing:.25em;text-transform:uppercase;color:#8a8a8e;white-space:nowrap}"
    ".sec-line{flex:1;height:1px;background:#e8e8ec}"
    ".card{border:1px solid #e8e8ec;border-radius:2px;margin-bottom:10px;overflow:hidden}"
    ".card-head{padding:12px 14px;border-bottom:1px solid #f0f0f4;display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap}"
    ".card-left{flex:1;min-width:0}"
    ".pill-row{display:flex;gap:5px;margin-bottom:4px;flex-wrap:wrap}"
    ".pill{font-size:8px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;padding:2px 7px;border-radius:2px}"
    ".p-t1{background:#fef6e0;color:#8a5c00;border:1px solid #f5d78a}"
    ".p-t2{background:#e8f0fe;color:#1a4ab5;border:1px solid #a8c0f8}"
    ".p-t3{background:#fde8ec;color:#c0232d;border:1px solid #f8a0a8}"
    ".p-ks{background:#e6f4f0;color:#1a5e40;border:1px solid #7ecbb0}"
    ".p-man{background:#f3f0ff;color:#5a30a0;border:1px solid #c8b8f8}"
    ".ticker{font-size:20px;font-weight:800;color:#0b1f3a;letter-spacing:-.02em;line-height:1}"
    ".company{font-size:11px;color:#8a8a9a;margin-top:2px}"
    ".card-right{text-align:right;flex-shrink:0}"
    ".pos{font-size:18px;font-weight:700;color:#0b1f3a;letter-spacing:-.02em}"
    ".pos-l{font-size:9px;color:#a0a0aa;text-transform:uppercase;letter-spacing:.1em}"
    ".card-body{padding:10px 14px;background:#fafafa}"
    ".meta-row{display:flex;gap:14px;margin-bottom:8px;flex-wrap:wrap}"
    ".meta{font-size:10px;color:#6a6a7a}"
    ".meta strong{color:#2a2a3a;font-weight:600}"
    ".thesis{font-size:12px;color:#3a3a4a;line-height:1.6;margin-bottom:8px}"
    ".sentiment-row{font-size:10px;color:#6a6a7a;background:#f0f6ff;padding:6px 9px;border-left:2px solid #5b9bd6;margin-bottom:6px;line-height:1.5}"
    ".tech-row{font-size:10px;color:#6a6a7a;background:#f0fdf4;padding:6px 9px;border-left:2px solid #4caf7d;margin-bottom:6px;line-height:1.5}"
    ".exit{font-size:10px;color:#8a8a9a;background:#f3f3f6;padding:7px 9px;border-left:2px solid #e05555;line-height:1.5}"
    ".exit strong{color:#c0392b}"
    ".pt{width:100%;border-collapse:collapse;font-size:11px}"
    ".pt th{font-size:8px;font-weight:600;letter-spacing:.15em;text-transform:uppercase;color:#a0a0aa;padding:7px 8px;text-align:left;border-bottom:2px solid #e8e8ec;background:#fafafa}"
    ".pt td{padding:9px 8px;border-bottom:1px solid #f0f0f4;color:#3a3a4a;vertical-align:middle}"
    ".pt tr:last-child td{border-bottom:none}"
    ".pt-tick{font-weight:700;font-size:12px;color:#0b1f3a}"
    ".pt-co{font-size:10px;color:#9a9aaa;margin-top:1px}"
    ".trk{font-size:9px;font-weight:600;padding:2px 6px;border-radius:2px}"
    ".tk-bull{background:#e6f4ec;color:#1a7a40}.tk-base{background:#f0f0f8;color:#4a4a6a}.tk-bear{background:#fde8e8;color:#c0392b}"
    ".ks-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}"
    ".ks-card{border:1px solid #e8e8ec;border-radius:2px;padding:12px}"
    ".ks-title{font-size:8px;font-weight:700;letter-spacing:.18em;text-transform:uppercase;margin-bottom:6px}"
    ".ks-avail .ks-title{color:#1a5e40}.ks-man .ks-title{color:#5a30a0}"
    ".ks-body{font-size:11px;color:#5a5a6a;line-height:1.6}"
    ".ks-body strong{color:#1c1c1e}"
    ".ftr{background:#0b1f3a;padding:18px 24px}"
    ".ftr-brand{font-size:12px;font-weight:700;color:#5b9bd6;margin-bottom:5px}"
    ".ftr-txt{font-size:10px;color:#4a6a88;line-height:1.8}"
    ".ftr-disc{font-size:9px;color:#2a4a62;margin-top:8px;padding-top:8px;border-top:1px solid #152d47;line-height:1.7}"
    "@media(max-width:480px){.body{padding:0 16px 20px}.mast-top{padding:16px 16px 0}"
    ".strip{padding:10px 16px;gap:14px}.ftr{padding:14px 16px}"
    ".ks-grid{grid-template-columns:1fr}.card-head{flex-direction:column}.card-right{text-align:left}}"
)

def _pill(cls, text):
    return f'<span class="pill {cls}">{text}</span>'
def _tier_pill(tier):
    return _pill('p-' + tier.lower(), tier)
def _ks_pill(available):
    return _pill('p-ks', 'KiwiSaver') if available else _pill('p-man', 'Sharesies')
def _track_span(tracking):
    cls = {'BULL':'tk-bull','BASE':'tk-base','BEAR':'tk-bear'}.get(str(tracking).upper(), 'tk-base')
    return f'<span class="trk {cls}">{tracking}</span>'
def _mast(date_str, issue_n, strip_stats):
    stats_html = ''.join(
        f'<div><div class="stat-l">{lbl}</div><div class="stat-v {cls}">{val}</div></div>'
        for lbl, val, cls in strip_stats
    )
    return (
        '<div class="mast"><div class="mast-top">'
        f'<div class="issue-row"><span class="issue-tag">Long-Term Portfolio &middot; {date_str}</span>'
        f'<span class="issue-num">Issue #{str(issue_n).zfill(2)}</span></div>'
        '<div class="brand">Autonomous<span>Capital</span></div>'
        '<div class="tagline">Monthly Portfolio Intelligence</div>'
        '</div><div class="mast-bar"></div>'
        f'<div class="strip">{stats_html}</div></div>'
    )
def _section(title, body):
    return (
        '<div class="sec"><div class="sec-hdr">'
        f'<span class="sec-txt">{title}</span><div class="sec-line"></div></div>'
        + body + '</div>'
    )
def _footer():
    return (
        '<div class="ftr"><div class="ftr-brand">Autonomous Capital</div>'
        '<div class="ftr-txt">Powered by Claude AI &middot; Finnhub &middot; Reddit &middot; SEC EDGAR &middot; Yahoo Finance</div>'
        '<div class="ftr-disc">For informational purposes only. Not financial advice. '
        'KiwiSaver routing based on Sharesies self-select list — verify before acting.</div></div>'
    )

def _action_card(item, kind):
    ticker  = item.get('ticker', '')
    company = item.get('company_name', ticker)
    tier    = item.get('tier', '')
    pos     = item.get('position_size_pct', item.get('target_pct', 0)) or 0
    ks      = item.get('kiwisaver_available', False)
    thesis  = item.get('thesis_summary', item.get('thesis', ''))
    exit_c  = item.get('thesis_breaks_if', '')
    sent_note = item.get('sentiment_note', '')
    above_200 = item.get('above_200ma')
    ret_1yr   = item.get('return_1yr')
    vs_qqq    = item.get('return_vs_qqq')
    news_n    = item.get('news_count', 0)
    reddit_n  = item.get('reddit_mentions', 0)

    act_pill = {
        'sell':     _pill('p-sell', 'Sell') if hasattr(_pill, '__call__') else '',
        'increase': _pill('p-inc',  'Increase'),
        'buy':      _pill('p-buy',  '+ Buy'),
    }.get(kind, _pill('p-buy', '+ Buy'))

    # Define missing pills inline
    p_sell = '<span class="pill" style="background:#fde8e8;color:#c0392b;font-size:8px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;padding:2px 7px;border-radius:2px">Sell</span>'
    p_inc  = '<span class="pill" style="background:#fff3e0;color:#c66b00;font-size:8px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;padding:2px 7px;border-radius:2px">Increase</span>'
    p_buy  = '<span class="pill" style="background:#e6f4ec;color:#1a7a40;font-size:8px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;padding:2px 7px;border-radius:2px">+ Buy</span>'
    act_pill = {'sell': p_sell, 'increase': p_inc, 'buy': p_buy}.get(kind, p_buy)

    pills    = act_pill + ' ' + _tier_pill(tier) + ' ' + _ks_pill(ks)
    pos_html = (f'<div class="card-right"><div class="pos">{round(pos,1)}%</div>'
                f'<div class="pos-l">of portfolio</div></div>') if pos else ''

    thesis_html   = f'<div class="thesis">{thesis}</div>' if thesis else ''
    exit_html     = f'<div class="exit"><strong>Exit if:</strong> {exit_c}</div>' if exit_c else ''

    tech_parts = []
    if above_200 is not None:
        tech_parts.append(f'200MA: {"✅" if above_200 else "❌"}')
    if ret_1yr is not None:
        tech_parts.append(f'1yr: {ret_1yr:+.1f}%')
    if vs_qqq is not None:
        tech_parts.append(f'vs QQQ: {vs_qqq:+.1f}%')
    tech_html = (f'<div class="tech-row">📈 {" &middot; ".join(tech_parts)}</div>') if tech_parts else ''

    sent_parts = []
    if news_n:    sent_parts.append(f'{news_n} news articles')
    if reddit_n:  sent_parts.append(f'{reddit_n} Reddit mentions')
    sent_html = (f'<div class="sentiment-row">💬 {" &middot; ".join(sent_parts)}'
                 + (f' &middot; {sent_note}' if sent_note else '') + '</div>') if sent_parts or sent_note else ''

    return (
        '<div class="card"><div class="card-head">'
        f'<div class="card-left"><div class="pill-row">{pills}</div>'
        f'<div class="ticker">{ticker}</div><div class="company">{company}</div></div>'
        + pos_html + '</div>'
        f'<div class="card-body">{tech_html}{sent_html}{thesis_html}{exit_html}</div></div>'
    )

def _badge_html(cls, text):
    return f'<span class="badge {cls}">{text}</span>'

def _tier_badge(tier):
    return _badge_html('b-' + tier.lower(), tier)

def _sent_badge(s):
    m = {'POSITIVE':'sv-pos','NEGATIVE':'sv-neg','NEUTRAL':'sv-neu','MIXED':'sv-mix'}
    return f'<span class="sv-badge {m.get(s,"sv-neu")}">{s.title()}</span>'

def _signal_badge(s):
    m = {'SIGNAL':'sv-sig','NOISE':'sv-noi','MIXED':'sv-mix2'}
    return f'<span class="sv-badge {m.get(s,"sv-noi")}">{s.title()}</span>'

def _thesis_badge(verdict):
    if verdict in ('CORE_HOLD','ACCUMULATE','MOONSHOT'):
        return '<span class="badge b-intact">Thesis intact</span>'
    if verdict == 'MONITOR':
        return '<span class="badge b-monitor">Monitor</span>'
    return '<span class="badge b-broken">Review</span>'

def _tracking_badge(t):
        t = str(t).upper()
        cls = {'BULL':'trk-bull','BASE':'trk-base','BEAR':'trk-bear'}.get(t,'trk-base')
        return f'<span class="trk-badge {cls}">Tracking: {t}</span>'

def _bar(label, pct, color, val_str):
        width = min(max(float(pct or 0) * 100, 0), 100)
        return (f'<div class="bar-row"><div class="bar-lbl">{label}</div>'
                f'<div class="bar-wrap"><div class="bar-fill" style="width:{width:.0f}%;background:{color}"></div></div>'
                f'<div class="bar-val" style="color:{color}">{val_str}</div></div>')

def _holding_card(h):
        ticker    = h.get('ticker', '')
        company   = h.get('company_name', ticker)
        tier      = h.get('tier', 'T2')
        pos       = h.get('position_size_pct', 0) or 0
        verdict   = h.get('verdict', 'UNKNOWN')
        ks        = h.get('kiwisaver_available', False)
        decade_p  = h.get('decade_probability', 0) or 0
        alpha_est = h.get('annual_alpha_estimate', 0) or 0
        date_added = str(h.get('date_added', ''))[:7]

        # Price / return
        cur_price  = h.get('current_price')
        ret_1yr    = h.get('return_1yr')
        vs_qqq     = h.get('return_vs_qqq')
        price_str  = f'${cur_price:.0f}' if cur_price else '—'
        ret_str    = f'{ret_1yr:+.1f}% yr' if ret_1yr is not None else ''
        ret_cls    = 'pos' if (ret_1yr or 0) >= 0 else 'neg'

        # Scenario
        scenario   = h.get('scenario', {})
        tracking   = str(scenario.get('current_tracking', 'BASE')).upper()
        trk_note   = scenario.get('tracking_note', '')
        bull_s     = scenario.get('bull', {})
        base_s     = scenario.get('base', {})
        bear_s     = scenario.get('bear', {})

        # Fundamentals
        roic      = h.get('roic', 0) or 0
        gm        = h.get('gross_margin', 0) or 0
        rev_gr    = h.get('rev_growth', 0) or 0
        de        = h.get('de_ratio', 0) or 0
        cov       = h.get('interest_coverage', 0) or 0
        dilution  = h.get('dilution_rate', 0) or 0
        insider   = h.get('insider_ownership', 0) or 0
        eq        = h.get('earnings_quality', 'WATCH')
        eq_cls    = {'CLEAN':'sb-clean','WATCH':'sb-watch','FLAG':'sb-flag'}.get(eq,'sb-watch')

        # Technicals
        above_200  = h.get('above_200ma')
        pct_high   = h.get('pct_from_high', 0) or 0
        trend      = h.get('trend', '—')
        vs_qqq_str = f'{vs_qqq:+.1f}%' if vs_qqq is not None else '—'

        # Sentiment
        news_cnt        = h.get('news_count', 0) or 0
        reddit_cnt      = h.get('reddit_mentions', 0) or 0
        sec_8k          = h.get('sec_8k_count', 0) or 0
        news_sent       = h.get('news_sentiment', 'NEUTRAL')
        reddit_sent     = h.get('reddit_sentiment', 'NEUTRAL')
        overall_s       = h.get('overall_sentiment', 'NEUTRAL')
        signal          = h.get('signal_or_noise', 'NOISE')
        key_themes      = h.get('key_themes', [])
        sent_note       = h.get('sentiment_note', '')
        sec_events      = h.get('sec_8k_events', [])
        sec_highlights  = h.get('sec_8k_highlights', [])
        sec_latest_date = h.get('sec_8k_latest_date', '')

        # Research
        thesis      = h.get('thesis_summary', '')
        breaks_if   = h.get('thesis_breaks_if', '')
        moat_type   = h.get('moat_type', '')
        moat_dur    = h.get('moat_durability_years', '')
        mgmt_grade  = h.get('management_grade', '')
        runway_yrs  = h.get('growth_runway_years', '')
        primary_risk = h.get('primary_risk', '')

        # ── HEAD ─────────────────────────────────────────────────────────────
        tracking_cls = {'BULL':'b-bull','BASE':'b-base','BEAR':'b-bear'}.get(tracking,'b-base')
        ks_badge     = _badge_html('b-ks','KiwiSaver') if ks else _badge_html('b-man','Sharesies')

        html = f'''
<div class="hcard">
<div class="hc-head">
  <div class="hc-row1">
    <div>
      <div class="badges" style="margin-bottom:6px">
        {_tier_badge(tier)}
        {_badge_html(tracking_cls, tracking + ' tracking')}
        {_thesis_badge(verdict)}
        {ks_badge}
      </div>
      <div class="hc-ticker">{ticker}</div>
      <div class="hc-co">{company}</div>
    </div>
    <div class="hc-right">
      <div class="hc-price">{price_str}</div>
      <div class="hc-ret {ret_cls}">{ret_str}</div>
    </div>
  </div>
  <div class="hc-meta">
    <div class="hc-m">Position <strong>{round(pos,1)}%</strong></div>
    <div class="hc-m">Added <strong>{date_added}</strong></div>
    <div class="hc-m">Decade prob. <strong>{round(decade_p*100):.0f}%</strong></div>
    {'<div class="hc-m">Alpha est. <strong>+' + str(round(alpha_est)) + '%/yr</strong></div>' if alpha_est else ''}
  </div>
</div>'''

        # ── FUNDAMENTALS ──────────────────────────────────────────────────────
        de_cls   = 'r' if de > 3 else ('n' if de > 1.5 else 'g')
        cov_cls  = 'r' if 0 < cov < 2 else 'g'
        roic_pct = f'{roic:.0%}' if roic else '—'
        gm_pct   = f'{gm:.0%}' if gm else '—'
        rg_pct   = f'{rev_gr:+.0%}' if rev_gr else '—'
        de_str   = f'{de:.1f}x' if de else '—'
        cov_str  = f'{cov:.0f}x' if cov else '—'
        dil_str  = f'{dilution:.1%}' if dilution else '0%'
        ins_str  = f'{insider:.1%}' if insider else '—'

        html += f'''
<div class="sec">
  <div class="sec-lbl">Business quality — fundamentals <span class="sec-badge {eq_cls}">{eq}</span></div>
  <div class="grid3">
    <div class="dc"><div class="dk">ROIC</div><div class="dv g">{roic_pct}</div></div>
    <div class="dc"><div class="dk">Gross margin</div><div class="dv g">{gm_pct}</div></div>
    <div class="dc"><div class="dk">Rev growth</div><div class="dv {"g" if (rev_gr or 0)>0 else "r"}">{rg_pct}</div></div>
    <div class="dc"><div class="dk">D/E ratio</div><div class="dv {de_cls}">{de_str}</div></div>
    <div class="dc"><div class="dk">Int. coverage</div><div class="dv {cov_cls}">{cov_str}</div></div>
    <div class="dc"><div class="dk">Dilution / Insider</div><div class="dv n">{dil_str} / {ins_str}</div></div>
  </div>
  {_bar('ROIC', roic, '#16a34a', roic_pct)}
  {_bar('Gross margin', gm, '#5b9bd6', gm_pct)}
  {_bar('Dilution', dilution, '#e05555', dil_str)}
</div>'''

        # ── TECHNICALS ────────────────────────────────────────────────────────
        above_str = ('✅ +' + f'{abs(pct_high):.1f}% above') if above_200 else ('❌ ' + f'{abs(pct_high):.1f}% below')
        above_cls = 'g' if above_200 else 'r'
        trend_cls = 'g' if trend == 'UP' else ('r' if trend == 'DOWN' else 'n')
        ret1yr_str = f'{ret_1yr:+.1f}%' if ret_1yr is not None else '—'
        ret1yr_cls = 'g' if (ret_1yr or 0) >= 0 else 'r'
        vsqqq_cls  = 'g' if (vs_qqq or 0) >= 0 else 'r'

        html += f'''
<div class="sec">
  <div class="sec-lbl">Long-term technical position</div>
  <div class="grid3">
    <div class="dc"><div class="dk">200MA</div><div class="dv {above_cls}" style="font-size:9px">{above_str}</div></div>
    <div class="dc"><div class="dk">52w from high</div><div class="dv n">{pct_high:.1f}%</div></div>
    <div class="dc"><div class="dk">Trend</div><div class="dv {trend_cls}">{trend}</div></div>
    <div class="dc"><div class="dk">1yr return</div><div class="dv {ret1yr_cls}">{ret1yr_str}</div></div>
    <div class="dc"><div class="dk">vs QQQ</div><div class="dv {vsqqq_cls}">{vs_qqq_str}</div></div>
    <div class="dc"><div class="dk">Since added</div><div class="dv n">{date_added}</div></div>
  </div>
</div>'''

        # ── SENTIMENT ─────────────────────────────────────────────────────────
        sec8k_str  = ', '.join(e.get('description','') for e in sec_events[:2]) if sec_events else 'No material events'
        themes_str = ' · '.join(key_themes) if key_themes else 'General market coverage'

        # Unpack LLM intelligence
        intel          = h.get('news_intelligence', {})
        intel_impact   = intel.get('thesis_impact', '')
        intel_reason   = intel.get('impact_reason', '')
        intel_insights = intel.get('key_insights', [])
        intel_watch    = intel.get('watch_flag', '')
        intel_summary  = intel.get('sentiment_summary', '')
        _impact_map    = {
            'STRENGTHENS': ('#16a34a', '#f0fdf4', 'Strengthens 20-yr thesis'),
            'THREATENS':   ('#c0392b', '#fff8f8', 'Threatens 20-yr thesis'),
            'NEUTRAL':     ('#6a7a8a', '#f0f4f8', 'Neutral to 20-yr thesis'),
        }
        imp_color, imp_bg, imp_label = _impact_map.get(intel_impact, ('#6a7a8a', '#f0f4f8', 'Sentiment analysis'))

        html += f'''
<div class="sec">
  <div class="sec-lbl">Market intelligence — 30 days <span style="font-weight:400; color:#9aa4b0">({news_cnt} news · {reddit_cnt} community)</span></div>

  {f"""<div style="border-left:3px solid {imp_color}; padding:8px 10px; background:{imp_bg}; border-radius:4px; margin-bottom:8px;">
    <div style="font-size:9px; font-weight:700; letter-spacing:0.08em; text-transform:uppercase; color:{imp_color}; margin-bottom:4px">{imp_label}{' — ' + intel_reason if intel_reason else ''}</div>
    {''.join(f'<div style="font-size:9.5px; padding:2px 0; color:#1a2a3a;">• {ins}</div>' for ins in intel_insights[:3]) if intel_insights else ''}
    {f'<div style="font-size:9px; color:#b45309; margin-top:5px">Watch: {intel_watch}</div>' if intel_watch else ''}
    {f'<div style="font-size:9px; color:#6a7a8a; margin-top:4px; font-style:italic">{intel_summary}</div>' if intel_summary else ''}
  </div>""" if intel else f"""<div class="sent-block">
    <div class="sent-src-row"><span class="sent-src">News &amp; community</span><span class="sent-cnt">{news_cnt} articles · {reddit_cnt} Reddit</span></div>
    <div class="sent-themes">Themes: {themes_str}</div>
    <div class="sent-verdict-row">{_sent_badge(news_sent)}{_signal_badge(signal)}</div>
  </div>"""}

  <div class="sent-block" style="border-left:3px solid {'#c0392b' if sec_8k > 0 else '#9aa4b0'}; padding-left:8px;">
    <div class="sent-src-row">
      <span class="sent-src" style="font-weight:700; color:{'#c0392b' if sec_8k > 0 else '#6a7a8a'}">SEC 8-K Filing{'s' if sec_8k!=1 else ''}</span>
      <span class="sent-cnt">{sec_8k} filing{'s' if sec_8k!=1 else ''} in last 45 days{' · latest ' + sec_latest_date if sec_latest_date else ''}</span>
    </div>
    {f"""<div style="margin-top:6px; padding:8px; background:#fff8f0; border-radius:4px; font-size:9px;">
      <div style="font-weight:700; letter-spacing:0.08em; text-transform:uppercase; color:#b45309; margin-bottom:5px">Key Highlights — From 8-K Filing ({sec_latest_date})</div>
      {''.join(f'<div style="padding:3px 0; border-bottom:1px solid #f0e0d0; color:#1a2a3a;">• {pt}</div>' for pt in sec_highlights)}
    </div>""" if sec_highlights else f'<div class="sent-themes" style="color:{"#c0392b" if sec_8k > 0 else "#888"}">{sec8k_str}</div>'}
    <div class="sent-verdict-row" style="margin-top:5px">
      {'<span class="sv-badge sv-sig">⚠ Material Signal — review immediately</span>' if sec_8k > 0 else '<span class="sv-badge sv-noi">No material events in last 45 days</span>'}
    </div>
  </div>
  {f'<div class="claude-box">LLM note: {sent_note}</div>' if sent_note else ''}
</div>'''

        # ── THESIS ────────────────────────────────────────────────────────────
        sect_dur    = h.get('sector_durability_20yr', '')
        sect_note   = h.get('sector_survival_note', '')
        _dur_colors = {'HIGH': '#16a34a', 'MEDIUM': '#d97706', 'LOW': '#c0392b'}
        sect_color  = _dur_colors.get(sect_dur, '#6a7a8a')

        html += f'''
<div class="sec">
  <div class="sec-lbl">Investment thesis — 20-year view</div>
  <div class="thesis-box">
    <div class="thesis-txt">{thesis}</div>
    <div class="moat-grid">
      {'<div class="moat-item">Moat <strong>' + str(moat_type) + '</strong></div>' if moat_type else ''}
      {'<div class="moat-item">Durability <strong>' + str(moat_dur) + ' yrs</strong></div>' if moat_dur else ''}
      {'<div class="moat-item">Management <strong>' + str(mgmt_grade) + ' grade</strong></div>' if mgmt_grade else ''}
      {'<div class="moat-item">Runway <strong>' + str(runway_yrs) + ' yrs</strong></div>' if runway_yrs else ''}
      {f'<div class="moat-item">20yr survival <strong style="color:{sect_color}">{sect_dur}</strong></div>' if sect_dur else ''}
    </div>
    {f'<div class="break-row" style="color:{sect_color}; font-style:italic; font-size:9px; margin-bottom:4px">{sect_note}</div>' if sect_note else ''}
    {'<div class="break-row"><strong>Primary risk:</strong> ' + str(primary_risk) + '</div>' if primary_risk else ''}
    {'<div class="break-row" style="margin-top:4px"><strong>Exit if:</strong> ' + str(breaks_if) + '</div>' if breaks_if else ''}
  </div>
</div>'''

        # ── SCENARIOS ─────────────────────────────────────────────────────────
        def _scen_cell(s, css_cls, lbl):
            if not s: return f'<div class="scen {css_cls}"><div class="scen-lbl">{lbl}</div><div class="scen-mult">—</div></div>'
            mult    = s.get('multiple','—')
            prob    = s.get('probability', 0)
            cap     = s.get('mktcap_10yr_b', 0) or s.get('revenue_10yr_b', 0)
            narr    = (s.get('narrative','') or '')[:80]
            cap_str = f'${cap:.1f}T' if cap >= 1 else (f'${cap:.0f}B' if cap else '')
            prob_str = f'{prob*100:.0f}% prob.' if prob else ''
            return (f'<div class="scen {css_cls}">'
                    f'<div class="scen-lbl">{lbl} · {prob_str}</div>'
                    f'<div class="scen-mult">{mult}x</div>'
                    f'<div class="scen-prob">{cap_str}</div>'
                    f'<div class="scen-note">{narr}</div>'
                    f'</div>')

        trk_cls = {'BULL':'trk-bull','BASE':'trk-base','BEAR':'trk-bear'}.get(tracking,'trk-base')
        html += f'''
<div class="sec">
  <div class="sec-lbl">AI Scenario Estimates <span style="font-weight:400; color:#9aa4b0; font-size:9px">(10yr indicative — grounded to current mktcap)</span></div>
  <div class="scen-grid">
    {_scen_cell(bull_s, 'sc-bull', 'Bull')}
    {_scen_cell(base_s, 'sc-base', 'Base')}
    {_scen_cell(bear_s, 'sc-bear', 'Bear')}
  </div>
  <div class="tracking-row">
    <span class="trk-badge {trk_cls}">Currently tracking: {tracking}</span>
    {'<div class="trk-note">' + trk_note + '</div>' if trk_note else ''}
  </div>
</div>
</div>'''  # close hcard

        return html

# ── MONTHLY PRICE TRACKER ─────────────────────────────────────────────────────
def update_holding_prices(portfolio: dict) -> dict:
    holdings = portfolio.get('holdings', [])
    if not holdings:
        return portfolio
    tickers = [h['ticker'] for h in holdings if h.get('status') == 'ACTIVE']
    if not tickers:
        return portfolio
    log.info(f'  Updating prices for {len(tickers)} active holdings...')
    for h in holdings:
        if h.get('status') != 'ACTIVE':
            continue
        try:
            info  = yf.Ticker(h['ticker']).info
            price = (info.get('regularMarketPrice') or
                     info.get('currentPrice') or
                     info.get('previousClose'))
            if price:
                h['current_price'] = round(float(price), 2)
            h['market_cap'] = info.get('marketCap', 0) or 0
            h['revenue']    = info.get('totalRevenue', 0) or 0
            # Refresh metrics that aren't stored in portfolio.json
            metrics = compute_all_metrics(h['ticker'], info)
            h['fcf_yield']       = metrics.get('fcf_yield')
            h['net_cash_m']      = metrics.get('net_cash_m')
            h['net_cash_flag']   = metrics.get('net_cash_flag', '—')
            h['rd_intensity']    = metrics.get('rd_intensity', 0)
            h['moat_proxy_label']= metrics.get('moat_proxy_label') or h.get('moat_type', '—')
            h['insider_ownership']= metrics.get('insider_pct') or h.get('insider_ownership', 0)
        except Exception:
            pass
    return portfolio

def compute_exit_returns(holding: dict) -> dict:
    ticker      = holding.get('ticker', '')
    entry_price = holding.get('entry_price') or holding.get('current_price')
    qqq_entry   = holding.get('qqq_price_at_entry')
    spy_entry   = holding.get('spy_price_at_entry')
    date_added  = holding.get('date_added', '')
    metrics = {
        'exit_price':       None,
        'return_pct':       None,
        'qqq_return_pct':   None,
        'spy_return_pct':   None,
        'alpha_vs_qqq':     None,
        'months_held':      None,
        'nzdusd_at_exit':   None,
    }
    try:
        info        = yf.Ticker(ticker).info
        exit_price  = (info.get('regularMarketPrice') or
                       info.get('currentPrice') or
                       info.get('previousClose'))
        if exit_price:
            metrics['exit_price'] = round(float(exit_price), 2)
        if entry_price and exit_price:
            metrics['return_pct'] = round((float(exit_price) - float(entry_price)) / float(entry_price) * 100, 1)
        if date_added:
            from_date = datetime.strptime(date_added[:10], '%Y-%m-%d')
            metrics['months_held'] = max(1, (datetime.now() - from_date).days // 30)
        bench = yf.download(['QQQ','SPY','NZDUSD=X'], period='1d', progress=False)
        if not bench.empty:
            qqq_exit = float(bench['Close']['QQQ'].iloc[-1])
            spy_exit = float(bench['Close']['SPY'].iloc[-1])
            usd_exit = float(bench['Close']['NZDUSD=X'].iloc[-1])
            metrics['nzdusd_at_exit'] = round(usd_exit, 4)
            if qqq_entry and qqq_exit:
                metrics['qqq_return_pct'] = round((qqq_exit - float(qqq_entry)) / float(qqq_entry) * 100, 1)
            if spy_entry and spy_exit:
                metrics['spy_return_pct'] = round((spy_exit - float(spy_entry)) / float(spy_entry) * 100, 1)
            if metrics['return_pct'] is not None and metrics['qqq_return_pct'] is not None:
                metrics['alpha_vs_qqq'] = round(metrics['return_pct'] - metrics['qqq_return_pct'], 1)
    except Exception as e:
        log.warning(f'  Exit returns failed for {ticker}: {e}')
    return metrics

# ── MAIN RUNNER ───────────────────────────────────────────────────────────────
def run_longterm_screener():
    log.info('=' * 66)
    log.info('  LONG-TERM INVESTMENT SCREENER v2.0')
    log.info(f'  Run date: {datetime.now().strftime("%Y-%m-%d %H:%M UTC")}')
    log.info(f'  Finnhub: {"✅ configured" if FINNHUB_API_KEY else "❌ missing"}')
    log.info(f'  Anthropic: {"✅ configured" if ANTHROPIC_API_KEY else "❌ missing"}')
    log.info('=' * 66)

    config    = load_config()
    _load_screening_config()
    portfolio = load_portfolio()
    portfolio.setdefault('holdings', [])
    portfolio.setdefault('run_history', [])
    portfolio.setdefault('exited', [])

    # One‑time backfill for 10‑K highlights (uncomment to run once)
    # for h in portfolio.get('holdings', []):
    #     if h.get('status') == 'ACTIVE' and 'ten_k_highlights' not in h:
    #         thesis = load_thesis(h['ticker'])
    #         if thesis and thesis.get('ten_k_highlights'):
    #             h['ten_k_highlights'] = thesis['ten_k_highlights']
    #             log.info(f'Backfilled 10‑K highlights for {h["ticker"]}')
    # save_portfolio(portfolio)

    # Step 1: Universe
    universe = load_checkpoint(1)
    if not universe:
        universe = build_universe(config)
    eligible_ipos = get_eligible_for_screening()
    if eligible_ipos:
        ipo_tickers = [e.get('entity_name','')[:6].upper().replace(' ','') for e in eligible_ipos]
        ipo_tickers = [t for t in ipo_tickers if len(t) >= 2]
        universe.extend(ipo_tickers)
        universe = sorted(set(universe))
        log.info(f'  Added {len(ipo_tickers)} IPO-eligible tickers to universe')
    save_checkpoint(1, universe)

    # Step 2: Fundamentals
    fundamentals = load_checkpoint(2)
    if not fundamentals:
        fundamentals = fetch_all_fundamentals(universe)
        save_checkpoint(2, fundamentals)

    # Step 3: Screening
    candidates = load_checkpoint(3)
    if not candidates:
        candidates = run_screening(fundamentals)
        save_checkpoint(3, candidates)

    # TRIAL MODE
    if RUN_MODE == 'TRIAL':
        log.info('TRIAL MODE: Stopping after Step 3')
        th, ts = generate_trial_email(candidates, len(fundamentals), len(universe))
        send_email(th, ts)
        clear_checkpoints()
        return

    # Quarterly megatrend review
    try:
        from quarterly_review import is_review_due
        if is_review_due():
            log.info('  Quarterly megatrend review due — running...')
            run_quarterly_review()
            print_score_report()
        else:
            log.info('  Megatrend scores current — skipping quarterly review')
    except Exception as e:
        log.warning(f'  Quarterly review failed: {e}')

    # IPO monitor
    try:
        ipo_data = run_ipo_monitor()
        log.info(f'  IPO watchlist: {len(ipo_data.get("watchlist",[]))} companies monitored')
    except Exception as e:
        log.warning(f'  IPO monitor failed: {e}')

    # Step 3.5: Technicals + Sentiment
    sent_tech_data = load_checkpoint(35)
    if not sent_tech_data:
        candidates, sent_tech_data = run_sentiment_technicals(candidates, portfolio)
        save_checkpoint(35, sent_tech_data)
    else:
        for ticker, cand in candidates.items():
            if ticker in sent_tech_data:
                cand['technicals'] = sent_tech_data[ticker]['technicals']
                cand['sentiment']  = sent_tech_data[ticker]['sentiment']

    # Refresh sentiment on existing portfolio holdings so 8-K and news counts are current
    _SENTIMENT_FIELDS = [
        'news_count', 'news_sentiment', 'reddit_mentions', 'reddit_sentiment',
        'overall_sentiment', 'signal_or_noise', 'key_themes',
        'sec_8k_count', 'sec_8k_events', 'sec_8k_highlights', 'sec_8k_latest_date',
        'news_intelligence', 'institutional_holders', 'mutualfund_holders',
    ]
    for _h in portfolio.get('holdings', []):
        _t = _h.get('ticker')
        if _t in sent_tech_data:
            _fresh = sent_tech_data[_t].get('sentiment', {})
            for _f in _SENTIMENT_FIELDS:
                if _f in _fresh:
                    _h[_f] = _fresh[_f]
            # reddit_mentions_30d stored differently — map it explicitly
            if 'reddit_mentions_30d' in _fresh:
                _h['reddit_mentions'] = _fresh['reddit_mentions_30d']

    # Refresh technicals on existing holdings too — this was missing entirely, so
    # above_200ma/pct_from_high/return_1yr/return_vs_qqq/CAGR/max_drawdown/trend
    # were frozen at whatever they were when a holding was first added, even
    # though Step 3.5 recomputes fresh technicals for every existing holding
    # every run. Only sentiment was ever being refreshed via _SENTIMENT_FIELDS.
    _TECHNICALS_FIELDS = [
        'above_200ma', 'pct_from_high', 'pct_from_200ma', 'return_1yr',
        'return_3yr_cagr', 'return_5yr_cagr', 'return_10yr_cagr',
        'max_drawdown', 'trend', 'years_listed', 'currency',
    ]
    for _h in portfolio.get('holdings', []):
        _t = _h.get('ticker')
        if _t in sent_tech_data:
            _fresh_tech = sent_tech_data[_t].get('technicals', {})
            for _f in _TECHNICALS_FIELDS:
                if _f in _fresh_tech:
                    _h[_f] = _fresh_tech[_f]
            # return_vs_qqq is stored under a different key in the raw technicals dict
            if 'return_vs_qqq_1yr' in _fresh_tech:
                _h['return_vs_qqq'] = _fresh_tech['return_vs_qqq_1yr']

    # Congressional stock disclosures — fetch once, attach to all portfolio holdings
    log.info('  Fetching US Congressional stock disclosures (House + Senate)...')
    _congress_data = fetch_congress_disclosures()
    for _h in portfolio.get('holdings', []):
        _tk = _h.get('ticker', '')
        _h['congress_disclosures'] = _congress_data.get(_tk, [])
        if _h['congress_disclosures']:
            log.info(f'  {_tk}: {len(_h["congress_disclosures"])} congressional tx in last 90 days')

    # Step 4-5: Research + Scenarios
    researched = load_checkpoint(4)
    if not researched:
        researched = run_research(candidates)
        researched = run_scenario_modeling(researched)
        save_checkpoint(4, researched)

    # Update prices
    portfolio = update_holding_prices(portfolio)

    # Retroactively sanitize existing holding scenarios (caps LLM hallucinations from prior runs)
    for _h in portfolio.get('holdings', []):
        if _h.get('status') == 'ACTIVE' and _h.get('scenario'):
            _mktcap_b = (_h.get('market_cap', 0) or 0) / 1e9
            if _mktcap_b > 0:
                _h['scenario'] = sanitize_scenario(
                    _h['scenario'], _h.get('ticker', ''),
                    _mktcap_b, _h.get('tier', 'T2'), _h.get('sector', '')
                )
                for _case in ['bull', 'base', 'bear']:
                    if _case in _h['scenario']:
                        _cap = (_h['scenario'][_case].get('mktcap_10yr_b', 0) or 0)
                        if _cap > 0:
                            _h['scenario'][_case]['multiple'] = round(_cap / _mktcap_b, 1)

    # Regenerate scenarios for holdings where bull == base == bear (LLM produced flat output),
    # where scenarios are inverted (bear > bull), or where scenarios are stale — bull is below
    # current market cap, meaning the stock has outrun all LLM projections since last write.
    _regen_needed = []
    for _h in portfolio.get('holdings', []):
        if _h.get('status') != 'ACTIVE' or not _h.get('scenario'):
            continue
        _sc = _h['scenario']
        _b1 = (_sc.get('bull') or {}).get('mktcap_10yr_b', 0) or 0
        _b2 = (_sc.get('base') or {}).get('mktcap_10yr_b', 0) or 0
        _b3 = (_sc.get('bear') or {}).get('mktcap_10yr_b', -1) or 0
        _mc_b     = (_h.get('market_cap', 0) or 0) / 1e9
        _flat     = (_b1 > 0) and (_b1 == _b2 == _b3)
        _inverted = (_b1 > 0) and (_b3 > _b1)
        _stale    = (_b1 > 0) and (_mc_b > 0) and (_b1 < _mc_b)
        if (_flat or _inverted or _stale) and _h.get('thesis_summary') and (_h.get('market_cap') or 0) > 0:
            if _stale and not _flat and not _inverted:
                log.info(f'  {_h.get("ticker","?")}: scenario stale — bull ${_b1:.1f}B < current ${_mc_b:.1f}B, queued for regen')
            _regen_needed.append(_h)

    if _regen_needed:
        log.info(f'  Regenerating scenarios for {len(_regen_needed)} holdings with flat/inverted outputs...')
        from llm_client import get_active_provider
        _prov, _ = get_active_provider()
        for _h in _regen_needed:
            _tk   = _h.get('ticker', '?')
            _tier = _h.get('tier', 'T2')
            _sect = _h.get('sector', 'Unknown')
            _mc   = (_h.get('market_cap', 0) or 0) / 1e9
            _rv   = (_h.get('revenue', 0) or 0) / 1e9
            _xtra = f"Kill risk: {_h.get('primary_risk','')}" if _tier == 'T3' else ''
            _pr   = SCENARIO_PROMPT.format(
                ticker=_tk, tier=_tier,
                current_mkt_cap_b=_mc, current_revenue_b=_rv,
                sector=_sect,
                thesis_summary=_h.get('thesis_summary', ''),
                verdict=_h.get('verdict', 'CORE_HOLD'),
                thesis_breaks_if=_h.get('thesis_breaks_if', 'Moat permanently eroded'),
                extra_context=_xtra,
            )
            try:
                _res = call_llm(_pr, system='Investment scenario analyst. Return ONLY valid JSON.', max_tokens=600)
                if _res['success']:
                    _nsc = sanitize_scenario(_res['data'], _tk, _mc, _tier, _sect)
                    for _case in ('bull', 'base', 'bear'):
                        if _case in _nsc:
                            _cap = (_nsc[_case].get('mktcap_10yr_b') or 0)
                            if _cap > 0 and _mc > 0:
                                _nsc[_case]['multiple'] = round(_cap / _mc, 1)
                    _nsc['written_date'] = datetime.now().isoformat()
                    _nsc['ticker'] = _tk
                    _h['scenario'] = _nsc
                    save_scenario(_tk, _nsc)
                    log.info(f'    {_tk}: Bull ${(_nsc.get("bull") or {}).get("mktcap_10yr_b",0):.0f}B '
                             f'Base ${(_nsc.get("base") or {}).get("mktcap_10yr_b",0):.0f}B '
                             f'Bear ${(_nsc.get("bear") or {}).get("mktcap_10yr_b",0):.0f}B')
                else:
                    log.warning(f'    {_tk}: scenario regen failed — {_res.get("error")}')
            except Exception as _e:
                log.warning(f'    {_tk}: scenario regen exception — {_e}')
            time.sleep(1)

    # Step 6: Portfolio construction
    decisions = construct_portfolio(researched, portfolio, config)

    for new in decisions['new_additions']:
        portfolio['holdings'].append(new)
    for exit_h in decisions['exits']:
        portfolio['holdings'] = [h for h in portfolio['holdings'] if h['ticker'] != exit_h['ticker']]
        exit_h['status']    = 'EXITED'
        exit_h['exit_date'] = datetime.now().strftime('%Y-%m-%d')
        exit_metrics = compute_exit_returns(exit_h)
        exit_h.update(exit_metrics)
        log.info(f'  EXIT {exit_h["ticker"]}: {exit_metrics.get("return_pct","?")}% return | '
                 f'Alpha vs QQQ: {exit_metrics.get("alpha_vs_qqq","?")}% | '
                 f'Held {exit_metrics.get("months_held","?")} months')
        portfolio['exited'].append(exit_h)
    for migration in decisions['migrations']:
        for h in portfolio['holdings']:
            if h['ticker'] == migration['ticker']:
                h['tier']           = migration['to_tier']
                h['tier_migrated']  = datetime.now().strftime('%Y-%m-%d')

    portfolio['run_history'].append({
        'date':            datetime.now().strftime('%Y-%m-%d'),
        'new_additions':   [h['ticker'] for h in decisions['new_additions']],
        'exits':           [h['ticker'] for h in decisions['exits']],
        'migrations':      [f"{m['ticker']}:{m['from_tier']}->{m['to_tier']}" for m in decisions['migrations']],
        'holdings_count':  len(portfolio['holdings'])
    })
    save_portfolio(portfolio)
    log.info(f'  Portfolio saved: {len(portfolio["holdings"])} holdings')

    # Step 7: Emails
    log.info('Step 7/7: Generating and sending emails...')
    month_str = datetime.now().strftime('%B %Y')

    if not portfolio.get('holdings') and not decisions.get('new_additions') and not decisions.get('screened_candidates'):
        log.warning('  Portfolio empty — falling back to screened candidates email')
        th, ts = generate_trial_email(candidates, len(fundamentals), len(universe))
        send_email(th, ts)
        clear_checkpoints()
        return

    action_html, action_subject = generate_action_email(decisions, portfolio)
    send_email(action_html, action_subject)
    time.sleep(5)

    try:
        ipo_summary = get_ipo_watchlist_summary()
        detail_html, detail_sub = generate_full_report(decisions, portfolio, researched, ipo_summary, FIF_THRESHOLD)
        if send_email(detail_html, detail_sub):
            log.info(f'  ✓ Email 2 sent: {detail_sub}')
        else:
            log.error('  ✗ Email 2 send returned False — check SMTP')
    except Exception as e:
        import traceback
        log.error(f'  ✗ Email 2 generation crashed: {e}')
        log.error(traceback.format_exc())

    if decisions.get('exits'):
        try:
            time.sleep(5)
            exit_html, exit_sub = generate_exit_email(decisions['exits'], month_str)
            if send_email(exit_html, exit_sub):
                log.info(f'  ✓ Email 3 sent: {exit_sub}')
        except Exception as e:
            import traceback
            log.error(f'  ✗ Email 3 crashed: {e}')
            log.error(traceback.format_exc())

    clear_checkpoints()
    log.info('=' * 66)
    log.info(f'  Run complete · {len(portfolio["holdings"])} holdings')
    log.info(f'  New: {[h["ticker"] for h in decisions["new_additions"]]}')
    log.info(f'  Exits: {[h["ticker"] for h in decisions["exits"]]}')
    log.info('=' * 66)

if __name__ == '__main__':
    run_longterm_screener()
