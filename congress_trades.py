#!/usr/bin/env python3
"""
Senate congressional-trading data — the only FREE, official, ticker-level
source of US lawmaker stock trades.

Scope & honesty
━━━━━━━━━━━━━━━
• Source: the Senate Office of Public Records "eFD" system
  (https://efdsearch.senate.gov) — Periodic Transaction Reports (PTRs) filed
  under the STOCK Act. This is public, free, and requires no API key.
• Senate only. House disclosures are scanned image PDFs with no machine-readable
  tickers, and the community S3 dumps that used to cover both chambers
  (senate/house-stock-watcher) are dead (HTTP 403). We therefore report a
  "Senate" signal, never a blanket "Congress" one.
• Everything degrades gracefully. eFD sits behind a bot filter that answers
  non-browser clients with 403; if the session, a page, or the network fails
  for any reason, this module returns an empty index tagged
  source='unavailable' so the screener stays honest instead of breaking.

Design
━━━━━━
The whole index (ticker -> recent Senate trades) is built ONCE per run and
cached to disk with a TTL, then every candidate just does a dict lookup — we
never hit the network per-ticker.
"""

from __future__ import annotations

import json
import logging
import re
import ssl
import time
import http.cookiejar
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger('screener.congress')

_BASE = 'https://efdsearch.senate.gov'
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36')
# The browser-shaped headers below are what get us past the eFD bot filter — a
# plain urllib request (no Accept-Language / Sec-Fetch-*) is answered with 403.
_BROWSER = {
    'User-Agent': _UA,
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'identity',
    'Connection': 'keep-alive',
}

_CACHE_DIR = Path(__file__).parent / 'data' / 'cache'
_CACHE_FILE = _CACHE_DIR / 'senate_trades.json'

# Module-level memo so multiple callers in one run share a single build.
_INDEX_MEMO: dict | None = None


# ── low-level HTTP (session with the eFD terms accepted) ──────────────────────
def _csrf(cj: http.cookiejar.CookieJar) -> str:
    for c in cj:
        if c.name == 'csrftoken':
            return c.value
    return ''


def _open_session():
    """Return an opener that has accepted the eFD prohibition agreement, or None."""
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    ctx = ssl.create_default_context()  # noqa: F841 (opener uses default context)

    def _get(url, referer=None):
        h = dict(_BROWSER)
        h['Accept'] = ('text/html,application/xhtml+xml,application/xml;q=0.9,'
                       'image/avif,image/webp,*/*;q=0.8')
        h['Upgrade-Insecure-Requests'] = '1'
        h['Sec-Fetch-Dest'] = 'document'
        h['Sec-Fetch-Mode'] = 'navigate'
        h['Sec-Fetch-Site'] = 'same-origin' if referer else 'none'
        h['Sec-Fetch-User'] = '?1'
        if referer:
            h['Referer'] = referer
        with opener.open(urllib.request.Request(url, headers=h), timeout=30) as r:
            return r.read().decode('utf-8', 'replace')

    def _post(url, data, referer, ajax=False):
        h = dict(_BROWSER)
        h['Content-Type'] = 'application/x-www-form-urlencoded'
        h['Referer'] = referer
        h['Origin'] = _BASE
        if ajax:
            h['Accept'] = 'application/json, text/javascript, */*; q=0.01'
            h['X-Requested-With'] = 'XMLHttpRequest'
            h['X-CSRFToken'] = _csrf(cj)
            h['Sec-Fetch-Dest'] = 'empty'
            h['Sec-Fetch-Mode'] = 'cors'
            h['Sec-Fetch-Site'] = 'same-origin'
        else:
            h['Accept'] = ('text/html,application/xhtml+xml,application/xml;q=0.9,'
                           'image/avif,image/webp,*/*;q=0.8')
            h['Upgrade-Insecure-Requests'] = '1'
            h['Sec-Fetch-Dest'] = 'document'
            h['Sec-Fetch-Mode'] = 'navigate'
            h['Sec-Fetch-Site'] = 'same-origin'
            h['Sec-Fetch-User'] = '?1'
        body = urllib.parse.urlencode(data, doseq=True).encode()
        with opener.open(urllib.request.Request(url, data=body, headers=h), timeout=30) as r:
            return r.read().decode('utf-8', 'replace')

    try:
        _get(_BASE + '/search/')
        token = _csrf(cj)
        if not token:
            log.debug('  Senate eFD: no CSRF token on landing page')
            return None
        _post(_BASE + '/search/home/',
              {'csrfmiddlewaretoken': token, 'prohibition_agreement': '1'},
              referer=_BASE + '/search/')
        return {'get': _get, 'post': _post, 'cj': cj, 'token': token}
    except urllib.error.HTTPError as e:
        log.warning(f'  Senate eFD: session blocked (HTTP {e.code}) — congressional '
                    f'trades unavailable this run (source stays honest).')
        return None
    except Exception as e:
        log.debug(f'  Senate eFD: session error {type(e).__name__}: {e}')
        return None


# ── report listing + PTR parsing ─────────────────────────────────────────────
def _list_recent_ptrs(session: dict, start_date: str, max_filings: int) -> list[dict]:
    """Page through the PTR report list (newest first) until max_filings/older."""
    out: list[dict] = []
    page_len = 100
    start = 0
    while len(out) < max_filings:
        payload = {
            'draw': '1',
            'columns[0][data]': '0', 'columns[1][data]': '1', 'columns[2][data]': '2',
            'columns[3][data]': '3', 'columns[4][data]': '4',
            'order[0][column]': '4', 'order[0][dir]': 'desc',
            'start': str(start), 'length': str(page_len),
            'search[value]': '', 'search[regex]': 'false',
            'report_types': '[11]',   # 11 = Periodic Transaction Report
            'filer_types': '[]',
            'submitted_start_date': start_date,
            'submitted_end_date': '',
            'candidate_state': '', 'senator_state': '', 'office_id': '',
            'first_name': '', 'last_name': '',
            'csrfmiddlewaretoken': session['token'],
        }
        try:
            raw = session['post'](_BASE + '/search/report/data/', payload,
                                  referer=_BASE + '/search/', ajax=True)
            j = json.loads(raw)
        except Exception as e:
            log.debug(f'  Senate eFD: report page failed {type(e).__name__}: {e}')
            break
        rows = j.get('data', [])
        if not rows:
            break
        for row in rows:
            # row[3] holds the linked report title, row[4] the filing date
            link_cell = str(row[3]) if len(row) > 3 else ''
            m = re.search(r'href="([^"]+)"', link_cell)
            href = m.group(1) if m else ''
            date_str = re.sub(r'<[^>]+>', '', str(row[4])).strip() if len(row) > 4 else ''
            first = re.sub(r'<[^>]+>', '', str(row[0])).strip() if row else ''
            last = re.sub(r'<[^>]+>', '', str(row[1])).strip() if len(row) > 1 else ''
            # Only electronically-filed PTRs have a parseable table; paper filings
            # are image PDFs (/search/view/paper/...) — skip them.
            if '/ptr/' in href:
                out.append({'senator': f'{first} {last}'.strip(), 'url': _BASE + href,
                            'filed': date_str})
            if len(out) >= max_filings:
                break
        if len(rows) < page_len:
            break
        start += page_len
        time.sleep(0.4)
    return out


_AMOUNT_RE = re.compile(r'\$[\d,]+')


def _parse_ptr(session: dict, url: str) -> list[dict]:
    """Return a list of {ticker, action, tx_date, amount, owner} for one PTR."""
    try:
        html = session['get'](url, referer=_BASE + '/search/')
    except Exception as e:
        log.debug(f'  Senate eFD: PTR fetch failed {type(e).__name__}: {e}')
        return []
    txns: list[dict] = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S):
        cells = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', c)).strip()
                 for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        cells = [c for c in cells if c != '']
        if len(cells) < 6:
            continue
        # Typical order: [#, tx_date, owner, ticker, asset_name, asset_type, type, amount]
        tx_date = cells[1] if len(cells) > 1 else ''
        owner = cells[2] if len(cells) > 2 else ''
        ticker = cells[3] if len(cells) > 3 else ''
        asset = cells[4] if len(cells) > 4 else ''
        joined = ' '.join(cells)
        # Ticker: prefer the dedicated cell; fall back to a (TICK) in the asset name.
        if not re.fullmatch(r'[A-Z]{1,5}', ticker):
            m = re.search(r'\(([A-Z]{1,5})\)', asset)
            ticker = m.group(1) if m else ''
        if not ticker:
            continue
        low = joined.lower()
        if 'purchase' in low:
            action = 'BUY'
        elif 'sale' in low or 'sold' in low:
            action = 'SELL'
        elif 'exchange' in low:
            action = 'EXCHANGE'
        else:
            action = 'OTHER'
        amt_m = _AMOUNT_RE.findall(joined)
        amount = f'{amt_m[0]} - {amt_m[1]}' if len(amt_m) >= 2 else (amt_m[0] if amt_m else '')
        txns.append({'ticker': ticker, 'action': action, 'tx_date': tx_date,
                     'amount': amount, 'owner': owner})
    return txns


# ── public API ────────────────────────────────────────────────────────────────
def build_senate_index(days: int = 120, max_filings: int = 150,
                       cache_ttl_days: int = 7, force: bool = False) -> dict:
    """
    Build (or load from cache) an index of recent Senate trades keyed by ticker.

    Returns:
        {
          'source':          'efd' | 'unavailable',
          'as_of':           ISO timestamp,
          'window_days':     int,
          'filings_scanned': int,
          'by_ticker':       { 'AAPL': [ {senator, action, tx_date, amount, owner, filed}, ... ] }
        }
    """
    global _INDEX_MEMO
    if _INDEX_MEMO is not None and not force:
        return _INDEX_MEMO

    # Disk cache (shared across runs within TTL).
    if not force:
        try:
            if _CACHE_FILE.exists():
                cached = json.loads(_CACHE_FILE.read_text(encoding='utf-8'))
                as_of = datetime.fromisoformat(cached.get('as_of', '1970-01-01T00:00:00'))
                if datetime.now() - as_of < timedelta(days=cache_ttl_days):
                    log.info(f"  Senate trades: using cached index "
                             f"({cached.get('filings_scanned', 0)} filings, "
                             f"source={cached.get('source')})")
                    _INDEX_MEMO = cached
                    return cached
        except Exception as e:
            log.debug(f'  Senate trades: cache read failed {type(e).__name__}: {e}')

    index = {
        'source': 'unavailable',
        'as_of': datetime.now().isoformat(timespec='seconds'),
        'window_days': days,
        'filings_scanned': 0,
        'by_ticker': {},
    }

    session = _open_session()
    if not session:
        _INDEX_MEMO = index
        _write_cache(index)
        return index

    start_date = (datetime.now() - timedelta(days=days)).strftime('%m/%d/%Y 00:00:00')
    log.info(f'  Senate trades: querying eFD for PTRs since {start_date[:10]} '
             f'(cap {max_filings} filings)...')
    filings = _list_recent_ptrs(session, start_date, max_filings)
    if not filings:
        log.info('  Senate trades: no filings returned (or blocked) — marking unavailable.')
        _INDEX_MEMO = index
        _write_cache(index)
        return index

    by_ticker: dict[str, list] = {}
    scanned = 0
    for f in filings:
        rows = _parse_ptr(session, f['url'])
        scanned += 1
        for tx in rows:
            entry = {'senator': f['senator'], 'filed': f['filed'], **tx}
            by_ticker.setdefault(tx['ticker'], []).append(entry)
        time.sleep(0.4)  # be polite to a government server

    index['source'] = 'efd'
    index['filings_scanned'] = scanned
    index['by_ticker'] = by_ticker
    log.info(f'  Senate trades: indexed {scanned} filings covering '
             f'{len(by_ticker)} tickers.')
    _INDEX_MEMO = index
    _write_cache(index)
    return index


def _write_cache(index: dict) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(index), encoding='utf-8')
    except Exception as e:
        log.debug(f'  Senate trades: cache write failed {type(e).__name__}: {e}')


def congress_signal_for(ticker: str, index: dict | None) -> dict:
    """
    Summarise Senate activity for one ticker from a pre-built index.

    Fields (safe defaults so callers never KeyError):
        congress_source   : 'efd' | 'unavailable'
        congress_trades   : int   (# disclosed transactions in window)
        congress_buys     : int
        congress_sells    : int
        congress_signal   : 'BUYING' | 'SELLING' | 'MIXED' | 'NONE' | 'UNAVAILABLE'
        congress_note     : short human-readable summary
    """
    if not index or index.get('source') != 'efd':
        return {
            'congress_source': 'unavailable',
            'congress_trades': 0, 'congress_buys': 0, 'congress_sells': 0,
            'congress_signal': 'UNAVAILABLE',
            'congress_note': 'Senate disclosure feed unavailable this run.',
        }
    rows = (index.get('by_ticker') or {}).get((ticker or '').upper(), [])
    buys = sum(1 for r in rows if r.get('action') == 'BUY')
    sells = sum(1 for r in rows if r.get('action') == 'SELL')
    total = len(rows)
    if total == 0:
        signal = 'NONE'
        note = f'No Senate trades in {ticker} in the last {index.get("window_days", 120)} days.'
    elif buys and not sells:
        signal = 'BUYING'
    elif sells and not buys:
        signal = 'SELLING'
    else:
        signal = 'MIXED'
    if total:
        names = sorted({r.get('senator', '').strip() for r in rows if r.get('senator')})
        who = ', '.join(names[:3]) + ('…' if len(names) > 3 else '')
        note = (f'{total} Senate transaction(s) — {buys} buy / {sells} sell '
                f'(last {index.get("window_days", 120)}d){": " + who if who else ""}')
    return {
        'congress_source': 'efd',
        'congress_trades': total, 'congress_buys': buys, 'congress_sells': sells,
        'congress_signal': signal,
        'congress_note': note,
    }
