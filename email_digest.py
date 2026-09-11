"""Compact, email-safe summaries; detailed evidence stays in the run artifacts."""
from collections import Counter
from datetime import datetime
from html import escape, unescape
import math
import os
from urllib.parse import quote

from email_builder import _action_call, _min_add_irr

MAX_ITEMS = 5
MAX_HOLDINGS = 50


def _text(value, limit=180):
    text = ' '.join(str(value if value is not None else '—').split())
    return escape(text[:limit] + ('…' if len(text) > limit else ''))


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _pct(value):
    number = _number(value)
    return f'{number:.1f}%' if number is not None else '—'


def _irr(holding):
    return _number((holding.get('scenario') or {}).get('expected_irr_pct'))


def _holdings(portfolio):
    return [h for h in portfolio.get('holdings', []) if h.get('status') == 'ACTIVE']


def _verdict(holding):
    return str((holding.get('research') or {}).get('verdict') or holding.get('verdict') or 'UNRATED')


def _heading(title):
    return f'<h2 style="font-size:18px;margin:26px 0 10px;color:#123047">{_text(title)}</h2>'


def _paragraph(text):
    return f'<p style="margin:8px 0;color:#475569">{_text(text, 350)}</p>'


def _item(holding, label, reason):
    ticker = _text(holding.get('ticker', '?'), 12)
    name = _text(holding.get('company_name') or '', 55)
    return (f'<tr><td style="padding:12px 0;border-bottom:1px solid #e2e8f0">'
            f'<strong>{ticker} · {_text(label, 85)}</strong><br>'
            f'<span style="color:#64748b;font-size:13px">{name}</span><br>'
            f'<span>{_text(reason, 200)}</span></td></tr>')


def _table(rows):
    return '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">' + ''.join(rows) + '</table>'


def _more(count):
    return _paragraph(f'{count} more in the detailed run report.') if count > 0 else ''


def _run_link():
    repository = os.getenv('GITHUB_REPOSITORY', 'Vishvesh-Trivedi/autonomous-long-term-screener')
    run_id = os.getenv('GITHUB_RUN_ID', '')
    path = f'/actions/runs/{quote(run_id, safe="")}' if run_id else '/actions'
    url = 'https://github.com/' + quote(repository, safe='/') + path
    return (f'<p><a href="{escape(url, quote=True)}" style="color:#0369a1">'
            'Open run &amp; download detailed reports</a></p>')


def _wrap(title, summary, body, portfolio):
    date = datetime.now().strftime('%d %b %Y')
    updated = _text(portfolio.get('last_updated') or 'not recorded', 32)
    return (f'<!doctype html><html lang="en"><head><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_text(title)}</title></head>'
            '<body style="margin:0;background:#f1f5f9;font:15px/1.6 Arial,sans-serif;color:#1e293b">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:white">'
            '<tr><td style="padding:26px 22px;background:#123047;color:white">'
            '<div style="font-size:12px;letter-spacing:2px">AUTONOMOUS CAPITAL</div>'
            f'<h1 style="font-size:26px;margin:8px 0">{_text(title)}</h1>'
            f'<div>{date} · 15–20 year horizon</div></td></tr>'
            f'<tr><td style="padding:20px 22px"><p style="font-size:17px">{_text(summary, 250)}</p>'
            f'{body}{_run_link()}'
            '<p style="font-size:12px;color:#64748b">Detailed research is in the run artifacts, available after the run finishes. '
            'Model estimates are uncertain, not guarantees. No trades are executed.</p>'
            f'<p style="font-size:12px;color:#64748b">Portfolio data updated: {updated}. '
            'Check the run status to confirm persistence succeeded.</p>'
            '</td></tr></table></td></tr></table></body></html>')


def generate_action_email(decisions, portfolio, decision_review=None):
    new = decisions.get('new_additions', [])
    exits = decisions.get('exits', [])
    migrations = decisions.get('migrations', [])
    holdings = _holdings(portfolio)
    summary = f'{len(new)} new positions · {len(exits)} exits · {len(migrations)} tier changes · {len(holdings)} holdings'
    body = ''
    for title, entries, label, field in (
        ('Exit recommendations', exits, 'EXIT', 'exit_reason'),
        ('New positions', new, 'NEW', 'thesis_summary'),
        ('Tier changes', migrations, 'TIER CHANGE', 'migration_reason'),
    ):
        if entries:
            body += _heading(title)
            rows = []
            for h in entries[:MAX_ITEMS]:
                reason = h.get(field) or h.get('reason') or h.get('thesis_summary') or 'See detailed report.'
                if h.get('swapped_out'):
                    reason = f'Replaces {h["swapped_out"]}. {reason}'
                if h.get('review_note'):
                    reason = f'Review: {h["review_note"]}. {reason}'
                rows.append(_item(h, label, reason))
            body += _table(rows) + _more(len(entries) - MAX_ITEMS)
    if not new and not exits and not migrations:
        body += _heading('No portfolio changes')
        body += _paragraph('No new position was approved this run. Existing positions remain unchanged; candidates are not added just to create activity.')
    if decision_review:
        body += _paragraph(decision_review.get('summary') or decision_review.get('overall_assessment') or 'Automated decision review completed; review warnings in the detailed report.')
    excluded = {h.get('ticker') for h in new + exits + migrations}
    opportunities = []
    for h in holdings:
        irr = _irr(h)
        if h.get('ticker') in excluded or irr is None or irr < _min_add_irr():
            continue
        if _verdict(h) not in ('CORE_HOLD', 'ACCUMULATE', 'MOONSHOT'):
            continue
        label, _, _, _, reason, priority = _action_call(h)
        if priority >= 2 and label.startswith('ADD'):
            opportunities.append((irr, h, unescape(label), reason))
    if opportunities:
        body += _heading('Existing positions to consider adding to')
        opportunities.sort(key=lambda item: item[0], reverse=True)
        body += _table([_item(h, label, f'Model IRR {_pct(irr)}/yr. {reason}')
                        for irr, h, label, reason in opportunities[:MAX_ITEMS]])
        body += _more(len(opportunities) - MAX_ITEMS)
    avoided = decisions.get('avoided', [])
    pending = [c for c in decisions.get('contests', []) if c.get('status') == 'PENDING']
    incomplete = decisions.get('screened_candidates', [])
    if avoided or pending or incomplete:
        body += _heading('Why candidates were not added')
        counts = Counter()
        for candidate in avoided:
            reason = str(candidate.get('reason') or '').lower()
            if 'confirmation' in reason:
                group = 'Awaiting swap confirmation'
            elif 'sector cap' in reason or 'factor cap' in reason:
                group = 'Concentration limit'
            elif 'survival' in reason:
                group = 'Sector survival risk'
            else:
                group = 'Research / eligibility decision'
            counts[group] += 1
        for label, count in counts.most_common():
            body += _paragraph(f'{label}: {count}')
        if incomplete:
            body += _paragraph(f'Research unavailable or incomplete: {len(incomplete)}. These are not approved buys.')
        if pending:
            body += _table([_item({'ticker': c.get('challenger')}, 'AWAITING CONFIRMATION',
                        f'Challenging {c.get("incumbent")}: {c.get("runs", 0)}/{c.get("needed", 2)} qualifying runs.')
                        for c in pending[:MAX_ITEMS]])
    subject = f'Action Brief | {datetime.now():%d %b %Y} | {len(new)} new, {len(exits)} exits'
    return _wrap('Action Brief', summary, body, portfolio), subject


def generate_full_report(decisions, portfolio, researched, ipo_watchlist=None,
                         fif_threshold=None, megatrend_review=None, sector_survival=None,
                         decision_review=None):
    holdings = sorted(_holdings(portfolio), key=lambda h: (h.get('tier', ''), h.get('ticker', '')))
    changed = [h for h in holdings if h.get('changed_this_month')]
    body = _heading('Portfolio snapshot')
    rows = []
    for h in holdings[:MAX_HOLDINGS]:
        metrics = f'{h.get("tier", "—")} · Model IRR {_pct(_irr(h))}/yr · Weight {_pct(h.get("position_size_pct"))}'
        rows.append(_item(h, _verdict(h).replace('_', ' '), metrics))
    body += _table(rows) if rows else _paragraph('No active holdings.')
    body += _more(len(holdings) - MAX_HOLDINGS)
    if changed:
        body += _heading('What changed')
        body += _table([_item(h, h.get('change_reason') or 'Updated coverage',
                            (h.get('research') or {}).get('thesis_summary') or h.get('thesis_summary') or 'See detailed report.')
                        for h in changed[:MAX_ITEMS]])
        body += _more(len(changed) - MAX_ITEMS)
    else:
        body += _paragraph('No material thesis, rating or tier changes recorded.')
    warnings = [h for h in holdings if h.get('review_flag') or _verdict(h) in ('AVOID', 'TRIM', 'EXIT')]
    if warnings:
        body += _heading('Needs review')
        body += _table([_item(h, 'REVIEW', h.get('review_note') or h.get('primary_risk') or h.get('thesis_breaks_if'))
                        for h in warnings[:MAX_ITEMS]])
    body += _heading('Track Record & detailed evidence')
    body += _paragraph('Historical returns, benchmarks, full theses, scenarios, news and disclosures are in the detailed report—not repeated in this email.')
    summary = f'{len(holdings)} active holdings · {len(changed)} changed · Full research available separately'
    return _wrap('Research Summary', summary, body, portfolio), f'Research Summary | {datetime.now():%d %b %Y}'
