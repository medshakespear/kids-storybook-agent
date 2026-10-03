"""Prevent page presentation from undoing a lossless local layout recovery."""
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch
from core.activity_presentation import prepare_activity_presentation
from core.creative_generator import validate_design, ask_json, layout_contract
from core.creative_layout import check_page
from core.layout_recovery import layout_recovery_candidates
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import authored_page


class CanonicalLayoutRecoveryTests(unittest.TestCase):
    """Use the real canonical content compiler and WeasyPrint geometry checks."""
    def setUp(self):
        """Use the exact grade band from the reported production failure."""
        self.config = load_grade_config()['3rd-4th']
        self.brief = {'title':'Design a Useful Shelter', 'render_mode':'authored', 'mechanic':'design shelter'}
        self.page = authored_page(mechanic='design shelter')

    def test_prepared_reflow_is_not_reset(self):
        """A validated layout candidate retains its composition during presentation."""
        prepared, brief = prepare_activity_presentation(self.page, self.brief, self.config)
        recovered = next(layout_recovery_candidates(prepared,12,8000))
        original = deepcopy(recovered)
        result, _ = prepare_activity_presentation(recovered, brief, self.config)
        self.assertEqual(result, original)
        self.assertTrue(result['_canonical_presentation'])
        self.assertNotEqual(result['html'], prepared['html'])

    def test_layout_exception_retains_uncompiled_canonical_source(self):
        """A retry uses the prepared page, with no independently compiled answers draft."""
        with patch('core.creative_generator.check_page',side_effect=ValueError('Design overflow: expected 1 pages, got 2')):
            with self.assertRaises(ValueError) as caught:
                validate_design(self.page,12,quality=self.config,expected_title=self.brief['title'],
                                require_coherent=True,brief=self.brief)
        source = caught.exception.layout_source
        self.assertTrue(source['_canonical_presentation'])
        self.assertNotIn('answers', source)
        self.assertNotIn('visuals', source)
        self.assertEqual(source['exercise'], self.page['exercise'])
        self.assertIn('data-content="question_1"', source['html'])

    def test_production_rescue_needs_only_one_provider_response(self):
        """Local reflow survives revalidation and keeps all original student work."""
        api = Mock()
        api.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(self.page)),finish_reason='stop')])
        checked = []
        def reject_initial_then_measure(page, font, **kwargs):
            """Simulate the initial spill and validate every recovery with real PDF geometry."""
            checked.append(page['html'])
            if len(checked) == 1:
                raise ValueError('Design overflow: expected 1 pages, got 2')
            return check_page(page,font,**kwargs)
        def validate(raw):
            """Run the production compiler, including automatic presentation."""
            return validate_design(raw,12,quality=self.config,expected_title=self.brief['title'],
                                   require_coherent=True,brief=self.brief)
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.check_page',side_effect=reject_initial_then_measure), \
             patch('core.creative_generator.time.sleep'):
            result = ask_json(layout_contract(12,12,coherent=True),validate,'Activity design 2',
                              response_schema=design_schema(self.brief,self.config))
        self.assertEqual(api.chat.completions.create.call_count,1)
        self.assertNotEqual(checked[0],checked[1])
        self.assertEqual(result['exercise'], self.page['exercise'])
        self.assertEqual(result['images'], self.page['images'])
        self.assertIn('height:45mm', result['html'])
