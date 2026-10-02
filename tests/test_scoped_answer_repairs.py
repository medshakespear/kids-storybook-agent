"""Answer-only retries must preserve student tasks, meaningful artwork and layout."""
import json
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.creative_generator import ask_json, layout_contract, merge_answer_repair, validate_design
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class ScopedAnswerRepairTests(unittest.TestCase):
    """Regress the answer-length -> missing-art -> small-art failure chain."""

    def validate(self,page):
        """Use actual binding and middle-grade print and visual checks."""
        cfg=load_grade_config()['3rd-4th']
        return validate_design(page,cfg['student_font_pt'],quality=cfg,
                               expected_title='Garden Invention',require_coherent=True)

    def ask(self,responses,validator=None):
        """Run mock provider responses through the complete production retry loop."""
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(r) if isinstance(r,dict) else r),
            finish_reason='stop')]) for r in responses]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(12,12,coherent=True),validator or self.validate,'Activity design 1')
        return result,api

    def test_answer_repair_preserves_original_art_and_task_despite_drifting_response(self):
        """A repair deleting artwork or replacing instructions contributes only its new answer."""
        original=authored_page();original['exercise']['questions'][0]['answer']='Accept a design. '*15
        unchanged=deepcopy(original)
        correction=authored_page();correction['images']=[];correction['html']='<p>Unrelated task</p>'
        correction['exercise']['goal']='A changed goal'
        correction['exercise']['questions'][0].update(prompt='A changed task',space_mm=0,
                            answer='Accept a shelter allowing sunlight and watering access.')
        result,api=self.ask([original,correction])
        self.assertEqual(original,unchanged)
        self.assertEqual(result['images'],original['images'])
        self.assertEqual(result['source_layout'],original['html'])
        self.assertEqual(result['exercise']['goal'],original['exercise']['goal'])
        self.assertEqual(result['exercise']['questions'][0]['space_mm'],45)
        self.assertEqual(result['exercise']['questions'][0]['prompt'],original['exercise']['questions'][0]['prompt'])
        self.assertEqual(api.chat.completions.create.call_count,2)
        message=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
        self.assertIn('Correct ONLY the answer field',message)
        self.assertIn('180 characters',message)

    def test_question_three_repair_does_not_change_other_answers(self):
        """Only the specifically rejected answer changes, including a later question ID."""
        page=authored_page()
        page['exercise']['questions'] += [dict(id='2',prompt='Name your invention.',answer='Any original name.',space_mm=0),
                                         dict(id='3',prompt='Describe the benefit.',answer='Long criterion. '*20,space_mm=0)]
        page['html']+='<p data-content="question_2"></p><p data-content="question_3"></p>'
        response=deepcopy(page)
        response['exercise']['questions'][0]['answer']='Changed other answer.'
        response['exercise']['questions'][2]['answer']='Accept a benefit linked to sunlight or watering.'
        result,_=self.ask([page,response])
        self.assertEqual(result['exercise']['questions'][0]['answer'],page['exercise']['questions'][0]['answer'])
        self.assertEqual(result['exercise']['questions'][1],page['exercise']['questions'][1])
        self.assertEqual(result['exercise']['questions'][2]['answer'],response['exercise']['questions'][2]['answer'])

    def test_missing_target_id_is_rejected_without_losing_original(self):
        """A malformed repair must not replace the retained original page."""
        page=authored_page();original=deepcopy(page)
        for correction in [{}, {'exercise':{'questions':[{'id':'2','answer':'Different answer'}]}},
                           {'exercise':{'questions':[{'id':'1','answer':'A'},{'id':'1','answer':'B'}]}}]:
            with self.subTest(correction=correction),self.assertRaisesRegex(ValueError,'Answer-only repair'):
                merge_answer_repair(page,correction,'1')
        self.assertEqual(page,original)

    def test_json_error_does_not_clear_scoped_original(self):
        """Serialization retry keeps the same answer scope and original art manifest."""
        page=authored_page();page['exercise']['questions'][0]['answer']='Long criterion. '*20
        correction={'exercise':{'questions':[{'id':'1','answer':'Accept a shelter allowing sunlight and watering access.'}]}}
        result,api=self.ask([page,'{',correction])
        self.assertEqual(result['images'],page['images'])
        self.assertEqual(result['source_layout'],page['html'])
        self.assertEqual(api.chat.completions.create.call_count,3)

    def test_short_answer_still_gets_arithmetic_verification(self):
        """Scoped extraction cannot make a wrong numeric key pass local validation."""
        page=authored_page();page['exercise']['questions'][0].update(prompt='What is 3 + 4?',
            answer='Long criterion. '*20,calculation={'expression':'3+4','answer':7},space_mm=20)
        changed=merge_answer_repair(page,{'exercise':{'questions':[{'id':'1','answer':'8'}]}},'1')
        with self.assertRaisesRegex(ValueError,'verified calculation answer'):
            self.validate(changed)

    def test_visual_failure_reports_measured_and_required_areas(self):
        """Quality errors give actual millimetre dimensions while retaining the grade floor."""
        page=authored_page();page['html']=page['html'].replace('width:175mm;height:75mm','width:50mm;height:30mm')
        with self.assertRaises(ValueError) as raised:
            self.validate(page)
        diagnostic=str(raised.exception)
        self.assertIn('at least 8000',diagnostic)
        self.assertIn('main visual of at least 4400',diagnostic)
        self.assertIn('measured total 1500',diagnostic)
        self.assertIn('largest visual 1500',diagnostic)

    def test_visual_size_repair_keeps_task_and_restores_useful_art(self):
        """A reflow repair can meet visual targets without losing response space or answers."""
        small=authored_page();small['html']=small['html'].replace('width:175mm;height:75mm','width:50mm;height:30mm')
        large=deepcopy(small);large['html']=large['html'].replace('width:50mm;height:30mm','width:150mm;height:90mm')
        result,api=self.ask([small,large])
        self.assertEqual(result['exercise'],small['exercise'])
        self.assertEqual(result['images'],small['images'])
        repair=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
        self.assertIn('Repair visual dimensions and layout ONLY',repair)
        self.assertIn('width:150mm;height:90mm',repair)
        self.assertIn('never shrink student text',repair)
