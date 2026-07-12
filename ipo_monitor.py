#!/usr/bin/env python3
"""
ipo_monitor.py
==============
SEC EDGAR IPO Pipeline Monitor.

Watches for S-1, F-1, S-4 (SPAC) and Form D (private placements) filings.
Maps each to a megatrend category.
Applies 180-day cooling period before entering the main screener.

Runs weekly via GitHub Actions (separate cron from main screener).
Outputs to data/ipo_watchlist.json which is read by screener.py.

Sources: All free, no API keys.
  - SEC EDGAR EFTS full-text search
  - SEC EDGAR submissions API
"""

import os, json, re, time, logging
from datetime import datetime, timedelta
from pathlib import Path
import requests

log = logging.getLogger('ipo_monitor')

BASE_DIR      = Path(__file__).parent
IPO_FILE      = BASE_DIR / 'data' / 'ipo_watchlist.json'
IPO_FILE.parent.mkdir(parents=True, exist_ok=True)

HEADERS = {'User-Agent': 'LongTermScreener vishvesh.niyati@gmail.com'}

# ── MEGATREND DEFINITIONS ─────────────────────────────────────────────────────
MEGATRENDS = {
    'ai_infrastructure': {
        'label':         'AI Infrastructure',
        'score':         10,
        'tailwind_years': 20,
        'keywords': [
            'artificial intelligence', 'machine learning', 'gpu', 'data center',
            'cloud computing', 'semiconductor', 'networking', 'connectivity',
            'inference', 'hyperscale', 'compute', 'cooling infrastructure'
        ],
        'sic_codes': ['3674', '3672', '7372', '3577', '3669'],
    },
    'nuclear_renaissance': {
        'label':         'Nuclear Renaissance',
        'score':         9,
        'tailwind_years': 30,
        'keywords': [
            'nuclear', 'reactor', 'uranium', 'small modular', 'smr',
            'advanced nuclear', 'molten salt', 'microreactor', 'fission',
            'nuclear fuel', 'enrichment'
        ],
        'sic_codes': ['4911', '1094'],
    },
    'space_commercial': {
        'label':         'Space Commercialisation',
        'score':         9,
        'tailwind_years': 25,
        'keywords': [
            'launch vehicle', 'rocket', 'satellite', 'orbit', 'space',
            'propulsion', 'spacecraft', 'constellation', 'reusable',
            'in-orbit', 'earth observation'
        ],
        'sic_codes': ['3812', '3761', '4812'],
    },
    'synthetic_biology': {
        'label':         'Synthetic Biology',
        'score':         9,
        'tailwind_years': 25,
        'keywords': [
            'rna', 'mrna', 'gene therapy', 'gene editing', 'crispr',
            'synthetic biology', 'biologics', 'cell therapy', 'immunotherapy',
            'genomics', 'proteomics', 'base editing', 'prime editing'
        ],
        'sic_codes': ['2836', '2835', '8731'],
    },
    'critical_minerals': {
        'label':         'Critical Minerals',
        'score':         8,
        'tailwind_years': 20,
        'keywords': [
            'tungsten', 'lithium', 'cobalt', 'rare earth', 'nickel',
            'manganese', 'graphite', 'vanadium', 'gallium', 'germanium',
            'critical mineral', 'strategic material', 'battery material'
        ],
        'sic_codes': ['1040', '1090', '1094', '2819'],
    },
    'defense_technology': {
        'label':         'Defense Technology',
        'score':         8,
        'tailwind_years': 20,
        'keywords': [
            'autonomous', 'unmanned', 'drone', 'cyber security', 'defense',
            'military', 'surveillance', 'counter-drone', 'electronic warfare',
            'c4isr', 'hypersonic', 'directed energy', 'anduril', 'shield ai'
        ],
        'sic_codes': ['3812', '3761', '3489', '7382'],
    },
    'aging_demographics': {
        'label':         'Aging Demographics',
        'score':         8,
        'tailwind_years': 25,
        'keywords': [
            'oncology', 'alzheimer', 'parkinson', 'cardiovascular', 'diabetes',
            'chronic disease', 'longevity', 'age-related', 'elder care',
            'therapeutics', 'precision medicine', 'rare disease', 'orphan drug'
        ],
        'sic_codes': ['2836', '2835', '8049', '8099'],
    },
    'energy_transition': {
        'label':         'Energy Transition',
        'score':         7,
        'tailwind_years': 20,
        'keywords': [
            'solar', 'wind', 'battery storage', 'grid storage', 'ev charging',
            'clean energy', 'renewable', 'hydrogen', 'fuel cell',
            'energy storage', 'power electronics', 'grid modernization'
        ],
        'sic_codes': ['3674', '3559', '3621', '4911'],
    },
    'fintech_inclusion': {
        'label':         'Fintech & Inclusion',
        'score':         7,
        'tailwind_years': 15,
        'keywords': [
            'digital payments', 'neobank', 'digital lending', 'insurtech',
            'wealthtech', 'embedded finance', 'crypto infrastructure',
            'remittance', 'financial inclusion', 'bnpl', 'open banking'
        ],
        'sic_codes': ['6022', '6159', '7372', '6199'],
    },
    'water_food_security': {
        'label':         'Water & Food Security',
        'score':         7,
        'tailwind_years': 25,
        'keywords': [
            'water treatment', 'desalination', 'irrigation', 'precision agriculture',
            'vertical farming', 'alternative protein', 'food security',
            'agritech', 'water scarcity', 'drought', 'food waste reduction'
        ],
        'sic_codes': ['4941', '0100', '2040', '3589'],
    },
}

# ── HELPERS ───────────────────────────────────────────────────────────────────
def load_watchlist() -> dict:
    if IPO_FILE.exists():
        with open(IPO_FILE) as f:
            return json.load(f)
    return {'watchlist': [], 'last_checked': None, 'form_d_pipeline': []}

def save_watchlist(data: dict) -> None:
    data['last_updated'] = datetime.now().isoformat()
    with open(IPO_FILE, 'w') as f:
        json.dump(data, f, indent=2, default=str)

def map_to_megatrend(description: str, sic: str = '') -> dict:
    """
    Map a company description to the best-fit megatrend.
    Returns megatrend key and score, or None if no strong match.
    """
    desc_lower = description.lower()
    best_match = None
    best_score = 0

    for key, mt in MEGATRENDS.items():
        hits = sum(1 for kw in mt['keywords'] if kw in desc_lower)
        sic_match = any(s in str(sic) for s in mt['sic_codes'])
        score = hits * 2 + (3 if sic_match else 0)
        if score > best_score:
            best_score = score
            best_match = key

    if best_score < 2:
        return {'megatrend': None, 'megatrend_label': 'General', 'megatrend_score': 0}

    mt = MEGATRENDS[best_match]
    return {
        'megatrend':       best_match,
        'megatrend_label': mt['label'],
        'megatrend_score': mt['score'],
        'tailwind_years':  mt['tailwind_years'],
    }

# ── SEC EDGAR FETCHERS ────────────────────────────────────────────────────────
def fetch_recent_ipo_filings(days_back: int = 30) -> list:
    """
    Fetch recent S-1, F-1, S-4 filings from SEC EDGAR.
    These represent the incoming IPO pipeline.
    """
    from_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    to_date   = datetime.now().strftime('%Y-%m-%d')
    filings   = []

    for form_type in ['S-1', 'F-1', 'S-4']:
        try:
            resp = requests.get(
                'https://efts.sec.gov/LATEST/search-index',
                params={
                    'q':         '',
                    'forms':     form_type,
                    'dateRange': 'custom',
                    'startdt':   from_date,
                    'enddt':     to_date,
                    '_source':   'period_of_report,entity_name,file_date,sic,display_names',
                    'hits.hits._source': 'entity_name,file_date,sic,display_names',
                },
                headers=HEADERS,
                timeout=20
            )
            if resp.status_code != 200:
                continue

            hits = resp.json().get('hits', {}).get('hits', [])
            for hit in hits[:50]:
                src = hit.get('_source', {})
                entity_name = src.get('entity_name', '')
                file_date   = src.get('file_date', '')
                sic         = src.get('sic', '')

                if not entity_name or not file_date:
                    continue

                # Skip amendments (S-1/A etc.)
                if '/A' in form_type:
                    continue

                filings.append({
                    'form_type':   form_type,
                    'entity_name': entity_name,
                    'file_date':   file_date,
                    'sic':         sic,
                    'description': src.get('display_names', [''])[0] if src.get('display_names') else '',
                })
            time.sleep(0.5)

        except Exception as e:
            log.warning(f'  S-1/F-1 fetch failed for {form_type}: {e}')

    return filings

def fetch_form_d_pipeline(days_back: int = 90) -> list:
    """
    Fetch Form D private placement filings.
    These are pre-IPO companies raising large rounds — future IPO candidates.
    Focus on large raises ($100M+) in megatrend categories.
    """
    from_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    to_date   = datetime.now().strftime('%Y-%m-%d')

    try:
        resp = requests.get(
            'https://efts.sec.gov/LATEST/search-index',
            params={
                'q':         '',
                'forms':     'D',
                'dateRange': 'custom',
                'startdt':   from_date,
                'enddt':     to_date,
            },
            headers=HEADERS,
            timeout=20
        )
        if resp.status_code != 200:
            return []

        hits = resp.json().get('hits', {}).get('hits', [])
        results = []
        for hit in hits[:100]:
            src = hit.get('_source', {})
            entity_name = src.get('entity_name', '')
            if not entity_name:
                continue
            results.append({
                'entity_name': entity_name,
                'file_date':   src.get('file_date', ''),
                'sic':         src.get('sic', ''),
            })
        return results

    except Exception as e:
        log.warning(f'  Form D fetch failed: {e}')
        return []

def get_cooling_end_date(file_date: str, megatrend_score: int = 0) -> str:
    """
    180-day cooling period from S-1 filing.
    Exceptional megatrend businesses (score >= 9): 90 days.
    """
    days = 90 if megatrend_score >= 9 else 180
    try:
        dt = datetime.strptime(file_date[:10], '%Y-%m-%d')
        return (dt + timedelta(days=days)).strftime('%Y-%m-%d')
    except Exception:
        return (datetime.now() + timedelta(days=180)).strftime('%Y-%m-%d')

def is_cooling_complete(cooling_end_date: str) -> bool:
    try:
        end = datetime.strptime(cooling_end_date[:10], '%Y-%m-%d')
        return datetime.now() > end
    except Exception:
        return False

# ── MAIN MONITOR FUNCTION ─────────────────────────────────────────────────────
def run_ipo_monitor() -> dict:
    """
    Main entry point. Called weekly by GitHub Actions.
    Returns updated watchlist with new filings mapped to megatrends.
    """
    log.info('IPO Monitor: checking SEC EDGAR for new filings...')
    watchlist_data = load_watchlist()
    existing_names = {w['entity_name'] for w in watchlist_data.get('watchlist', [])}

    new_filings = fetch_recent_ipo_filings(days_back=30)
    log.info(f'  Found {len(new_filings)} new IPO filings')

    new_count = 0
    for filing in new_filings:
        if filing['entity_name'] in existing_names:
            continue

        description = filing.get('description', '') + ' ' + filing.get('entity_name', '')
        mt          = map_to_megatrend(description, filing.get('sic', ''))

        # Only watch companies with megatrend alignment
        if mt['megatrend_score'] < 2:
            continue

        cooling_end = get_cooling_end_date(
            filing['file_date'],
            mt['megatrend_score']
        )
        days_remaining = max(0, (datetime.strptime(cooling_end, '%Y-%m-%d') - datetime.now()).days)

        entry = {
            **filing,
            **mt,
            'cooling_end_date':  cooling_end,
            'days_until_eligible': days_remaining,
            'cooling_complete':  is_cooling_complete(cooling_end),
            'added_to_watchlist': datetime.now().strftime('%Y-%m-%d'),
            'status':            'COOLING' if days_remaining > 0 else 'ELIGIBLE',
        }

        watchlist_data['watchlist'].append(entry)
        existing_names.add(filing['entity_name'])
        new_count += 1
        log.info(f'  Added to watchlist: {filing["entity_name"]} [{mt["megatrend_label"]}] '
                 f'cooling until {cooling_end}')

    # Update cooling status for existing entries
    for entry in watchlist_data.get('watchlist', []):
        entry['cooling_complete']    = is_cooling_complete(entry.get('cooling_end_date', ''))
        entry['days_until_eligible'] = max(0, (
            datetime.strptime(entry['cooling_end_date'][:10], '%Y-%m-%d') - datetime.now()
        ).days) if entry.get('cooling_end_date') else 0
        entry['status'] = 'ELIGIBLE' if entry['cooling_complete'] else 'COOLING'

    # Form D pipeline (private unicorns)
    form_d = fetch_form_d_pipeline(days_back=90)
    watchlist_data['form_d_pipeline'] = form_d[:50]

    watchlist_data['last_checked'] = datetime.now().isoformat()
    watchlist_data['new_this_run'] = new_count

    save_watchlist(watchlist_data)
    log.info(f'  IPO monitor complete: {new_count} new, {len(watchlist_data["watchlist"])} total watching')

    return watchlist_data

def get_eligible_for_screening() -> list:
    """Returns IPO candidates that have completed cooling period."""
    data = load_watchlist()
    return [w for w in data.get('watchlist', []) if w.get('cooling_complete')]

def get_ipo_watchlist_summary() -> dict:
    """Summary for inclusion in Email 2."""
    data    = load_watchlist()
    cooling = [w for w in data.get('watchlist', []) if not w.get('cooling_complete')]
    eligible = [w for w in data.get('watchlist', []) if w.get('cooling_complete')]

    return {
        'cooling':         cooling,
        'eligible':        eligible,
        'total_watching':  len(data.get('watchlist', [])),
        'last_checked':    data.get('last_checked', 'Never'),
    }

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s  %(levelname)-8s  %(message)s')
    run_ipo_monitor()
