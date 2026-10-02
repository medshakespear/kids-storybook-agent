"""Regression coverage for exact-puzzle direction and question ownership failures."""
import json
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.creative_generator import ask_json, layout_contract, validate_design
from core.page_contract import EXERCISE_CONTRACT
from core.pipeline import load_grade_config
from tests.coherent_fixtures import exact_page, visual_examples


class ExactContentRepairTests(unittest.TestCase):
    """Repair one shared task without making up answers or deleting real student actions."""

    def validate(self,page):
        """Run shared binding and measured Pre-K print preflight."""
        return validate_design(page,15,quality=load_grade_config()['Pre-K-K'],
                               expected_title="Pip's Bakery",require_coherent=True)

    def exact(self):
        """Use a valid count-and-write graphic with a computed answer."""
        return exact_page(visual_examples()[3])

    def test_parallel_directions_and_reserved_label_report_together(self):
        """One correction gets both problems instead of discovering one per API call."""
        raw=self.exact()
        raw['exercise']['directions']='Count and connect the glowing star cookies.'
        raw['exercise']['questions']=[dict(id='1',prompt='Count the stars.',answer='Three.',space_mm=0)]
        with self.assertRaises(ValueError) as raised:
            self.validate(raw)
        self.assertIn('verified directions',str(raised.exception))
        self.assertIn('reserved label 1',str(raised.exception))
        self.assertIn('questions item 1',str(raised.exception))

    def test_additional_action_remains_printed_and_keyed(self):
        """An original second action survives alongside the computed counting task."""
        raw=self.exact()
        raw['exercise']['questions']=[dict(id='2',prompt='Invent a new cookie shape.',
                                         answer='Accept an original drawn shape.',space_mm=25)]
        raw['html']+='<div data-content="question_2"></div>'
        result=self.validate(raw)
        self.assertIn('2. Invent a new cookie shape.',result['html'])
        self.assertIn('2. Accept an original drawn shape.',result['answers'])
        self.assertEqual(result['exercise_binding']['question_ids'],['1','2'])

    def test_unbound_task_directions_still_fail_instead_of_becoming_caption(self):
        """Counting and connecting instructions cannot be hidden in a decorative label."""
        raw=self.exact()
        raw['html']='<p>Count the glowing star cookies on each tray and connect them.</p>'+raw['html']
        with self.assertRaisesRegex(ValueError,'unbound wording'):
            self.validate(raw)

    def test_reserved_question_is_not_automatically_discarded(self):
        """A conflicting but genuinely different task requires correction of its label."""
        raw=self.exact()
        raw['exercise']['questions']=[dict(id='1',prompt='Invent a new cookie shape.',
                                         answer='Accept an original shape.',space_mm=25)]
        raw['html']+='<div data-content="question_1"></div>'
        with self.assertRaisesRegex(ValueError,'genuinely additional action'):
            self.validate(raw)

    def test_reported_chain_repairs_in_one_response_using_current_schema(self):
        """Duplicate labels, raw wording and parallel directions get cohesive exact-mode guidance."""
        bad=self.exact()
        bad['exercise']['directions']='Count and connect the star cookies.'
        bad['exercise']['questions']=[dict(id='1',prompt='Count the stars.',answer='Three.',space_mm=0)]
        bad['html']='<p>Count and connect the star cookies.</p>'+bad['html']
        good=self.exact()
        api=Mock()
        def response(page):
            """Produce a complete mocked chat completion without live credentials."""
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
        api.chat.completions.create.side_effect=[response(bad),response(good)]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(15,14,coherent=True),self.validate,'Activity design 1')
        correction=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
        self.assertIn('Omit exercise.directions and exercise.passage AND their HTML slots',correction)
        self.assertIn('Keep all genuinely additional student actions',correction)
        self.assertIn('exercise.visual (singular)',correction)
        self.assertNotIn('including html, images, visuals and answers',correction)
        self.assertEqual(result['exercise']['questions'],[])
        self.assertEqual(api.chat.completions.create.call_count,2)
        self.assertEqual(result['visuals'][0]['rows'],good['exercise']['visual']['rows'])

    def test_initial_contract_explains_exact_number_and_slot_ownership(self):
        """The initial prompt prevents duplicates before spending a repair attempt."""
        self.assertIn('questions:[], NO directions/passage',EXERCISE_CONTRACT)
        self.assertIn('visual.question=1 owns printed task 1',EXERCISE_CONTRACT)
        self.assertIn('count and WRITE',EXERCISE_CONTRACT)
