"""Generate HTML preview of both emails for layout inspection."""
import json, sys, pathlib, os
sys.stdout.reconfigure(encoding='utf-8')
os.chdir(os.path.dirname(__file__))
from dotenv import load_dotenv; load_dotenv()
from email_report import generate_full_report
from email_builder import generate_action_email

portfolio = json.load(open('data/portfolio.json'))
for h in portfolio.get('holdings', []):
    if not h.get('scenario'):
        sp = pathlib.Path('data/scenarios') / f"{h.get('ticker','')}.json"
        if sp.exists():
            h['scenario'] = json.loads(sp.read_text())

rb_html, rb_sub = generate_full_report({'screened_candidates': []}, portfolio, {})
ae_html, ae_sub = generate_action_email({'new_additions': [], 'exits': [], 'migrations': []}, portfolio)

open('preview_research.html', 'w', encoding='utf-8').write(rb_html)
open('preview_action.html', 'w', encoding='utf-8').write(ae_html)
print(f'Research Brief: {rb_sub}')
print(f'Action Email:   {ae_sub}')
print('Saved: preview_research.html, preview_action.html')
