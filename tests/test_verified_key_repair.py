"""Recover prose keys without allowing an already verified operation to drift."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.number_word_answers import whole_number_word_answer
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class VerifiedKeyRepairTests(unittest.TestCase):
    """Check lower-grade numeric wording and narrowly scoped answer-only corrections."""

    def page(self,answer):
        """Build a correct calculation with independently supplied prose key wording."""
        page=authored_page()
        page['exercise']['questions']=[{'id':'2',
            'prompt':'A class has 12 beads and gets 8 more. How many beads does it have?',
            'answer':answer,'space_mm':25,'calculation':{'expression':'12+8','answer':20}}]
        page['html']=page['html'].replace('question_1','question_2')
        return page

    def validate(self,page):
        """Compile tasks and measure a real first/second-grade printable page."""
        return validate_design(page,14,quality=load_grade_config()['1st-2nd'],
                               expected_title='Garden Detectives',require_coherent=True)

    def test_correct_number_words_remain_printed_as_authored(self):
        """A complete spelled-out result does not need a model correction."""
        for answer in ['Twenty','twenty beads.','Answer: twenty beads']:
            page=self.page(answer)
            with self.subTest(answer=answer):
                result=self.validate(page)
                self.assertEqual(result['exercise']['questions'][0]['answer'],answer)

    def test_wrong_word_answer_still_rejected_with_expected_value(self):
        """Recognition never changes the computed result to match an incorrect key."""
        with self.assertRaisesRegex(ValueError,"expected 20 from '12\\+8'.*received 'nineteen beads'"):
            self.validate(self.page('nineteen beads'))

    def test_fraction_and_task_wording_are_not_inferred_as_cardinals(self):
        """Do not mistake partial fractions or instructions for a complete result."""
        for text in ['one half','one third','one hundred','twenty or thirty',
                     'Draw twenty beads','one more','twenty-one minus one','twenty - one','twenty beads and two coins']:
            with self.subTest(text=text):
                self.assertIsNone(whole_number_word_answer(text))
        self.assertEqual(whole_number_word_answer('twenty-one beads.'),21)
        self.assertEqual(whole_number_word_answer('zero'),0)

    def test_answer_only_retry_cannot_change_correct_calculation_or_task(self):
        """Apply just the key correction even if a model invents a different operation."""
        page=self.page('There were 12 initially and 8 more.')
        original=deepcopy(page)
        correction={'html':'<p>Unrelated page</p>','images':None,'exercise':{'questions':[{
            'id':'2','prompt':'Calculate 999 + 1','answer':'20 beads',
            'calculation':{'expression':'999+1','answer':1000},'space_mm':0}]}}
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(raw)),finish_reason='stop')]) for raw in [page,correction]]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(14,13,coherent=True),self.validate,'Activity design 1')
        question=result['exercise']['questions'][0]
        self.assertEqual(question['calculation'],original['exercise']['questions'][0]['calculation'])
        self.assertEqual(question['prompt'],original['exercise']['questions'][0]['prompt'])
        self.assertEqual(question['space_mm'],25)
        self.assertEqual(question['answer'],'20 beads')
        self.assertEqual(result['source_layout'],original['html'])
        self.assertEqual(result['images'],original['images'])
        message=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
        self.assertIn('Correct ONLY the answer field',message)
        self.assertIn("expected 20 from '12+8'",message)
        self.assertEqual(api.chat.completions.create.call_count,2)
        self.assertEqual(page,original)


if __name__=='__main__':
    unittest.main()
