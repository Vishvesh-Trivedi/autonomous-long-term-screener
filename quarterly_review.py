#!/usr/bin/env python3
"""
quarterly_review.py
===================
Layer 3 of the megatrend scoring system.

Runs once per quarter via GitHub Actions.
Uses Claude to re-score each megatrend based on:
  - Recent policy developments
  - Capital flow signals
  - TAM estimate updates
  - Technology maturity changes

Writes to data/megatrend_scores.json which overrides base scores
in research_metrics.py for the next 90 days.

Cost: ~$0.15 per quarterly run (10 megatrends × small prompt).
Requires: ANTHROPIC_API_KEY
"""

import os, json, re, logging, time
from datetime import datetime, timedelta
from pathlib import Path
from llm_client import call_llm, get_active_provider

log = logging.getLogger('quarterly_review')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s'
)

BASE_DIR    = Path(__file__).parent
SCORES_FILE = BASE_DIR / 'data' / 'megatrend_scores.json'
SCORES_FILE.parent.mkdir(parents=True, exist_ok=True)

# How long scores stay valid before next quarterly review
SCORE_TTL_DAYS = 90

# ── SCORING PROMPT ────────────────────────────────────────────────────────────
REVIEW_PROMPT = """You are a senior equity research analyst at a long-term investment fund with a 20-year mandate.

Today's date: {date}

Your task: Score the following investment megatrend for a long-term investor (20-year horizon).

Megatrend: {label}
Base rationale: {rationale}
Current base score: {base_score}/10

Scoring criteria (1-10):
  10 = Generational structural shift, 20+ year runway, multi-trillion TAM, strong policy tailwind, accelerating capital flows
   9 = Major structural shift, 25-30yr runway, proven early commercial traction, policy support building
   8 = Clear structural tailwind, 15-20yr runway, real capital flowing, some policy support
   7 = Real tailwind but timing uncertain or TAM more constrained than alternatives
   5 = Structural forces present but competitive or execution risk makes it marginal
   3 = Narrative-driven, limited structural basis for 20-year compounding
   1 = Speculative theme with no structural foundation

Consider:
1. Has policy support strengthened or weakened in the last 6 months?
2. Are capital flows accelerating into this sector?
3. Has the TAM estimate expanded or contracted based on recent evidence?
4. Has the technology/commercial maturity improved or stalled?
5. What is the competitive intensity trend?

Based on your assessment of current conditions as of {date}, provide:
- Your score (1-10)
- A one-sentence rationale for any change from the base score
- A specific observable signal that would cause you to revise the score up or down

Return ONLY valid JSON:
{{"score": number, "rationale": "one sentence", "upside_signal": "specific observable event that would increase score", "downside_signal": "specific observable event that would decrease score", "confidence": "HIGH|MEDIUM|LOW"}}"""

# ── MEGATREND DEFINITIONS FOR REVIEW ─────────────────────────────────────────
# These must match keys in research_metrics.py MEGATRENDS
MEGATRENDS_FOR_REVIEW = {
    'ai_infrastructure':  {
        'label': 'AI Infrastructure',
        'base_score': 10,
        'rationale': 'Generational compute buildout. Every hyperscaler committed. No ceiling visible.',
    },
    'nuclear_renaissance': {
        'label': 'Nuclear Renaissance',
        'base_score': 9,
        'rationale': 'Clean baseload power is the only 24/7 zero-carbon option. SMR economics improving.',
    },
    'space_commercial': {
        'label': 'Space Commercialisation',
        'base_score': 9,
        'rationale': 'Launch costs falling 10x per decade. Satellite internet, earth observation, in-orbit services.',
    },
    'synthetic_biology': {
        'label': 'Synthetic Biology',
        'base_score': 9,
        'rationale': 'RNA/gene editing platforms attack every chronic disease. Multi-trillion TAM.',
    },
    'critical_minerals': {
        'label': 'Critical Minerals',
        'base_score': 8,
        'rationale': 'Energy transition requires 6x more minerals by 2040. Supply geopolitically constrained.',
    },
    'defense_technology': {
        'label': 'Defense Technology',
        'base_score': 8,
        'rationale': 'Geopolitical fragmentation driving defense budgets up globally for decades.',
    },
    'aging_demographics': {
        'label': 'Aging Demographics',
        'base_score': 8,
        'rationale': 'Global 65+ population doubles by 2050. Chronic disease, longevity medicine.',
    },
    'energy_transition': {
        'label': 'Energy Transition',
        'base_score': 7,
        'rationale': 'Real tailwind but execution risk and policy dependency higher than other categories.',
    },
    'fintech_inclusion': {
        'label': 'Fintech & Inclusion',
        'base_score': 7,
        'rationale': 'Digital finance has shorter runway — winner-takes-most risk at this stage.',
    },
    'water_food': {
        'label': 'Water & Food Security',
        'base_score': 7,
        'rationale': 'Climate scarcity is real but investment solutions are early stage.',
    },
}

# ── HELPERS ───────────────────────────────────────────────────────────────────
def load_existing_scores() -> dict:
    if SCORES_FILE.exists():
        with open(SCORES_FILE) as f:
            return json.load(f)
    return {}

def is_review_due() -> bool:
    """Check if 90-day TTL has expired."""
    existing = load_existing_scores()
    if not existing.get('last_reviewed'):
        return True
    last = datetime.fromisoformat(existing['last_reviewed'])
    return datetime.now() > last + timedelta(days=SCORE_TTL_DAYS)

def save_scores(scores: dict, review_results: dict) -> None:
    _, model = get_active_provider()
    data = {
        'last_reviewed': datetime.now().isoformat(),
        'next_review':   (datetime.now() + timedelta(days=SCORE_TTL_DAYS)).strftime('%Y-%m-%d'),
        'scores':        scores,
        'detail':        review_results,
        'model_used':    model or 'unknown',
    }
    with open(SCORES_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    log.info(f'  Scores saved to {SCORES_FILE}')

# ── MAIN REVIEW FUNCTION ──────────────────────────────────────────────────────
def run_quarterly_review(force: bool = False) -> dict:
    """
    Run Claude quarterly review of all megatrend scores.

    Args:
        force: Skip TTL check and run regardless.

    Returns:
        Dict of {megatrend_key: score} with updated scores.
    """
    if not force and not is_review_due():
        log.info('Quarterly review not due yet. Use force=True to override.')
        existing = load_existing_scores()
        return existing.get('scores', {})

    provider, model = get_active_provider()
    if not provider:
        log.warning('No LLM provider configured — quarterly review skipped')
        return {k: v['base_score'] for k, v in MEGATRENDS_FOR_REVIEW.items()}

    log.info('=' * 60)
    log.info('  QUARTERLY MEGATREND REVIEW')
    log.info(f'  Date: {datetime.now().strftime("%Y-%m-%d")}')
    log.info(f'  Provider: {provider} / {model}')
    log.info(f'  Reviewing {len(MEGATRENDS_FOR_REVIEW)} megatrends')
    log.info('=' * 60)

    scores       = {}
    review_detail= {}
    date_str     = datetime.now().strftime('%B %Y')
    changes      = []

    for key, mt in MEGATRENDS_FOR_REVIEW.items():
        prompt = REVIEW_PROMPT.format(
            date       = date_str,
            label      = mt['label'],
            rationale  = mt['rationale'],
            base_score = mt['base_score'],
        )

        try:
            llm_result = call_llm(prompt, max_tokens=300)
            if not llm_result.get('success'):
                raise Exception(llm_result.get('error', 'LLM call failed'))
            result = llm_result['data']

            new_score = int(result.get('score', mt['base_score']))
            new_score = max(1, min(10, new_score))   # clamp 1-10
            scores[key] = new_score
            review_detail[key] = result

            change_str = ''
            if new_score != mt['base_score']:
                direction = '+' if new_score > mt['base_score'] else ''
                change_str = f' ({direction}{new_score - mt["base_score"]} from base)'
                changes.append(f'{mt["label"]}: {mt["base_score"]} → {new_score}')

            log.info(f'  {mt["label"]:<28} {new_score}/10{change_str}')
            if result.get('rationale') and new_score != mt['base_score']:
                log.info(f'    Rationale: {result["rationale"]}')

            time.sleep(0.5)  # Rate limit courtesy

        except json.JSONDecodeError as e:
            log.warning(f'  {mt["label"]}: JSON parse error — using base score')
            scores[key] = mt['base_score']
        except Exception as e:
            log.warning(f'  {mt["label"]}: Error ({e}) — using base score')
            scores[key] = mt['base_score']

    save_scores(scores, review_detail)

    log.info('=' * 60)
    if changes:
        log.info('  Score changes this quarter:')
        for c in changes:
            log.info(f'    {c}')
    else:
        log.info('  No score changes — all megatrends stable')
    log.info('=' * 60)

    return scores

def get_current_scores() -> dict:
    """
    Get current effective scores (from file if valid, else base scores).
    Called by research_metrics._load_megatrend_scores().
    """
    existing = load_existing_scores()
    if existing.get('scores') and not is_review_due():
        return existing['scores']
    return {k: v['base_score'] for k, v in MEGATRENDS_FOR_REVIEW.items()}

def print_score_report() -> None:
    """Print current scores to stdout for logging."""
    data = load_existing_scores()
    scores = data.get('scores', {})
    detail = data.get('detail', {})
    last   = data.get('last_reviewed', 'Never')
    next_r = data.get('next_review', 'Unknown')

    print(f'\nMegatrend Scores — Last reviewed: {last[:10]}  Next: {next_r}')
    print('-' * 70)
    for key, mt in MEGATRENDS_FOR_REVIEW.items():
        score = scores.get(key, mt['base_score'])
        base  = mt['base_score']
        d     = detail.get(key, {})
        conf  = d.get('confidence','—')
        diff  = score - base
        diff_str = f'({"+"+str(diff) if diff>0 else str(diff)} vs base)' if diff != 0 else '(no change)'
        print(f'  {mt["label"]:<28} {score}/10  {diff_str:<20} confidence: {conf}')
        if d.get('rationale') and diff != 0:
            print(f'    → {d["rationale"]}')
    print()

if __name__ == '__main__':
    import sys
    force = '--force' in sys.argv
    run_quarterly_review(force=force)
    print_score_report()
