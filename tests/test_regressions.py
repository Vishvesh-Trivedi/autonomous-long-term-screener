"""Offline regressions for additions, state persistence and compact emails."""
import ast
from copy import deepcopy
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from email_digest import generate_action_email, generate_full_report


def holding(ticker='OLD', **updates):
    result = {'ticker': ticker, 'company_name': ticker, 'tier': 'T1',
              'status': 'ACTIVE', 'sector': 'Technology', 'date_added': '2020-01-01',
              'verdict': 'ACCUMULATE', 'position_size_pct': 4,
              'scenario': {'expected_irr_pct': 1}, 'changed_this_month': False}
    result.update(updates)
    return result


class DigestTests(unittest.TestCase):
    def test_no_changes_is_explicit(self):
        html, subject = generate_action_email({}, {'holdings': [holding()]})
        self.assertIn('No portfolio changes', html)
        self.assertIn('0 new', subject)
        self.assertNotIn('Existing positions to consider', html)

    def test_add_gate_requires_finite_sufficient_irr(self):
        for value in [None, float('nan'), float('inf'), 'bad', 0, 7]:
            with self.subTest(value=value), patch('email_digest._min_add_irr', return_value=8):
                h = holding(above_200ma=False, scenario={'expected_irr_pct': value})
                html, _ = generate_action_email({}, {'holdings': [h]})
                self.assertNotIn('Existing positions to consider', html)
        h = holding(above_200ma=False, scenario={'expected_irr_pct': 12})
        with patch('email_digest._min_add_irr', return_value=8):
            html, _ = generate_action_email({}, {'holdings': [h]})
        self.assertIn('Existing positions to consider', html)

    def test_new_position_not_repeated_as_accumulation(self):
        h = holding(above_200ma=False, scenario={'expected_irr_pct': 20})
        html, _ = generate_action_email({'new_additions': [h]}, {'holdings': [h]})
        self.assertIn('New positions', html)
        self.assertNotIn('Existing positions to consider', html)

    def test_html_escaped_and_nonfinite_hidden(self):
        h = holding(company_name='<script>alert(1)</script>', position_size_pct=float('nan'),
                    scenario={'expected_irr_pct': float('inf')})
        html, _ = generate_full_report({}, {'holdings': [h]}, {})
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('nan%', html)
        self.assertNotIn('inf%', html)

    def test_size_bound_even_with_large_research(self):
        portfolio = {'holdings': [holding(f'T{i}', company_name='Long name ' * 100,
                            thesis_summary='Long thesis ' * 1000, changed_this_month=True,
                            change_reason='Long change ' * 100) for i in range(100)]}
        before = deepcopy(portfolio)
        html, _ = generate_full_report({}, portfolio, {})
        self.assertLess(len(html.encode('utf-8')), 80000)
        self.assertIn('50 more in the detailed run report', html)
        self.assertEqual(portfolio, before)

    def test_rejection_reasons_and_pending_are_visible(self):
        decisions = {'avoided': [{'reason': 'Sector cap: at max'}],
                     'screened_candidates': [{'ticker': 'BAD'}],
                     'contests': [{'status': 'PENDING', 'challenger': 'NEW',
                                   'incumbent': 'OLD', 'runs': 1, 'needed': 2}]}
        html, _ = generate_action_email(decisions, {'holdings': []})
        self.assertIn('Concentration limit: 1', html)
        self.assertIn('Research unavailable or incomplete: 1', html)
        self.assertIn('1/2 qualifying runs', html)

    def test_actual_portfolio_email_budget(self):
        portfolio = json.loads((ROOT / 'data/portfolio.json').read_text(encoding='utf-8'))
        for render in (lambda: generate_action_email({}, portfolio),
                       lambda: generate_full_report({}, portfolio, {})):
            html, _ = render()
            self.assertLess(len(html.encode('utf-8')), 80000)
            self.assertIn('download detailed reports', html)


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'swap.json'
        self.research = {}
        self.config = json.loads((ROOT / 'universe_config.json').read_text(encoding='utf-8'))
        self.config['sector_replacement']['enabled'] = False
        self.config['sector_replacement']['override_enabled'] = False
        self.ns = self.namespace()
        self.candidate = {'tier': 'T1', 'info': {'sector': 'Technology', 'longName': 'NEW'},
                          'research': {'verdict': 'ACCUMULATE', 'moat_durability_years': 20,
                                       'decade_probability': 95, 'roiic_pct': 30,
                                       'growth_runway_years': 15, 'interest_coverage': 10},
                          'scenario': {'expected_irr_pct': 20}}

    def namespace(self):
        def nested(default, *keys):
            value = self.config
            for key in keys:
                if not isinstance(value, dict) or key not in value:
                    return default
                value = value[key]
            return value
        def save_swap(value):
            self.path.write_text(json.dumps(value), encoding='utf-8')
        ns = {'datetime': datetime, 'log': logging.getLogger('test'),
              '_cn': nested, '_cu': lambda key, default=None: nested(default, 'stock_screening', 'universal', key),
              'load_thesis': lambda ticker: self.research.get(ticker, {}),
              'load_scenario': lambda ticker: {'expected_irr_pct': 1},
              '_concentration_flag': lambda h: '', '_rerun_flag': lambda h: '',
              'load_swap_state': lambda: json.loads(self.path.read_text()) if self.path.exists() else {},
              'save_swap_state': save_swap, 'load_json': lambda p: {}, 'save_json': Mock(),
              'REJECTION_LOG_FILE': Path(self.temp.name) / 'rejections.json',
              'check_kiwisaver_availability': lambda *a: {'available': False, 'route': 'manual'},
              'compute_earnings_quality': lambda *a: 'OK',
              'compute_debt_ratios': lambda *a: {'de_ratio': 0, 'coverage': 10},
              'compute_all_metrics': lambda *a: {}, 'compute_trajectory': lambda *a: {},
              'cross_check_yahoo': lambda *a: {},
              'compute_earnings_quality_trend': lambda *a: {},
              '_compute_data_completeness': lambda *a: {},
              'compute_roic': lambda *a: .2, 'compute_dilution_rate': lambda *a: 0,
              'get_insider_ownership': lambda *a: .1, 'yf': Mock()}
        ns['yf'].download.side_effect = AssertionError('No network in regression tests')
        source = ast.parse((ROOT / 'screener.py').read_text(encoding='utf-8'))
        names = {'_fnum', '_expected_irr', '_conviction_score', '_days_since', 'construct_portfolio'}
        module = ast.Module(body=[n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
        exec(compile(module, 'screener.py', 'exec'), ns)
        return ns

    def construct(self, holdings=None, candidate=None, sector_map=None):
        return self.ns['construct_portfolio']({'NEW': candidate or self.candidate},
                    {'holdings': holdings or []}, self.config, sector_map)

    def test_qualified_new_stock_is_added(self):
        result = self.construct()
        self.assertEqual([h['ticker'] for h in result['new_additions']], ['NEW'])
        self.assertEqual(result['new_additions'][0]['status'], 'ACTIVE')
        self.ns['save_json'].assert_called_once()

    def test_sector_cap_is_still_enforced(self):
        result = self.construct([holding(f'OLD{i}') for i in range(3)])
        self.assertFalse(result['new_additions'])
        self.assertIn('Sector cap', result['avoided'][0]['reason'])

    def test_exit_frees_slot_in_same_run(self):
        self.research['OLD0'] = {'verdict': 'AVOID'}
        result = self.construct([holding(f'OLD{i}') for i in range(3)])
        self.assertEqual([h['ticker'] for h in result['exits']], ['OLD0'])
        self.assertEqual([h['ticker'] for h in result['new_additions']], ['NEW'])
        self.assertEqual(result['sector_slots']['Technology']['count'], 3)

    def test_low_survival_and_avoid_still_block(self):
        result = self.construct(sector_map={'sectors': {'Technology': {'survives_20yr': 'LOW'}}})
        self.assertFalse(result['new_additions'])
        candidate = deepcopy(self.candidate)
        candidate['research']['verdict'] = 'AVOID'
        self.assertFalse(self.construct(candidate=candidate)['new_additions'])

    def test_swap_confirmation_survives_new_process_state(self):
        self.config['sector_replacement']['enabled'] = True
        holdings = [holding(f'OLD{i}') for i in range(3)]
        first = self.construct(holdings)
        self.assertFalse(first['new_additions'])
        self.assertEqual(first['contests'][0]['status'], 'PENDING')
        self.assertTrue(self.path.exists())
        self.ns = self.namespace()
        second = self.construct(holdings)
        self.assertEqual(second['new_additions'][0]['entry_kind'], 'SWAP')
        self.assertEqual(len(second['exits']), 1)
        self.assertEqual(second['sector_slots']['Technology']['count'], 3)


@unittest.skipUnless(os.name == 'posix', 'GitHub Linux runner integration tests')
class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.remote = root / 'remote.git'
        self.work = root / 'work'
        self.work.mkdir()
        self.git('init', '--bare', str(self.remote))
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.work / 'data').mkdir()
        (self.work / 'data/portfolio.json').write_text('{}')
        (self.work / 'universe_config.json').write_text('{}')
        (self.work / 'preview_action.html').write_text('old preview')
        (self.work / '.gitignore').write_text('data/checkpoints/\n')
        self.git('add', '.')
        self.git('commit', '-m', 'fixture')
        self.git('remote', 'add', 'origin', str(self.remote))
        self.git('push', '-u', 'origin', 'main')

    def git(self, *args, check=True):
        return subprocess.run(['git', *args], cwd=self.work, check=check, capture_output=True, text=True)

    def persist(self):
        env = {**os.environ, 'GITHUB_REF_NAME': 'main'}
        return subprocess.run(['bash', str(ROOT / 'scripts/persist_state.sh'), 'test state'],
                              cwd=self.work, env=env, capture_output=True, text=True)

    def test_dirty_config_and_preview_do_not_prevent_push(self):
        (self.work / 'data/portfolio.json').write_text('{"new": "NEW"}')
        (self.work / 'data/swap_state.json').write_text('{"pending": {"NEW": 1}}')
        (self.work / 'universe_config.json').write_text('{"updated": true}')
        (self.work / 'preview_action.html').write_text('new uncommitted preview')
        (self.work / 'data/checkpoints').mkdir()
        (self.work / 'data/checkpoints/step.json').write_text('{}')
        broken = self.git('pull', '--rebase', 'origin', 'main', check=False)
        self.assertNotEqual(broken.returncode, 0)
        self.assertIn('unstaged changes', broken.stderr)
        result = self.persist()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout, self.git('rev-parse', 'origin/main').stdout)
        self.assertIn('NEW', self.git('show', 'origin/main:data/portfolio.json').stdout)
        self.assertIn('updated', self.git('show', 'origin/main:universe_config.json').stdout)
        self.assertIn('pending', self.git('show', 'origin/main:data/swap_state.json').stdout)
        self.assertEqual(self.git('show', 'origin/main:preview_action.html').stdout, 'old preview')
        self.assertEqual((self.work / 'preview_action.html').read_text(), 'new uncommitted preview')
        self.assertNotIn('checkpoints', self.git('ls-tree', '-r', '--name-only', 'HEAD').stdout)

    def test_push_failure_is_not_success(self):
        hook = self.remote / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        before = self.git('rev-parse', 'origin/main').stdout
        (self.work / 'data/portfolio.json').write_text('{"new": true}')
        result = self.persist()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('NOT persisted', result.stdout)
        self.assertEqual(before, self.git('rev-parse', 'origin/main').stdout)

    def test_no_changes_is_clean_noop(self):
        before = self.git('rev-parse', 'HEAD').stdout
        result = self.persist()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.git('rev-parse', 'HEAD').stdout)


if __name__ == '__main__':
    unittest.main()
