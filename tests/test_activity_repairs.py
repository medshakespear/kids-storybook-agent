"""Regressions for the live operand and passage failures reported in Railway."""
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.activity_generator import generate_activity_pack, validate_pack, merge_repairs
from core.pipeline import load_grade_config
from tests.activity_fixtures import sample_pack


def response(data):
    """Build an offline chat response."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data)))])


class RepairTests(unittest.TestCase):
    """Ensure valid pages survive content and provider failures."""

    def setUp(self):
        """Use actual third/fourth-grade limits."""
        self.config = load_grade_config()
        self.band = '3rd-4th'
        self.pack = sample_pack(self.band, self.config[self.band])

    def test_integer_encoding_and_bounds(self):
        """Normalize integer encodings but never silently alter math values."""
        item = self.pack['pages'][6]['items'][0]
        item.update(a='12', b=3.0)
        pack = validate_pack(self.pack, 'test', self.band, self.config[self.band])
        self.assertEqual(pack['pages'][6]['answers'][0], '15')
        self.assertIs(type(pack['pages'][6]['items'][0]['a']), int)
        for bad in (101, 1.5, True, 'twelve'):
            item['a'] = bad
            with self.assertRaisesRegex(ValueError, 'Page 7, item 1: a must'):
                validate_pack(self.pack, 'test', self.band, self.config[self.band])

    def test_repairs_both_failures_without_regenerating_valid_pages(self):
        """Repair oversized math and a short passage in one bounded follow-up."""
        broken = deepcopy(self.pack)
        broken['pages'][6]['items'][0]['a'] = 150
        broken['pages'][3]['passage'] = 'A tiny passage.'
        api = Mock()
        api.chat.completions.create.side_effect = [response(broken), response({'pages': [self.pack['pages'][3], self.pack['pages'][6]]})]
        with patch('core.activity_generator.text_provider_names', return_value=['gemini']), patch('core.activity_generator.text_client', return_value=(api, 'test')), patch('core.activity_generator.time.sleep'), self.assertLogs('core.activity_generator', level='WARNING') as logs:
            result = generate_activity_pack('test', self.band, self.config, max_retries=2)
        self.assertEqual(result['pages'][0], self.pack['pages'][0])
        self.assertEqual(result['pages'][6]['answers'][0], self.pack['pages'][6]['answers'][0])
        second = api.chat.completions.create.call_args_list[1].kwargs
        self.assertIn('REPAIR MODE', second['messages'][1]['content'])
        self.assertEqual(second['max_completion_tokens'], 4000)
        self.assertIn('repair pages 4, 7', '\n'.join(logs.output))

    def test_fallback_keeps_draft_and_does_not_retry_quota(self):
        """Quota failure immediately switches provider while keeping the repair request."""
        broken = deepcopy(self.pack)
        broken['pages'][3]['passage'] = 'Too short.'
        quota = RuntimeError('private response body')
        quota.status_code = 429
        primary, fallback = Mock(), Mock()
        primary.chat.completions.create.side_effect = [response(broken), quota]
        fallback.chat.completions.create.return_value = response({'pages': [self.pack['pages'][3]]})
        with patch('core.activity_generator.text_provider_names', return_value=['gemini', 'groq']), patch('core.activity_generator.text_client', side_effect=[(primary, 'test'), (fallback, 'test')]), patch('core.activity_generator.time.sleep'):
            result = generate_activity_pack('test', self.band, self.config)
        self.assertEqual(primary.chat.completions.create.call_count, 2)
        self.assertIn('REPAIR MODE', fallback.chat.completions.create.call_args.kwargs['messages'][1]['content'])
        self.assertEqual(result['pages'][3]['passage'], self.pack['pages'][3]['passage'])

    def test_repair_cannot_replace_unrequested_pages(self):
        """Reject unsolicited replacement pages and preserve the source draft."""
        before = deepcopy(self.pack)
        with self.assertRaises(ValueError):
            merge_repairs(self.pack, {'pages': [self.pack['pages'][0]]}, {4: 'short passage'})
        self.assertEqual(self.pack, before)
