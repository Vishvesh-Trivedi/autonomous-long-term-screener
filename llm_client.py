#!/usr/bin/env python3
"""
llm_client.py
=============
Provider-agnostic LLM client for research generation.

Supports:
  - NVIDIA NIM (free tier, 40 req/min, no credit card)
  - Anthropic Claude (if credits available)

Provider is selected in universe_config.json -> llm.provider.
Falls back gracefully if primary provider is unavailable.

The same prompts work across providers because we constrain output to JSON.
"""

import os, json, logging, time
from pathlib import Path

log = logging.getLogger('llm')

# ── PROVIDER CONFIGS ─────────────────────────────────────────────────────────
# All settings live in universe_config.json — these are documentation only.
PROVIDERS = {
    'nvidia': {
        'base_url':    'https://integrate.api.nvidia.com/v1',
        'api_key_env': 'NVIDIA_API_KEY',
        'default_model': 'meta/llama-3.3-70b-instruct',
        'rate_limit_per_min': 40,
    },
    'anthropic': {
        'api_key_env': 'ANTHROPIC_API_KEY',
        'default_model': 'claude-sonnet-4-5',
    },
}


def _load_llm_config() -> dict:
    """Load LLM provider config from universe_config.json."""
    try:
        cfg_file = Path(__file__).parent / 'universe_config.json'
        if cfg_file.exists():
            cfg = json.loads(cfg_file.read_text())
            return cfg.get('llm', {})
    except Exception:
        pass
    return {}


_NVIDIA_CALL_TIMES: list = []

def _throttle_nvidia_rpm() -> None:
    """
    Proactively pace calls to stay under NVIDIA NIM's free-tier rate limit
    (documented as 40 requests/minute — exceeding it returns HTTP 429).
    Sleeps before making a call that would push us over the limit, instead of
    firing and reacting to a 429 after the fact.
    """
    limit  = PROVIDERS['nvidia']['rate_limit_per_min']
    window = 60.0
    now = time.time()
    global _NVIDIA_CALL_TIMES
    _NVIDIA_CALL_TIMES = [t for t in _NVIDIA_CALL_TIMES if now - t < window]
    if len(_NVIDIA_CALL_TIMES) >= limit:
        sleep_for = window - (now - _NVIDIA_CALL_TIMES[0]) + 0.5
        if sleep_for > 0:
            log.warning(f'  NVIDIA RPM guard: {len(_NVIDIA_CALL_TIMES)} calls in the last {window:.0f}s '
                        f'(limit {limit}) — sleeping {sleep_for:.1f}s')
            time.sleep(sleep_for)
    _NVIDIA_CALL_TIMES.append(time.time())


def is_provider_available(provider: str = None) -> bool:
    """Check if a provider is configured and has an API key."""
    if provider is None:
        provider = _load_llm_config().get('provider', 'nvidia')
    if provider not in PROVIDERS:
        return False
    key_env = PROVIDERS[provider]['api_key_env']
    return bool(os.environ.get(key_env))


def get_active_provider() -> tuple:
    """
    Returns (provider_name, model_name) based on config + key availability.
    Falls back to alternative if primary is unavailable.
    """
    cfg = _load_llm_config()
    primary  = cfg.get('provider', 'nvidia')
    fallback = cfg.get('fallback_provider', 'anthropic')
    model    = cfg.get('model')

    if is_provider_available(primary):
        active_model = model or PROVIDERS[primary]['default_model']
        return primary, active_model

    if fallback and is_provider_available(fallback):
        log.warning(f'  Primary LLM ({primary}) unavailable — falling back to {fallback}')
        active_model = cfg.get('fallback_model') or PROVIDERS[fallback]['default_model']
        return fallback, active_model

    return None, None


# ── UNIFIED CALL ──────────────────────────────────────────────────────────────
def call_llm(prompt: str, system: str = None, max_tokens: int = 2000,
             temperature: float = 0.3, model_override: str = None) -> dict:
    """
    Send a prompt to the configured LLM and return parsed JSON.

    Returns:
        {'success': bool, 'data': dict|None, 'error': str|None, 'provider': str}
    """
    cfg = _load_llm_config()
    fallback_provider = cfg.get('fallback_provider', 'anthropic')

    provider, model = get_active_provider()
    if model_override and provider == 'nvidia':
        model = model_override
    if not provider:
        return {'success': False, 'data': None,
                'error': 'No LLM provider configured with valid API key',
                'provider': None}

    system_msg = system or (
        "You are a senior equity research analyst. "
        "Return ONLY valid JSON. No preamble, no markdown, no code fences."
    )

    def _try_provider(prov: str, mdl: str) -> tuple:
        """Attempt one provider end-to-end. Returns (text, error) — text is '' on failure."""
        try:
            if prov == 'nvidia':
                # Retry up to 3 times. Two distinct failure modes observed in
                # practice: (1) HTTP 429 when the 40 req/min free-tier limit is
                # hit; (2) a 200 OK with genuinely empty content, which
                # free-tier NIM capacity produces under load even within the
                # rate limit — this turns out to be far more common for larger
                # completions (long thesis/scenario JSON) than short ones.
                text = ''
                for _attempt in range(3):
                    _throttle_nvidia_rpm()
                    try:
                        text = _call_nvidia(prompt, system_msg, mdl, max_tokens, temperature)
                    except Exception as e:
                        is_rate_limited = getattr(e, 'status_code', None) == 429 or '429' in str(e)
                        if is_rate_limited and _attempt < 2:
                            log.warning(f'  NVIDIA rate-limited (attempt {_attempt+1}/3) — backing off 15s...')
                            time.sleep(15)
                            continue
                        return '', str(e)
                    if text:
                        return text, None
                    if _attempt < 2:
                        log.warning(f'  NVIDIA empty response (attempt {_attempt+1}/3) — retrying...')
                        time.sleep(3)
                return '', 'NVIDIA returned empty after 3 attempts'
            elif prov == 'anthropic':
                text = _call_anthropic(prompt, system_msg, mdl, max_tokens, temperature)
                return text, (None if text else 'Anthropic returned an empty response')
            return '', f'Unknown provider: {prov}'
        except Exception as e:
            return '', str(e)

    def _parse(text: str, prov: str, mdl: str) -> dict:
        try:
            cleaned = text.strip()
            if cleaned.startswith('```'):
                lines = cleaned.split('\n')
                cleaned = '\n'.join(lines[1:-1] if lines[-1].startswith('```') else lines[1:])
            if '{' in cleaned:
                start = cleaned.find('{')
                end   = cleaned.rfind('}') + 1
                cleaned = cleaned[start:end]
            data = json.loads(cleaned)
            return {'success': True, 'data': data, 'error': None, 'provider': prov, 'model': mdl}
        except json.JSONDecodeError as e:
            return {'success': False, 'data': None,
                    'error': f'JSON parse failed: {e}. Response: {text[:200]}', 'provider': prov}

    text, err = _try_provider(provider, model)
    result = _parse(text, provider, model) if text else {'success': False, 'data': None, 'error': err, 'provider': provider}

    # Call-level fallback: if the primary provider failed (empty response OR
    # unparseable JSON), automatically retry the same prompt on the configured
    # fallback provider instead of giving up - the previous behavior only fell
    # back when the primary's API key was entirely absent, not when individual
    # calls failed. This is what actually determines whether new candidates
    # get a real thesis or end up as ERROR/PARSE_ERROR and never join the
    # portfolio.
    if not result['success'] and fallback_provider and fallback_provider != provider and is_provider_available(fallback_provider):
        log.warning(f'  {provider} failed ({result["error"]}) — falling back to {fallback_provider} for this call')
        fb_model = cfg.get('fallback_model') or PROVIDERS[fallback_provider]['default_model']
        fb_text, fb_err = _try_provider(fallback_provider, fb_model)
        fb_result = _parse(fb_text, fallback_provider, fb_model) if fb_text else \
            {'success': False, 'data': None, 'error': fb_err, 'provider': fallback_provider}
        if fb_result['success']:
            return fb_result
        result['error'] = f'{result["error"]}; fallback {fallback_provider} also failed: {fb_result["error"]}'

    return result


# ── PROVIDER-SPECIFIC IMPLEMENTATIONS ─────────────────────────────────────────
def _call_nvidia(prompt: str, system: str, model: str,
                 max_tokens: int, temperature: float) -> str:
    """Call NVIDIA NIM via OpenAI-compatible API."""
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError('openai package not installed — add to requirements.txt')

    client = OpenAI(
        base_url = PROVIDERS['nvidia']['base_url'],
        api_key  = os.environ.get('NVIDIA_API_KEY'),
    )
    resp = client.chat.completions.create(
        model       = model,
        messages    = [
            {'role': 'system', 'content': system},
            {'role': 'user',   'content': prompt},
        ],
        temperature = temperature,
        max_tokens  = max_tokens,
        top_p       = 0.9,
    )
    return resp.choices[0].message.content or ''


def _call_anthropic(prompt: str, system: str, model: str,
                    max_tokens: int, temperature: float) -> str:
    """Call Anthropic Claude API."""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError('anthropic package not installed')

    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    resp = client.messages.create(
        model       = model,
        max_tokens  = max_tokens,
        temperature = temperature,
        system      = system,
        messages    = [{'role': 'user', 'content': prompt}],
    )
    return resp.content[0].text


# ── BACKWARD-COMPATIBLE WRAPPER (for existing screener.py call sites) ────────
def research_stock(prompt: str, system: str = None, max_tokens: int = 2000) -> dict:
    """
    Drop-in replacement for the existing Anthropic call pattern.

    Returns the SAME dict shape the screener expects:
        {'verdict':..., 'thesis':..., 'scenarios':...}
    or an error envelope if the call failed.
    """
    result = call_llm(prompt, system, max_tokens)
    if result['success']:
        return result['data']
    # Match the existing error contract used by construct_portfolio
    if result.get('error') and 'JSON parse' in result['error']:
        return {'verdict': 'PARSE_ERROR', 'error': result['error']}
    return {'verdict': 'ERROR', 'error': result.get('error', 'Unknown LLM error')}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    print("LLM Client self-test")
    print("-" * 50)
    provider, model = get_active_provider()
    print(f"Active provider: {provider}")
    print(f"Active model:    {model}")
    print(f"NVIDIA available:    {is_provider_available('nvidia')}")
    print(f"Anthropic available: {is_provider_available('anthropic')}")
    if provider:
        print(f"\nSending test prompt...")
        result = call_llm(
            'Score the AI infrastructure megatrend 1-10 for a 20-year investor. '
            'Return JSON: {"score": number, "reason": "one sentence"}'
        )
        print(f"Success: {result['success']}")
        print(f"Data:    {result.get('data')}")
        if result.get('error'):
            print(f"Error:   {result['error']}")
