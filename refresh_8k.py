"""Re-fetch 8-K highlights + news highlights for all holdings, update portfolio.json."""
import json, os, sys, pathlib, logging
os.chdir(os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(message)s')

from screener import fetch_sec_8k, fetch_finnhub_news, extract_news_highlights, send_email
from email_report import generate_full_report
from email_builder import generate_action_email

portfolio = json.load(open('data/portfolio.json'))

# Load scenarios
for h in portfolio.get('holdings', []):
    if not h.get('scenario'):
        sp = pathlib.Path('data/scenarios') / f"{h.get('ticker','')}.json"
        if sp.exists():
            h['scenario'] = json.loads(sp.read_text())

active = [h for h in portfolio.get('holdings', []) if h.get('status') == 'ACTIVE']

for h in active:
    tk = h.get('ticker', '')

    # Always refresh 8-K
    result = fetch_sec_8k(tk)
    count  = result.get('sec_8k_count', 0)
    highlights = result.get('sec_8k_highlights', [])
    h['sec_8k_count']       = count
    h['sec_8k_events']      = result.get('sec_8k_events', [])
    h['sec_8k_highlights']  = highlights
    h['sec_8k_latest_date'] = result.get('sec_8k_latest_date', '')

    days_label = result.get('sec_8k_latest_date', '')

    # Admin-only filings that warrant news fallback
    _ADMIN_LABELS = (
        'annual meeting: routine director elections',
        're-appointed as auditor',
        'will arrange to mail paper copies',
        'annual report for the year ended',
        'does not provide actual reported results',
    )
    is_admin_only = (
        count > 0 and
        highlights and
        len(highlights) == 1 and
        any(ph in highlights[0].lower() for ph in _ADMIN_LABELS)
    )

    if count == 0 or is_admin_only:
        # No filing or filing only contains admin noise — supplement with news
        news = fetch_finnhub_news(tk)
        news_hl = extract_news_highlights(tk, news.get('headlines', []))
        h['news_highlights'] = news_hl
        if is_admin_only and not news_hl:
            pass  # keep the admin message as only content
        elif is_admin_only and news_hl:
            h['sec_8k_highlights'] = []  # news is more useful
        status = f'admin-only [{days_label}] + {len(news_hl)} news' if is_admin_only else f'no filing + {len(news_hl)} news'
        print(f'{tk}: {status}')
    else:
        h['news_highlights'] = []
        print(f'{tk}: {count} filing(s) [{days_label}], {len(highlights)} highlights')

# Save updated portfolio
json.dump(portfolio, open('data/portfolio.json', 'w'), indent=2)
print('\nPortfolio saved.')

# Resend both emails
rb_html, rb_sub = generate_full_report({'screened_candidates': []}, portfolio, {})
ok1 = send_email(rb_html, '[8K REFRESH] ' + rb_sub)
print(f'Research Brief: {"SENT" if ok1 else "FAILED"}')

ae_html, ae_sub = generate_action_email({'new_additions': [], 'exits': [], 'migrations': []}, portfolio)
ok2 = send_email(ae_html, '[8K REFRESH] ' + ae_sub)
print(f'Action Email:   {"SENT" if ok2 else "FAILED"}')
