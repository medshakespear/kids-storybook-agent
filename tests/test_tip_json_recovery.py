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

    def test_role_tip_heading_binds_without_an_extra_completion_for_both_grades(self):
        """A short Investigator heading retains all student content through the real JSON flow."""
        from core.response_schemas import design_schema
        for band in ('3rd-4th','5th-6th'):
            config=dict(load_grade_config()[band],purposeful_activity_layout=False,
                        context_caption_limit=24,stimulus_limit=4,items_per_page=2)
            page=authored_page();page['exercise'].update(captions=[],stimuli=[])
            original=deepcopy(page)
            page['html']=page['html'].replace('<p data-content="directions">',
                '<h3 style="font-size:16pt;color:#167E80">Tip for <strong>Investigators:</strong></h3><p data-content="directions">')
            api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
            brief={'render_mode':'authored','mechanic':page['exercise']['mechanic']}
            with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                 patch('core.creative_generator.text_client',return_value=(api,'fixture-model')):
                result=ask_json(layout_contract(config['student_font_pt'],config['minimum_text_pt'],coherent=True),
                    lambda raw:validate_design(raw,config['student_font_pt'],quality=config,
                        expected_title='Garden Detectives',require_coherent=True,brief=brief),
                    'Activity design 1',response_schema=design_schema(brief,config))
            self.assertEqual(api.chat.completions.create.call_count,1)
            self.assertEqual(result['exercise']['directions'],original['exercise']['directions'])
            self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
            self.assertEqual(result['images'],original['images'])
            self.assertEqual(result['html'].count('Tip for Investigators:'),1)
            self.assertIn('height:45mm',result['html'])

    def test_short_tip_heading_forms_and_body_boundaries(self):
        """Related role labels are recoverable; tip bodies cannot hide independent tasks."""
        from core.content_binding import tip_heading
        for text in ('Tip:','Challenge Tip:','Tip for Investigators:','Tip for Young Readers:'):
            self.assertTrue(tip_heading(text),text)
        for text in ('Tip for Investigators: Count three flowers.',
                     'Tip for Investigators: The answer is 3.',
                     'Draw three flowers:', 'Tip for '+('A'*61)+':'):
            self.assertFalse(tip_heading(text),text)
        page=authored_page();page['html']+='<p><strong>Tip for Investigators:</strong> Draw three extra flowers.</p>'
        with self.assertRaisesRegex(ValueError,'unbound wording'):
            self.validate(page)

    def test_tip_heading_respects_caption_budget(self):
        """Label recovery cannot bypass the contextual-label ceiling."""
        from core.content_binding import bind_standard_heading
        exercise={'captions':[{'id':f'c{i}','text':f'Context label {i}'} for i in range(6)]}
        markup='<h3>Tip for Investigators:</h3>'
        original=deepcopy(exercise)
        self.assertEqual(bind_standard_heading(markup,exercise),markup)
        self.assertEqual(exercise,original)

    def test_role_tip_label_works_on_exact_pages_without_changing_the_puzzle(self):
        """A heading remains context, not a second set of computed-task instructions."""
        from tests.coherent_fixtures import exact_page, visual_examples
        for band in ('3rd-4th','5th-6th'):
            page=exact_page(visual_examples()[5]);original=deepcopy(page['exercise']['visual'])
            page['html']+='<h3>Tip for Investigators:</h3>'
            config=dict(load_grade_config()[band],purposeful_activity_layout=False,stimulus_limit=4,context_caption_limit=24)
            result=validate_design(page,config['student_font_pt'],quality=config,expected_title='Museum Sorting',require_coherent=True)
            self.assertEqual(result['exercise']['visual'],original)
            self.assertEqual(result['html'].count('Tip for Investigators:'),1)

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
