#!/usr/bin/env python3
"""
quarterly_review.py
===================
Layer 3 of the megatrend scoring system.

Runs once per quarter via GitHub Actions. Two jobs, in order:

  1. DISCOVERY — ask the LLM whether any structural megatrend for a 10-20yr
     investor exists that isn't already tracked. Accepted proposals are
     merged into universe_config.json's `megatrends` block (the same file a
     human would hand-edit) so research_metrics.py picks them up with no
     code changes, exactly like that file's own comment promises.

  2. SURVIVAL REVIEW — re-score every tracked megatrend (existing + anything
     just discovered) and get an explicit survives_10yr / survives_20yr
     verdict, not just a 1-10 number. A megatrend the LLM concludes won't
     even survive 10 years gets flagged `deprecated` in universe_config.json,
     which stops NEW candidates from being classified into it going forward
     (existing holdings keep their historical label — see
     research_metrics.compute_megatrend_alignment). If a deprecated sector's
     thesis later recovers, it gets un-deprecated — this is a two-way gate,
     not one-way decay.

Writes to:
  - universe_config.json  (megatrends block — new entries + deprecated flags)
  - data/megatrend_scores.json (scores + survival verdicts, 90-day TTL)

Both writes go through an atomic temp-file + os.replace so a killed run or a
concurrent job can never leave universe_config.json — read by every script,
every run — truncated or corrupted.

Cost: ~$0.20 per quarterly run (1 discovery call + ~10-13 review calls, small
prompts). Requires an LLM provider configured (NVIDIA free tier or
ANTHROPIC_API_KEY as fallback — see llm_client.py).
"""

import os, json, re, logging, time, tempfile
from datetime import datetime, timedelta
from pathlib import Path
from llm_client import call_llm, get_active_provider
from research_metrics import _load_megatrend_definitions

log = logging.getLogger('quarterly_review')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s'
)

BASE_DIR    = Path(__file__).parent
SCORES_FILE = BASE_DIR / 'data' / 'megatrend_scores.json'
CONFIG_FILE = BASE_DIR / 'universe_config.json'
SCORES_FILE.parent.mkdir(parents=True, exist_ok=True)

SCORE_TTL_DAYS = 90                          # how long scores stay valid before next quarterly review
MAX_NEW_MEGATRENDS_PER_RUN = 3                # cap discovery so the list can't run away in one quarter
KEYWORD_OVERLAP_DUPLICATE_THRESHOLD = 0.50    # overlap coefficient above which a proposal is a duplicate

SCORING_RUBRIC = (
    "  10 = Generational structural shift, 20+ year runway, multi-trillion TAM, strong policy tailwind, accelerating capital flows\n"
    "   9 = Major structural shift, 25-30yr runway, proven early commercial traction, policy support building\n"
    "   8 = Clear structural tailwind, 15-20yr runway, real capital flowing, some policy support\n"
    "   7 = Real tailwind but timing uncertain or TAM more constrained than alternatives\n"
    "   5 = Structural forces present but competitive or execution risk makes it marginal\n"
    "   3 = Narrative-driven, limited structural basis for 20-year compounding\n"
    "   1 = Speculative theme with no structural foundation"
)

# ── ATOMIC JSON HELPERS ────────────────────────────────────────────────────────
def _atomic_write_json(path: Path, data: dict) -> None:
    """
    Temp-file + os.replace instead of a plain open()+write(). universe_config.json
    is read by every script on every run (thresholds, email settings, megatrend
    definitions) — a truncated file from a killed process would break the whole
    pipeline, not just this one. Now that quarterly_review.py is the first
    automated writer of that file, this is no longer optional.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f'.{path.name}.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp_path, path)
    except Exception:
        try: os.unlink(tmp_path)
        except OSError: pass
        raise

def _load_universe_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
    return {}

def _current_megatrend_definitions() -> dict:
    """
    Single source of truth: universe_config.json's `megatrends` block, via the
    same loader research_metrics.py uses. This file used to keep its own
    hardcoded MEGATRENDS_FOR_REVIEW dict that had already drifted out of sync
    with universe_config.json (a category added there was never reviewed here
    unless someone remembered to copy it by hand) — read live instead.
    """
    return _load_megatrend_definitions()

# ── PROMPTS ─────────────────────────────────────────────────────────────────────
REVIEW_PROMPT = """You are a senior equity research analyst at a long-term investment fund with a strict 10-20 year mandate.

Today's date: {date}

Your task: assess the following investment megatrend for a long-term investor.

Megatrend: {label}
Base rationale: {rationale}
Current base score: {base_score}/10

Scoring criteria (1-10):
{rubric}

Consider:
1. Has policy support strengthened or weakened in the last 6 months?
2. Are capital flows accelerating into this sector?
3. Has the TAM estimate expanded or contracted based on recent evidence?
4. Has the technology/commercial maturity improved or stalled?
5. What is the competitive intensity trend?
6. Structural survival: is the core thesis (not any single company) still likely to be a major force in 10 years? In 20 years? A sector can score high today but still fail survival if it's likely to be commoditized, regulated away, or structurally disrupted within the horizon.

Based on your assessment as of {date}, provide:
- score (1-10)
- survives_10yr: true/false — will this remain a genuine structural tailwind in 10 years?
- survives_20yr: true/false — will it still be one in 20 years?
- a one-sentence rationale for any score change
- a specific observable signal that would cause you to revise the score up or down

Return ONLY valid JSON:
{{"score": number, "survives_10yr": true|false, "survives_20yr": true|false, "rationale": "one sentence", "upside_signal": "specific observable event that would increase score", "downside_signal": "specific observable event that would decrease score", "confidence": "HIGH|MEDIUM|LOW"}}"""

DISCOVERY_PROMPT = """You are a senior equity research strategist at a long-term investment fund with a strict 10-20 year mandate. Your job right now is not to pick stocks — it is to decide which STRUCTURAL SECTORS are worth hunting in for the next 10-20 years.

Today's date: {date}

You already track these {n} structural megatrends:
{existing_list}

Task: identify 0 to 3 NEW structural megatrends for a 10-20 year investor that are genuinely distinct from everything listed above — do not propose anything that substantially overlaps an existing category (e.g. do not propose "Advanced Semiconductors" if "AI Infrastructure" already covers it). Only propose a megatrend you are genuinely confident will still be a major structural force in 20 years. If nothing new clears that bar, return an empty list — proposing a mediocre category is worse than proposing nothing.

Scoring rubric for base_score (1-10):
{rubric}

For each new megatrend, provide:
  - key: short snake_case identifier (2-4 words, lowercase, underscores only), must not collide with or closely resemble any key already listed above
  - label: short display name
  - keywords: 6-10 category-level keywords for matching company descriptions — industry/technology terms only, NEVER specific company names or tickers
  - base_score: number, 1-10, using the rubric above
  - tailwind_years: how many years this structural tailwind should reasonably persist
  - rationale: one sentence
  - survives_20yr: true (only propose megatrends you believe clear this bar)

Return ONLY valid JSON:
{{"new_megatrends": [{{"key":"string","label":"string","keywords":["string","..."],"base_score":number,"tailwind_years":number,"rationale":"string","survives_20yr":true}}]}}
If nothing qualifies, return {{"new_megatrends": []}}."""

# ── DISCOVERY: propose, validate, dedupe ───────────────────────────────────────
def _slugify_key(raw: str) -> str:
    key = re.sub(r'[^a-z0-9]+', '_', str(raw).lower()).strip('_')
    return key or 'unnamed_megatrend'

def _keyword_overlap(a: list, b: list) -> float:
    """
    Overlap coefficient (|A∩B| / min(|A|,|B|)) between two keyword lists — NOT
    Jaccard. A freshly-proposed megatrend typically has ~6-10 keywords while a
    mature existing one can have 15+; Jaccard's union-sized denominator dilutes
    away exactly the case we need to catch (every one of the new keywords
    already covered by an existing category), since a small set can never push
    Jaccard high against a much larger one. The overlap coefficient measures
    "what fraction of the smaller list is already contained in the other",
    which is robust to that size mismatch.
    """
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))

def _validate_new_megatrend(candidate: dict, existing: dict, accepted_keys: set) -> tuple:
    """Returns (accepted: bool, key_or_rejection_reason: str)."""
    required = ('key', 'label', 'keywords', 'base_score', 'tailwind_years', 'rationale')
    if not all(k in candidate for k in required):
        return False, 'missing required field(s)'
    if not candidate.get('keywords') or not isinstance(candidate['keywords'], list):
        return False, 'no keywords'
    key = _slugify_key(candidate['key'])
    if key in existing or key in accepted_keys:
        return False, f'key collision: {key}'
    label_l = str(candidate['label']).strip().lower()
    if any(v['label'].strip().lower() == label_l for v in existing.values()):
        return False, f'label collision: {candidate["label"]}'
    new_kws = [str(k).lower() for k in candidate['keywords']]
    for v in existing.values():
        overlap = _keyword_overlap(new_kws, v.get('keywords', []))
        if overlap > KEYWORD_OVERLAP_DUPLICATE_THRESHOLD:
            return False, f'keyword overlap {overlap:.0%} with existing "{v["label"]}"'
    try:
        int(candidate['base_score']); int(candidate['tailwind_years'])
    except (TypeError, ValueError):
        return False, 'non-numeric base_score/tailwind_years'
    return True, key

def discover_new_megatrends(existing: dict) -> list:
    """
    Ask the LLM to propose new structural megatrends not already covered.
    Returns a list of validated, deduped megatrend dicts ready to merge into
    universe_config.json. Never raises — a failed or malformed LLM call just
    means zero new megatrends this quarter, same as "nothing qualified".
    """
    existing_list = '\n'.join(f'- {v["label"]}: {v.get("rationale","")}' for v in existing.values())
    prompt = DISCOVERY_PROMPT.format(
        date=datetime.now().strftime('%B %Y'),
        n=len(existing),
        existing_list=existing_list or '(none yet)',
        rubric=SCORING_RUBRIC,
    )
    try:
        result = call_llm(prompt, max_tokens=900)
        if not result.get('success'):
            log.warning(f'  Megatrend discovery call failed: {result.get("error")}')
            return []
        proposals = result['data'].get('new_megatrends', [])
        if not isinstance(proposals, list):
            return []
    except Exception as e:
        log.warning(f'  Megatrend discovery failed: {e}')
        return []

    accepted, accepted_keys = [], set()
    for cand in proposals[:10]:   # sanity cap on how many raw proposals we even consider
        if len(accepted) >= MAX_NEW_MEGATRENDS_PER_RUN:
            break
        if not isinstance(cand, dict):
            continue
        ok, key_or_reason = _validate_new_megatrend(cand, existing, accepted_keys)
        if not ok:
            log.info(f'  Discovery candidate rejected ({key_or_reason}): {cand.get("label", cand.get("key","?"))}')
            continue
        key = key_or_reason
        accepted_keys.add(key)
        entry = {
            'key':             key,
            'label':           str(cand['label']),
            'base_score':      max(1, min(10, int(cand['base_score']))),
            'tailwind_years':  max(1, int(cand['tailwind_years'])),
            'rationale':       str(cand.get('rationale', ''))[:300],
            'keywords':        [str(k).lower() for k in cand['keywords']][:12],
            'sic_codes':       [],   # LLM doesn't get to guess SIC codes — see research_metrics.py
            'deprecated':      False,
            'discovered_by':   'llm',
            'discovered_date': datetime.now().strftime('%Y-%m-%d'),
        }
        accepted.append(entry)
        log.info(f'  NEW MEGATREND: {entry["label"]} ({key}) — base {entry["base_score"]}/10')
    return accepted

def merge_new_megatrends(new_megatrends: list) -> None:
    if not new_megatrends:
        return
    cfg = _load_universe_config()
    cfg.setdefault('megatrends', {})
    for mt in new_megatrends:
        cfg['megatrends'][mt['key']] = mt
    _atomic_write_json(CONFIG_FILE, cfg)
    log.info(f'  Merged {len(new_megatrends)} new megatrend(s) into universe_config.json')

# ── SURVIVAL → DEPRECATION ─────────────────────────────────────────────────────
def apply_deprecations(review_detail: dict) -> dict:
    """
    Flip `deprecated` in universe_config.json based on this run's survival
    verdicts. survives_10yr == False deprecates a megatrend (stricter, higher-
    confidence bar than the 20yr flag, which is recorded but kept informational
    — a sector that's shaky at 20yr but solid at 10yr shouldn't be pruned from
    a systematic screener on a single quarter's forecast). A deprecated sector
    stops being assigned to NEW candidates; existing holdings are untouched.
    If a previously-deprecated sector's survives_10yr flips back to true, it's
    restored — a two-way gate, not one-way decay.
    """
    cfg = _load_universe_config()
    mt_cfg = cfg.get('megatrends', {})
    deprecated_now, undeprecated_now = [], []
    changed = False
    for key, detail in review_detail.items():
        if key not in mt_cfg:
            continue
        survives_10yr = detail.get('survives_10yr')
        if survives_10yr is None:
            continue   # malformed/failed review for this one — leave existing flag alone
        currently_dep = bool(mt_cfg[key].get('deprecated', False))
        if survives_10yr is False and not currently_dep:
            mt_cfg[key]['deprecated'] = True
            deprecated_now.append(key)
            changed = True
        elif survives_10yr is True and currently_dep:
            mt_cfg[key]['deprecated'] = False
            undeprecated_now.append(key)
            changed = True
    if changed:
        cfg['megatrends'] = mt_cfg
        _atomic_write_json(CONFIG_FILE, cfg)
        if deprecated_now:
            log.warning(f'  DEPRECATED (fails 10yr survival): {deprecated_now}')
        if undeprecated_now:
            log.info(f'  RESTORED (10yr survival recovered): {undeprecated_now}')
    return {'deprecated_this_run': deprecated_now, 'undeprecated_this_run': undeprecated_now}

# ── SCORES FILE ─────────────────────────────────────────────────────────────────
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

def save_scores(scores: dict, review_detail: dict, new_megatrends: list, deprecation_changes: dict) -> None:
    _, model = get_active_provider()
    data = {
        'last_reviewed': datetime.now().isoformat(),
        'next_review':   (datetime.now() + timedelta(days=SCORE_TTL_DAYS)).strftime('%Y-%m-%d'),
        'scores':        scores,
        'detail':        review_detail,
        'model_used':    model or 'unknown',
        'new_this_run':  [{'key': m['key'], 'label': m['label'], 'rationale': m['rationale']} for m in new_megatrends],
        **deprecation_changes,
    }
    _atomic_write_json(SCORES_FILE, data)
    log.info(f'  Scores saved to {SCORES_FILE}')

# ── MAIN REVIEW FUNCTION ──────────────────────────────────────────────────────
def run_quarterly_review(force: bool = False) -> dict:
    """
    Run the LLM quarterly review: discover new megatrends, then score +
    survival-review every tracked megatrend (existing + newly discovered).

    Args:
        force: skip the 90-day TTL check and run regardless.

    Returns:
        Dict of {megatrend_key: score}.
    """
    if not force and not is_review_due():
        log.info('Quarterly review not due yet. Use force=True to override.')
        existing = load_existing_scores()
        return existing.get('scores', {})

    provider, model = get_active_provider()
    if not provider:
        log.warning('No LLM provider configured — quarterly review skipped')
        return {k: v['base_score'] for k, v in _current_megatrend_definitions().items()}

    log.info('=' * 60)
    log.info('  QUARTERLY MEGATREND REVIEW')
    log.info(f'  Date: {datetime.now().strftime("%Y-%m-%d")}')
    log.info(f'  Provider: {provider} / {model}')
    log.info('=' * 60)

    # ── Step 1: discovery — is there a new sector worth tracking? ──
    existing_defs = _current_megatrend_definitions()
    log.info(f'  Reviewing {len(existing_defs)} tracked megatrends; checking for new ones...')
    new_megatrends = discover_new_megatrends(existing_defs)
    merge_new_megatrends(new_megatrends)

    # ── Step 2: score + survival review — existing AND newly discovered ──
    all_defs = _current_megatrend_definitions()   # reload: includes anything just merged
    scores, review_detail, changes = {}, {}, []

    for key, mt in all_defs.items():
        prompt = REVIEW_PROMPT.format(
            date=datetime.now().strftime('%B %Y'),
            label=mt['label'], rationale=mt['rationale'], base_score=mt['base_score'],
            rubric=SCORING_RUBRIC,
        )
        try:
            llm_result = call_llm(prompt, max_tokens=350)
            if not llm_result.get('success'):
                raise Exception(llm_result.get('error', 'LLM call failed'))
            result = llm_result['data']

            new_score = max(1, min(10, int(result.get('score', mt['base_score']))))
            scores[key] = new_score
            review_detail[key] = {
                'label':           mt['label'],
                'survives_10yr':   bool(result.get('survives_10yr', True)),
                'survives_20yr':   bool(result.get('survives_20yr', True)),
                'rationale':       result.get('rationale', ''),
                'upside_signal':   result.get('upside_signal', ''),
                'downside_signal': result.get('downside_signal', ''),
                'confidence':      result.get('confidence', '—'),
            }

            change_str = ''
            if new_score != mt['base_score']:
                direction = '+' if new_score > mt['base_score'] else ''
                change_str = f' ({direction}{new_score - mt["base_score"]} from base)'
                changes.append(f'{mt["label"]}: {mt["base_score"]} -> {new_score}')

            surv = f'10yr:{"Y" if review_detail[key]["survives_10yr"] else "N"} 20yr:{"Y" if review_detail[key]["survives_20yr"] else "N"}'
            log.info(f'  {mt["label"]:<28} {new_score}/10{change_str}  {surv}')
            if result.get('rationale') and new_score != mt['base_score']:
                log.info(f'    Rationale: {result["rationale"]}')

            time.sleep(0.5)  # rate limit courtesy

        except json.JSONDecodeError:
            # A failed call must never silently deprecate a sector — default to
            # "survives" so a bad LLM day can't masquerade as a survival verdict.
            log.warning(f'  {mt["label"]}: JSON parse error — using base score, assuming survival')
            scores[key] = mt['base_score']
            review_detail[key] = {'label': mt['label'], 'survives_10yr': True, 'survives_20yr': True,
                                   'rationale': 'review failed — defaulted', 'confidence': 'LOW'}
        except Exception as e:
            log.warning(f'  {mt["label"]}: Error ({e}) — using base score, assuming survival')
            scores[key] = mt['base_score']
            review_detail[key] = {'label': mt['label'], 'survives_10yr': True, 'survives_20yr': True,
                                   'rationale': f'review failed: {e}', 'confidence': 'LOW'}

    # ── Step 3: apply this run's survival verdicts as deprecation flags ──
    deprecation_changes = apply_deprecations(review_detail)

    save_scores(scores, review_detail, new_megatrends, deprecation_changes)

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
    return {k: v['base_score'] for k, v in _current_megatrend_definitions().items()}

def print_score_report() -> None:
    """Print current scores + survival verdicts to stdout for logging."""
    data   = load_existing_scores()
    scores = data.get('scores', {})
    detail = data.get('detail', {})
    last   = data.get('last_reviewed', 'Never')
    next_r = data.get('next_review', 'Unknown')

    print(f'\nMegatrend Scores — Last reviewed: {last[:10] if last != "Never" else last}  Next: {next_r}')
    print('-' * 70)
    def _flag(v):   # True/False/missing -> Y/N/? — a missing key is "not yet assessed", not a failure
        return 'Y' if v is True else ('N' if v is False else '?')

    for key, d in detail.items():
        score = scores.get(key, '—')
        conf  = d.get('confidence', '—')
        surv  = f'10yr:{_flag(d.get("survives_10yr"))} 20yr:{_flag(d.get("survives_20yr"))}'
        print(f'  {d.get("label", key):<28} {score}/10  {surv}  confidence: {conf}')
        if d.get('rationale'):
            print(f'    -> {d["rationale"]}')

    if data.get('new_this_run'):
        print(f'\n  NEW this quarter: {[m["label"] for m in data["new_this_run"]]}')
    if data.get('deprecated_this_run'):
        print(f'  DEPRECATED this quarter: {data["deprecated_this_run"]}')
    if data.get('undeprecated_this_run'):
        print(f'  RESTORED this quarter: {data["undeprecated_this_run"]}')
    print()

if __name__ == '__main__':
    import sys
    force = '--force' in sys.argv
    run_quarterly_review(force=force)
    print_score_report()
