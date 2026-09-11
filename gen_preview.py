"""Render production emails without network calls or email delivery."""
import json
from pathlib import Path

from email_digest import generate_action_email, generate_full_report
from email_report import generate_full_report as generate_detailed_report

ROOT = Path(__file__).resolve().parent


def main():
    portfolio = json.loads((ROOT / 'data/portfolio.json').read_text(encoding='utf-8'))
    for holding in portfolio.get('holdings', []):
        if not holding.get('scenario'):
            path = ROOT / 'data/scenarios' / f'{holding.get("ticker", "")}.json'
            if path.exists():
                holding['scenario'] = json.loads(path.read_text(encoding='utf-8'))
    decisions = {'new_additions': [], 'exits': [], 'migrations': [], 'screened_candidates': []}
    outputs = {
        'preview_action.html': generate_action_email(decisions, portfolio)[0],
        'preview_research.html': generate_full_report(decisions, portfolio, {})[0],
        'research_full.html': generate_detailed_report(decisions, portfolio, {})[0],
    }
    output_dir = ROOT / 'reports'
    output_dir.mkdir(exist_ok=True)
    for name, html in outputs.items():
        size = len(html.encode('utf-8'))
        if name.startswith('preview_') and size >= 80000:
            raise ValueError(f'{name} exceeds the 80 KB email budget: {size}')
        (output_dir / name).write_text(html, encoding='utf-8')
        print(f'{name}: {size:,} bytes')


if __name__ == '__main__':
    main()
