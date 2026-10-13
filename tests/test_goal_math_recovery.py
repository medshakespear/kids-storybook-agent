"""Prevent harmless goal headings from exhausting calculation-repair attempts."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.content_binding import bind_standard_heading, goal_heading
from core.creative_generator import ask_json, layout_contract, validate_design
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class GoalMathRecoveryTests(unittest.TestCase):
    """Use production JSON repair and real print checks with mocked providers."""

    def config(self,band):
        """Use the production mixed-activity allowances for an active grade band."""
        return dict(load_grade_config()[band],purposeful_activity_layout=False,
                    context_caption_limit=24,stimulus_limit=8,items_per_page=2)

    def validate(self,page,band):
        """Compile canonical tasks and check their rendered page geometry."""
        config=self.config(band)
        return validate_design(page,config['student_font_pt'],quality=config,
                               expected_title='Garden Detectives',require_coherent=True)

    def test_standalone_goal_labels_bind_for_both_grades(self):
        """A heading consumes no completion and leaves questions, art and answers intact."""
        for band in ('3rd-4th','5th-6th'):
            for label in ('Activity Goal:','Goal:'):
                with self.subTest(band=band,label=label):
                    page=authored_page();original=deepcopy(page)
                    page['html']=page['html'].replace('<p data-content="directions">',
                        '<h3 style="font-size:16pt;color:#167E80"><strong>'+label+'</strong></h3>'
                        '<p data-content="directions">')
                    result=self.validate(page,band)
                    self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                    self.assertEqual(result['images'],original['images'])
                    self.assertEqual(result['html'].count(label),1)
                    self.assertIn({'id':'goal_label_1','text':label},result['exercise']['captions'])

    def test_word_problem_repair_does_not_cascade_into_goal_label_retries(self):
        """One scoped math repair succeeds without changing the original word problem or art."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=authored_page()
                page['html']=page['html'].replace('<p data-content="directions">',
                    '<h3 style="font-size:16pt">Activity Goal:</h3><p data-content="directions">')
                page['exercise']['questions'][0].update(id='2',
                    prompt='Each of 3 boxes holds 12+8 pencils. How many pencils in all?',
                    answer='60 pencils.',space_mm=25)
                page['html']=page['html'].replace('question_1','question_2')
                original=deepcopy(page)
                correction={'exercise':{'questions':[{'id':'2','answer':'60 pencils.',
                    'calculation':{'expression':'3*(12+8)','answer':60}}]}}
                api=Mock();api.chat.completions.create.side_effect=[
                    SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(raw)),
                        finish_reason='stop')]) for raw in (page,correction)]
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
                     patch('core.creative_generator.text_client',return_value=(api,'fixture-model')), \
                     patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(13,12,coherent=True),
                        lambda raw:self.validate(raw,band),'Activity design 2')
                self.assertEqual(api.chat.completions.create.call_count,2)
                question=result['exercise']['questions'][0]
                self.assertEqual(question['prompt'],original['exercise']['questions'][0]['prompt'])
                self.assertEqual(question['space_mm'],25)
                self.assertEqual(question['calculation']['answer'],60)
                self.assertEqual(result['images'],original['images'])
                self.assertEqual(result['html'].count('Activity Goal:'),1)
                self.assertEqual(page,original)
                repair=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
                self.assertIn('Correct ONLY the calculation and answer fields',repair)

    def test_goal_heading_cannot_hide_a_task_or_answer(self):
        """Only the whole standalone label is accepted, never an appended instruction."""
        for text in ('Goal: Draw three extra flowers.','Activity Goal: The answer is 60.'):
            self.assertFalse(goal_heading(text))
            page=authored_page();page['html']+='<p>'+text+'</p>'
            with self.assertRaisesRegex(ValueError,'unbound wording'):
                self.validate(page,'3rd-4th')
        page=authored_page();page['html']+='<h3>Goal:</h3><p>Draw three extra flowers.</p>'
        with self.assertRaisesRegex(ValueError,'unbound wording'):
            self.validate(page,'5th-6th')

    def test_goal_label_respects_budget_and_does_not_guess_calculations(self):
        """Full manifests and unknown word-problem formulas remain explicit defects."""
        exercise={'captions':[{'id':f'c{i}','text':f'Context {i}'} for i in range(6)]}
        original=deepcopy(exercise)
        self.assertEqual(bind_standard_heading('<h3>Goal:</h3>',exercise),'<h3>Goal:</h3>')
        self.assertEqual(exercise,original)
        page=authored_page();page['exercise']['questions'][0].update(
            prompt='Each of 3 boxes holds 12+8 pencils. How many pencils in all?',answer='60 pencils.')
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band),self.assertRaisesRegex(ValueError,'requires a calculation'):
                self.validate(page,band)
