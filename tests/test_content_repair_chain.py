"""Regress cascading prompt/answer defects and explicitly rounded classroom mathematics."""
import json
from copy import deepcopy
from fractions import Fraction
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design,merge_prompt_repair
from core.exercise_quality import expected_calculation,validate_exercises
from core.pipeline import load_grade_config
from core.activity_generator import ActivityGenerationError
from tests.coherent_fixtures import authored_page


class ContentRepairChainTests(unittest.TestCase):
    """Preserve creative tasks while repairing only identified fields."""

    def validate(self,page):
        """Use real shared compilation and upper-grade print validation."""
        return validate_design(page,11,quality=load_grade_config()['5th-6th'],
                               expected_title='Creative Studio',require_coherent=True)

    def ask(self,responses):
        """Run the production loop with deterministic API responses."""
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(r)),finish_reason='stop')]) for r in responses]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(11,11,coherent=True),self.validate,'Activity design 1')
        return result,api

    def rounded_page(self):
        """Match the reported division with a genuinely printed rounding instruction."""
        page=authored_page()
        page['exercise']['questions']=[dict(id='1',prompt='A mural costs $996 after a 15% discount. Find its original price. Round to the nearest cent.',
                     answer='$1171.76',space_mm=25,calculation={'expression':'996/0.85','answer':1171.76})]
        return page

    def test_explicit_currency_rounding_passes_both_math_validators(self):
        """A correct rounded answer must not be rejected as an inexact rational."""
        page=self.validate(self.rounded_page())
        validate_exercises(page,load_grade_config()['5th-6th'])
        self.assertEqual(expected_calculation('996/0.85','Round to the nearest cent.'),Fraction('1171.76'))

    def test_no_rounding_instruction_retains_exact_math_requirement(self):
        """Do not assume all currency or decimal questions should be rounded."""
        page=self.rounded_page();page['exercise']['questions'][0]['prompt']='A mural costs $996 after a 15% discount. Find its exact original price.'
        with self.assertRaisesRegex(ValueError,'declared math answer is incorrect'):
            self.validate(page)

    def test_half_up_rounding_is_exact_for_ties_and_negatives(self):
        """Avoid float precision and bankers-rounding surprises."""
        for expression,places,result in [('1.005',2,'1.01'),('-1.005',2,'-1.01'),
                                         ('8/3',2,'2.67'),('5/2',0,'3'),('1/8',3,'0.125')]:
            with self.subTest(expression=expression):
                self.assertEqual(expected_calculation(expression,f'Round to {places} decimal places.'),Fraction(result))
        with self.assertRaisesRegex(ValueError,'conflict'):
            expected_calculation('8/3','Round to the nearest tenth and to two decimal places.')

    def test_prompt_only_correction_keeps_rounding_math_and_art(self):
        """A short task correction cannot delete or redesign the rest of the page."""
        page=self.rounded_page()
        short=page['exercise']['questions'][0]['prompt']
        page['exercise']['questions'][0]['prompt']='Consider this detailed classroom studio scenario carefully. '*12+short
        original=deepcopy(page)
        correction={'exercise':{'questions':[{'id':'1','prompt':short}]},'images':None,'html':'Wrong layout'}
        result,api=self.ask([page,correction])
        self.assertEqual(page,original)
        self.assertEqual(result['images'],page['images'])
        self.assertEqual(result['source_layout'],page['html'])
        self.assertEqual(result['exercise']['questions'][0]['calculation'],page['exercise']['questions'][0]['calculation'])
        self.assertEqual(api.chat.completions.create.call_count,2)

    def test_prompt_repair_cannot_change_numbers_or_quantities(self):
        """Do not silently simplify a word problem by changing its data."""
        page=self.rounded_page()
        with self.assertRaisesRegex(ValueError,'preserve every numeric'):
            merge_prompt_repair(page,{'exercise':{'questions':[{'id':'1','prompt':'A mural costs $99 after a 15% discount.'}]}},'1')

    def test_prompt_repair_cannot_drop_rounding_instructions(self):
        """The shorter wording must still ask for the same precision."""
        page=self.rounded_page()
        with self.assertRaisesRegex(ValueError,'rounding precision'):
            merge_prompt_repair(page,{'exercise':{'questions':[{'id':'1','prompt':'A mural costs $996 after a 15% discount. Find its original price.'}]}},'1')

    def test_rounding_does_not_bypass_younger_grade_whole_number_rule(self):
        """Rounding a fraction to an integer cannot make it appropriate for early grades."""
        page=self.rounded_page()
        page['exercise']['questions'][0].update(prompt='Calculate 5 / 2. Round to the nearest whole number.',
                  calculation={'expression':'5/2','answer':3},answer='3')
        with self.assertRaisesRegex(ValueError,'whole-number'):
            validate_design(page,14,quality=load_grade_config()['1st-2nd'],
                            expected_title='Creative Studio',require_coherent=True)

    def test_distinct_field_repairs_receive_bounded_progress_budget(self):
        """Four independent defects can be corrected without discarding prior progress."""
        page=authored_page()
        long_prompt='Describe your original shelter and show its useful features. '*12
        long_answer='Accept a shelter design that protects the plant and allows sunlight. '*8
        page['exercise']['questions']=[dict(id=str(i),prompt=long_prompt,answer=long_answer,space_mm=15) for i in [1,2]]
        page['html']+='<div data-content="question_2"></div>'
        replies=[page]
        for i,field,text in [('1','prompt','Draw an original useful plant shelter.'),
                             ('1','answer','Accept a protective design allowing sunlight.'),
                             ('2','prompt','Draw another shelter and show how to water it.'),
                             ('2','answer','Accept a design allowing watering and sunlight.')]:
            replies.append({'exercise':{'questions':[{'id':i,field:text}]}})
        result,api=self.ask(replies)
        self.assertEqual(api.chat.completions.create.call_count,5)
        self.assertEqual(result['images'],page['images'])
        self.assertEqual([q['space_mm'] for q in result['exercise']['questions']],[15,15])

    def test_same_defect_cannot_replenish_retry_budget(self):
        """Unsuccessful rewrites still stop after the configured attempt limit."""
        page=authored_page();page['exercise']['questions'][0]['prompt']='Draw your shelter. '*40
        with self.assertRaises(ActivityGenerationError):
            self.ask([page]*4)


if __name__=='__main__':
    unittest.main()
