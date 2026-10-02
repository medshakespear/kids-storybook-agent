"""Remove redundant blank metadata without deleting questions, pictures or filled text."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design,merge_layout_repair
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page,exact_page,visual_examples


class DuplicateMetadataSlotTests(unittest.TestCase):
    """Exercise production compilation for the duplicate name/date daily failure."""

    def validate(self,page):
        """Measure a complete Pre-K page with real canonical text and puzzle checks."""
        return validate_design(page,14,quality=load_grade_config()['Pre-K-K'],
                               expected_title='Garden Detectives',require_coherent=True)

    def test_empty_and_prefilled_metadata_duplicates_need_no_retry(self):
        """Print just one blank Name and Date while retaining every real task."""
        page=authored_page()
        page['html']+='<p data-content="name"></p><p data-content="date"></p>'
        page['html']+='<p data-content="name"><strong>Name:</strong> __________</p>'
        page['html']+='<p data-content="date">Date: _________________</p>'
        original=deepcopy(page)
        api=Mock()
        api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')):
            result=ask_json(layout_contract(14,14,coherent=True),self.validate,'Activity design 1')
        self.assertEqual(result['html'].count('Name: ____________________'),1)
        self.assertEqual(result['html'].count('Date: ____________________'),1)
        self.assertEqual(api.chat.completions.create.call_count,1)
        self.assertEqual(result['exercise'],original['exercise'])
        self.assertEqual(result['images'],original['images'])
        self.assertEqual(page,original)

    def test_raw_formatted_and_explicit_metadata_are_deduplicated_together(self):
        """Mixed raw and canonical model drafts share the same identification slots."""
        page=authored_page()
        page['html']+='<p>Name: _____</p><p><strong>Date:</strong> _____</p>'
        page['html']+='<p data-content="name"></p><p data-content="date"></p>'
        result=self.validate(page)
        self.assertEqual(result['html'].count('Name: ____________________'),1)
        self.assertEqual(result['html'].count('Date: ____________________'),1)

    def test_filled_or_instructional_duplicate_is_not_discarded(self):
        """Only blank metadata copies qualify for local removal."""
        for body in ['Name: Maya','Name: ____ Draw three flowers.',
                     '<img data-asset="scene" style="width:80mm;height:60mm"/>']:
            page=authored_page()
            page['html']+=f'<p data-content="name"></p><p data-content="name">{body}</p>'
            with self.subTest(body=body),self.assertRaises(ValueError):
                self.validate(page)

    def test_duplicate_question_slots_stay_invalid(self):
        """Never apply metadata de-duplication to instructional content or work areas."""
        page=authored_page();page['html']+='<div data-content="question_1"></div>'
        with self.assertRaisesRegex(ValueError,'question_1; already printed'):
            self.validate(page)

    def test_exact_task_directions_cannot_change_to_count_and_match(self):
        """Eliminating duplicate metadata must not authorize unverified puzzle instructions."""
        page=exact_page(visual_examples()[3])
        page['html']+='<p data-content="name"></p><p data-content="date"></p><p data-content="date"></p>'
        page['html']+='<p>Count the smiling corn cobs and match them to the correct number dots.</p>'
        with self.assertRaisesRegex(ValueError,'unbound wording'):
            self.validate(page)

    def test_layout_retry_cannot_promote_new_instructions_to_captions(self):
        """Retain the existing safeguard behind the third reported failure."""
        page=authored_page()
        correction=deepcopy(page)
        correction['exercise']['captions']=[{'id':'new_task','text':'Count corn cobs and match number dots.'}]
        with self.assertRaisesRegex(ValueError,'complete wording already printed'):
            merge_layout_repair(page,correction)


if __name__=='__main__':
    unittest.main()
