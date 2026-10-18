"""Regress standalone matching letters and coherent repair of below-grade math."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.content_binding import bind_standard_heading
from core.creative_generator import ask_json,layout_contract,validate_design
from core.response_schemas import design_schema
from tests import test_complete_student_tasks as fixtures
from tests.test_binding_alias_regressions import matching_page
from tests.test_student_workbook import evidence_page,workbook_config


class MatchingMarkersGradeRepairTests(unittest.TestCase):
    """Use real content/grade/layout checks and mock only provider replies."""

    def test_letter_markers_and_qualitative_followup_bind_in_both_grades(self):
        """Write-the-letter and explain-one-choice are not quantitative operations."""
        for band in ('3rd-4th','5th-6th'):
            page=matching_page()
            page['exercise']['questions'][0]['prompt']='Write the correct letter (A-D) beside numbered terms (1-4). Explain one choice.'
            page['exercise']['questions'][0]['calculation']={'expression':'1-4','answer':'-3'}
            page['html']=page['html'].replace('<p data-content="stimulus_source_text"',
                'A.<p data-content="stimulus_source_text"')
            before=deepcopy(page)
            result=fixtures.CompleteStudentTaskTests().ask(page,band)
            self.assertNotIn('calculation',result['exercise']['questions'][0])
            self.assertTrue(any(c['text']=='A.' for c in result['exercise']['captions']))
            self.assertEqual(result['exercise']['questions'][0]['answer'],before['exercise']['questions'][0]['answer'])
            self.assertEqual(page,before)

    def test_marker_binding_never_turns_unregistered_tasks_into_captions(self):
        """Only whole short markers qualify, not a sentence beginning with A."""
        for text in ('A. Calculate 8-3.','A. Write a report.','A. The answer is five.'):
            exercise={'render_mode':'authored','mechanic':'matching','captions':[]}
            markup='<p>'+text+'</p>'
            self.assertEqual(bind_standard_heading(markup,exercise),markup)
            self.assertEqual(exercise['captions'],[])
        exercise={'render_mode':'authored','mechanic':'reading','captions':[]}
        self.assertEqual(bind_standard_heading('<p>A.</p>',exercise),'<p>A.</p>')

    def test_below_grade_repair_can_update_prompt_calculation_and_key_together(self):
        """The old calculation-only repair instruction must not pin a weak problem forever."""
        for band,expression,value in (('3rd-4th','245-128','117'),('5th-6th','2450-1284','1166')):
            raw=evidence_page();raw['exercise']['questions'][0].update(prompt='Calculate 8-3.',answer='5',
                calculation={'expression':'8-3','answer':'5'})
            correction={'exercise':{'questions':[{'id':'1','prompt':'Calculate '+expression+'.',
                'answer':value,'calculation':{'expression':expression,'answer':value},'space_mm':0}]}}
            api=Mock();api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(reply)),finish_reason='stop')]) for reply in (raw,correction)]
            config=workbook_config(band,simple=True)
            with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                 patch('core.creative_generator.text_client',return_value=(api,'fixture')), \
                 patch('core.creative_generator.time.sleep'):
                result=ask_json(layout_contract(12,12,coherent=True),
                    lambda draft:validate_design(draft,12,quality=config,expected_title='Evidence Practice',require_coherent=True),
                    'Activity design 3',response_schema=design_schema({'render_mode':'authored','mechanic':'compare_claims'},config))
            self.assertEqual(api.chat.completions.create.call_count,2)
            self.assertEqual(result['exercise']['questions'][0]['prompt'],correction['exercise']['questions'][0]['prompt'])
            self.assertEqual(result['exercise']['questions'][0]['answer'],value)
            self.assertEqual(result['exercise']['questions'][1]['prompt'],raw['exercise']['questions'][1]['prompt'])
            self.assertEqual(result['exercise']['stimuli'],raw['exercise']['stimuli'])
            self.assertEqual(result['images'],raw['images'])
            self.assertGreaterEqual(result['exercise']['questions'][0]['space_mm'],35)
            repair=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
            self.assertIn('increase its mathematical demand',repair)
            self.assertNotIn('Correct ONLY exercise.questions[].calculation',repair)
