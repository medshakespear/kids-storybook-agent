"""Restore declared factual context without inventing tasks or diagram associations."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from core.missing_exact_context import recover_missing_exact_context
from core.creative_generator import ask_json, validate_design, layout_contract, density_guidance
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests.coherent_fixtures import exact_page, visual_examples


class MissingExactContextTests(unittest.TestCase):
    """Exercise actual binding, label readability and print preflight in both bands."""

    def page(self):
        """Return a valid puzzle with four declared but unprinted factual captions."""
        page=exact_page(visual_examples()[5])
        page['html']=page['html'].replace('width:175mm;height:150mm','width:90mm;height:50mm')
        page['exercise']['captions']=[{'id':f'c{i}','text':text} for i,text in enumerate((
            'These fictional exhibit cards have different shapes.',
            'The display uses colors to make the groups clear.',
            'Visitors can compare the objects in each group.',
            'Each group includes objects with shared features.'),1)]
        page['exercise']['questions']=[{'id':'2','prompt':'Describe one useful feature of the display.',
            'answer':'Accept a feature that makes the shared features clear.','space_mm':25}]
        page['html']+='<div data-content="question_2"></div>'
        return page

    def test_reported_missing_four_captions_and_tiny_labels_recover_in_one_call(self):
        """Known context and the exact puzzle survive a measured local recovery."""
        for band in ('3rd-4th','5th-6th'):
            config=dict(load_grade_config()[band],purposeful_activity_layout=False,stimulus_limit=4,
                        context_caption_limit=24,items_per_page=2)
            raw=self.page();original=deepcopy(raw)
            api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')])
            brief={'render_mode':'exact','mechanic':'sort'}
            prompt=layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True)+'\n'+density_guidance(config)
            with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                 patch('core.creative_generator.text_client',return_value=(api,'fixture-model')):
                result=ask_json(prompt,lambda page:validate_design(page,config['student_font_pt'],quality=config,
                    expected_title='Museum Sorting',require_coherent=True,brief=brief),'Activity design 3',
                    response_schema=design_schema(brief,config))
            self.assertEqual(api.chat.completions.create.call_count,1)
            self.assertEqual(result['exercise'],original['exercise'])
            for caption in original['exercise']['captions']:
                self.assertEqual(result['html'].count(caption['text']),1)
            self.assertIn('height:25mm',result['html'])
            self.assertEqual(raw,original)

    def test_missing_task_or_diagram_identifier_cannot_be_guessed(self):
        """Standalone factual context is distinct from actions and labels attached to a diagram."""
        for text in ('Node A','Sort these cards into a new group.','Why is this group different?','Unbound label'):
            page=self.page();page['exercise']['captions']=[{'id':'c1','text':text}]
            self.assertEqual(recover_missing_exact_context(page)['html'],page['html'])

    def test_already_printed_canonical_context_is_not_duplicated(self):
        """Raw exact copies and named slots remain in their existing positions."""
        page=self.page()
        page['html']+='<p>'+page['exercise']['captions'][0]['text']+'</p><p data-content="caption_c2"></p>'
        result=recover_missing_exact_context(page)
        self.assertNotIn('data-content="caption_c1"',result['html'])
        self.assertEqual(result['html'].count('data-content="caption_c2"'),1)
        self.assertEqual(result['html'].count('data-content="caption_c3"'),1)

    def test_label_error_explains_required_dimensions(self):
        """A model repair gets physical scale information rather than the same vague error."""
        page=self.page();page=recover_missing_exact_context(page)
        config=dict(load_grade_config()['3rd-4th'],purposeful_activity_layout=False,stimulus_limit=4,context_caption_limit=24)
        with self.assertRaisesRegex(ValueError,'Current smallest label.*width:.*height:'):
            validate_design(page,config['student_font_pt'],quality=config,expected_title='Museum Sorting',require_coherent=True)
