"""Exact/rounded percent keys must share one computed result, without choosing operations."""
import json
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design
from core.math_result_recovery import repair_declared_result
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class PercentageResultRecoveryTests(unittest.TestCase):
    """Regress the 27/39*100 exact-fraction versus decimal retry loop."""

    def page(self,rounding=False):
        """Create a coherent percent word problem with one inconsistent result."""
        page=authored_page()
        prompt='Of 39 students, 27 joined the helpers. What percentage joined?'
        if rounding:
            prompt+=' Round to two decimal places.'
        page['exercise']['questions']=[dict(id='3',prompt=prompt,answer='69.23%',space_mm=25,
                               calculation={'expression':'27/39*100','answer':69.23})]
        page['html']=page['html'].replace('question_1','question_3')
        return page

    def validate(self,page):
        """Run real shared binding, math and upper-grade print checks."""
        return validate_design(page,11,quality=load_grade_config()['5th-6th'],
                               expected_title='Community Helpers',require_coherent=True)

    def ask(self,responses):
        """Use the production retry flow with mocked provider output."""
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(r)),finish_reason='stop')]) for r in responses]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(11,11,coherent=True),self.validate,'Activity design 2')
        return result,api

    def test_manifest_recovery_then_percentage_math_finishes_without_math_retry(self):
        """Fix the exact user failure chain while keeping the recovered art and word problem."""
        page=self.page();page['images']=None
        original=deepcopy(page)
        result,api=self.ask([page,{'images':authored_page()['images']}])
        self.assertEqual(api.chat.completions.create.call_count,2)
        question=result['exercise']['questions'][0]
        self.assertEqual(question['answer'],'900/13%')
        self.assertEqual(question['calculation']['answer'],'900/13')
        self.assertEqual(question['prompt'],page['exercise']['questions'][0]['prompt'])
        self.assertEqual(question['space_mm'],25)
        self.assertEqual(page,original)

    def test_correct_calculation_with_rounded_key_is_recovered_locally(self):
        """A stale prose key cannot restart the exact/rounded calculation loop."""
        page=self.page();page['exercise']['questions'][0]['calculation']['answer']='900/13'
        result,api=self.ask([page])
        self.assertEqual(result['exercise']['questions'][0]['answer'],'900/13%')
        self.assertEqual(api.chat.completions.create.call_count,1)

    def test_requested_rounding_remains_a_decimal(self):
        """Explicit rounding is respected rather than replaced by an exact fraction."""
        page=self.page(True);page['exercise']['questions'][0].update(answer='69.2%',
                    calculation={'expression':'2700/39','answer':69.2})
        result,api=self.ask([page])
        self.assertEqual(result['exercise']['questions'][0]['answer'],'69.23%')
        self.assertEqual(result['exercise']['questions'][0]['calculation']['answer'],'69.23')
        self.assertEqual(api.chat.completions.create.call_count,1)

    def test_percent_annotation_preserves_other_context_numbers(self):
        """Only the identified percentage is changed, keeping the 27 and 39 facts."""
        page=self.page();page['exercise']['questions'][0]['answer']='27 of 39 students (69.23%).'
        corrected=repair_declared_result(page,'3')
        self.assertEqual(corrected['exercise']['questions'][0]['answer'],'27 of 39 students (900/13%).')
        self.validate(corrected)

    def test_ambiguous_numeric_criteria_are_not_rewritten(self):
        """Unrelated numeric quantities and multiple percentage results need semantic repair."""
        for answer in ['Accept a drawing with 3 labelled helpers.','69.23% and 69.2% of two separate groups.']:
            page=self.page();page['exercise']['questions'][0]['answer']=answer
            self.assertIsNone(repair_declared_result(page,'3'))

    def test_recovery_does_not_choose_a_different_operation(self):
        """If the declared operation contradicts printed arithmetic, the full validator rejects it."""
        page=self.page();page['exercise']['questions'][0].update(prompt='Calculate 12 - 8',answer='21',
                                         calculation={'expression':'12+8','answer':21})
        corrected=repair_declared_result(page,'3')
        self.assertEqual(corrected['exercise']['questions'][0]['calculation']['expression'],'12+8')
        with self.assertRaisesRegex(ValueError,'does not solve the printed arithmetic'):
            self.validate(corrected)


if __name__=='__main__':
    unittest.main()
