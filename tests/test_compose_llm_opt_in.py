"""Configuration regressions: forwarding is allowed, live LLM use stays opt-in."""
from pathlib import Path
import os
import re
import unittest
from unittest import mock

import server as app

ROOT = Path(__file__).resolve().parents[1]


class ComposeLlmOptInTest(unittest.TestCase):
    def test_compose_forwards_enabled_with_safe_zero_default(self):
        source = (ROOT / 'compose.yaml').read_text(encoding='utf-8')
        matches = re.findall(r'^\s+NARYADAI_LLM_ENABLED:\s*(.+)$', source, re.MULTILINE)
        self.assertEqual(matches, ['${NARYADAI_LLM_ENABLED:-0}'])
        # Existing provider configuration forwarding is retained verbatim.
        for key in ('NARYADAI_LLM_API_URL', 'NARYADAI_LLM_API_KEY', 'NARYADAI_LLM_MODEL'):
            self.assertIn(f'{key}: ${{{key}:-}}', source)

    def test_explicit_zero_stays_rules_only_even_with_synthetic_configuration(self):
        fake = {
            'NARYADAI_LLM_ENABLED': '0',
            'NARYADAI_LLM_API_KEY': 'synthetic-test-not-a-real-key',
            'NARYADAI_LLM_MODEL': 'synthetic-test-model',
            'NARYADAI_LLM_API_URL': 'https://example.invalid/chat/completions',
        }
        with mock.patch.dict(os.environ, fake, clear=True), \
             mock.patch.object(app.urllib.request, 'urlopen', side_effect=AssertionError('No external request allowed')) as network:
            result = app.llm_review('Синтетическая проверка: внешний запрос запрещён.')
        self.assertEqual(result['mode'], 'rules-only: disabled')
        network.assert_not_called()

    def test_missing_enabled_stays_rules_only_and_readme_explains_manual_opt_in(self):
        fake = {
            'NARYADAI_LLM_API_KEY': 'synthetic-test-not-a-real-key',
            'NARYADAI_LLM_MODEL': 'synthetic-test-model',
        }
        with mock.patch.dict(os.environ, fake, clear=True), \
             mock.patch.object(app.urllib.request, 'urlopen', side_effect=AssertionError('No external request allowed')) as network:
            result = app.llm_review('Синтетическая проверка без флага включения.')
        self.assertEqual(result['mode'], 'rules-only: disabled')
        network.assert_not_called()
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('NARYADAI_LLM_ENABLED=1', readme)
        self.assertIn('NARYADAI_LLM_ENABLED=0', readme)
        self.assertIn('rules-only', readme)
        self.assertIn('Не присылайте его в чат', readme)

    def test_optional_adapters_and_summary_have_disabled_or_empty_defaults(self):
        source = (ROOT / 'compose.yaml').read_text(encoding='utf-8')
        expected = {
            'NARYADAI_LLM_REPORT_SUMMARY': '0',
            'NARYADAI_TELEGRAM_ENABLED': '0',
            'NARYADAI_TELEGRAM_BOT_TOKEN': '',
            'NARYADAI_TELEGRAM_WEBHOOK_SECRET': '',
        }
        for key, default in expected.items():
            matches = re.findall(r'^\s+' + key + r':\s*(.+)$', source, re.MULTILINE)
            self.assertEqual(matches, [f'${{{key}:-{default}}}'], key)
        template = dict(line.split('=', 1) for line in
                        (ROOT / '.env.example').read_text(encoding='utf-8').splitlines()
                        if line and not line.startswith('#'))
        for key in ('NARYADAI_LLM_ENABLED', 'NARYADAI_LLM_REPORT_SUMMARY', 'NARYADAI_TELEGRAM_ENABLED'):
            self.assertEqual(template[key], '0', key)
        for key in ('NARYADAI_LLM_API_KEY', 'NARYADAI_TELEGRAM_BOT_TOKEN', 'NARYADAI_TELEGRAM_WEBHOOK_SECRET'):
            self.assertEqual(template[key], '', key)

    def test_telegram_requires_explicit_opt_in_and_both_local_secrets(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(app.telegram_delivery_configured())
        fake = {'NARYADAI_TELEGRAM_ENABLED': '0',
                'NARYADAI_TELEGRAM_BOT_TOKEN': 'synthetic-test-not-real',
                'NARYADAI_TELEGRAM_WEBHOOK_SECRET': 'synthetic-test-not-real'}
        with mock.patch.dict(os.environ, fake, clear=True):
            self.assertFalse(app.telegram_delivery_configured())
        fake['NARYADAI_TELEGRAM_ENABLED'] = '1'
        for missing in ('NARYADAI_TELEGRAM_BOT_TOKEN', 'NARYADAI_TELEGRAM_WEBHOOK_SECRET'):
            with mock.patch.dict(os.environ, {**fake, missing: ''}, clear=True):
                self.assertFalse(app.telegram_delivery_configured())
        # This is only a pure configuration predicate; no delivery is started.
        with mock.patch.dict(os.environ, fake, clear=True):
            self.assertTrue(app.telegram_delivery_configured())


if __name__ == '__main__':
    unittest.main()
