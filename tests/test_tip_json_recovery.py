"""Recover harmless labels and JSON wrappers without losing exercise content."""
import json
from copy import deepcopy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.creative_generator import parse_design_json, validate_design, ask_json, layout_contract
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class TipJsonRecoveryTests(unittest.TestCase):
    """Exercise the production parser and real page validation without API calls."""

    def validate(self,page):
        """Compile and measure a younger-grade authored worksheet."""
        return validate_design(page,14,quality=load_grade_config()['1st-2nd'],
                               expected_title='Garden Detectives',require_coherent=True)

    def test_tip_label_registers_caption_without_changing_task(self):
        """Retain the standalone label, all artwork and the original student task."""
        page=authored_page()
        page['html']=page['html'].replace('<p data-content="directions">',
                                        '<h3 style="font-size:14pt">Challenge Tip:</h3><p data-content="directions">')
        original=deepcopy(page)
        result=self.validate(page)
        self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
        self.assertEqual(result['images'],original['images'])
        self.assertIn({'id':'tip_label_1','text':'Challenge Tip:'},result['exercise']['captions'])
        self.assertIn('Challenge Tip:',result['html'])
        self.assertEqual(page,original)

    def test_tip_label_does_not_authorize_independent_instructions(self):
        """An unknown tip body still needs a shared canonical field."""
        page=authored_page()
        page['html']+='<p>Challenge Tip:</p><p>Draw three extra flowers.</p>'
        with self.assertRaisesRegex(ValueError,'unbound wording'):
            self.validate(page)

    def test_label_with_inline_instruction_is_not_swallowed(self):
        """Only the exact whole heading can be registered automatically."""
        page=authored_page()
        page['html']+='<p><strong>Challenge Tip:</strong> Draw three flowers.</p>'
        with self.assertRaisesRegex(ValueError,'unbound wording'):
            self.validate(page)

    def test_json_wrappers_and_identical_echoes(self):
        """A closing fence and duplicate identical payload preserve every field."""
        page=authored_page();raw=json.dumps(page)
        for response in [raw,raw+'\n```','```json\n'+raw+'\n```',raw+'\n'+raw]:
            self.assertEqual(parse_design_json(response),page)

    def test_conflicting_or_extra_json_is_rejected(self):
        """Never discard a second design, unknown fields, trailing prose or type changes."""
        for response in ['{"a":1}{"a":2}','{"a":1}{"a":true}',
                         '{"a":1}\nHere is another instruction.',
                         '{"a":1},"images":[]','[]']:
            with self.subTest(response=response),self.assertRaises(ValueError):
                parse_design_json(response)

    def test_malformed_json_is_not_guessed(self):
        """Missing commas and unterminated strings remain explicit serialization defects."""
        for response in ['{"a":1 "b":2}','{"html":"unfinished}']:
            with self.assertRaises(json.JSONDecodeError):
                parse_design_json(response)

    def test_extra_data_retry_focuses_on_serialization_and_validates_result(self):
        """A prose suffix receives a short syntax repair, then full worksheet checks."""
        page=authored_page();raw=json.dumps(page)
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=s),finish_reason='stop')])
            for s in [raw+'\nExplanation follows.',raw]]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(14,13,coherent=True),self.validate,'Activity design 3')
        self.assertEqual(result['exercise'],page['exercise'])
        self.assertEqual(result['images'],page['images'])
        retry=api.chat.completions.create.call_args.kwargs['messages']
        self.assertEqual(len(retry),2)
        self.assertIn('Repair JSON serialization only',retry[-1]['content'])
        self.assertEqual(api.chat.completions.create.call_args.kwargs['temperature'],0.3)


if __name__=='__main__':
    unittest.main()
