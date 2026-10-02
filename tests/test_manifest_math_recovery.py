"""An image-manifest recovery must not strand a safely computable arithmetic answer."""
import json
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from core.creative_generator import ask_json,layout_contract,validate_design,repair_printed_arithmetic
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class ManifestMathRecoveryTests(unittest.TestCase):
    """Exercise real shared validation across consecutive content defects."""

    def page(self):
        """Make a usable upper-grade arithmetic worksheet with a wrong numeric result."""
        page=authored_page()
        page['exercise']['questions']=[dict(id='1',prompt='What is 12 + 8?',answer='21',space_mm=25,
                                          calculation={'expression':'12+8','answer':21})]
        return page

    def validate(self,page):
        """Compile tasks and perform actual upper-grade print checks."""
        return validate_design(page,11,quality=load_grade_config()['5th-6th'],
                               expected_title='Innovation Studio',require_coherent=True)

    def ask(self,responses):
        """Return provider calls and validated output without a live API."""
        api=Mock()
        api.chat.completions.create.side_effect=[SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(r)),finish_reason='stop')]) for r in responses]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(11,11,coherent=True),self.validate,'Activity design 1')
        return result,api

    def test_null_manifest_then_wrong_math_finishes_after_prompt_recovery(self):
        """Preserve the recovered prompts and locally compute the printed expression."""
        original=self.page();original['images']=None
        result,api=self.ask([original,{'images':authored_page()['images']}])
        self.assertEqual(api.chat.completions.create.call_count,2)
        self.assertEqual(result['images'],authored_page()['images'])
        self.assertEqual(result['source_layout'],original['html'])
        question=result['exercise']['questions'][0]
        self.assertEqual(question['answer'],'20')
        self.assertEqual(question['calculation']['answer'],'20')
        self.assertEqual(question['prompt'],original['exercise']['questions'][0]['prompt'])
        self.assertEqual(question['space_mm'],25)

    def test_standalone_wrong_math_needs_no_extra_api_call(self):
        """Correct only results, leaving canonical layout, wording and prompts intact."""
        original=self.page();snapshot=deepcopy(original)
        result,api=self.ask([original])
        self.assertEqual(api.chat.completions.create.call_count,1)
        self.assertEqual(original,snapshot)
        self.assertEqual(result['images'],original['images'])
        self.assertEqual(result['exercise']['questions'][0]['answer'],'20')

    def test_untrusted_or_semantic_questions_still_need_repair(self):
        """Do not guess word-problem operations or overwrite prose success criteria."""
        for changes in [dict(prompt='There are 12 pencils and 8 students. How many pencils remain?'),
                        dict(answer='Accept 21 drawings with labels.'),
                        dict(calculation={'expression':'12-8','answer':5}),
                        dict(calculation={'expression':'12/0','answer':21})]:
            page=self.page();page['exercise']['questions'][0].update(changes)
            with self.subTest(changes=changes):
                self.assertIsNone(repair_printed_arithmetic(page,'1'))

    def test_division_preserves_exact_fraction(self):
        """Avoid floating-point rounding errors when correcting the key."""
        page=self.page();page['exercise']['questions'][0].update(prompt='Calculate 8 ÷ 3',answer='3',
                      calculation={'expression':'8/3','answer':3})
        result,api=self.ask([page])
        self.assertEqual(result['exercise']['questions'][0]['answer'],'8/3')
        self.assertEqual(api.chat.completions.create.call_count,1)

    def test_remaining_layout_defect_is_not_bypassed_by_math_repair(self):
        """The repaired result still runs every content and layout check."""
        page=self.page();page['html']+='<p>Unbound extra instruction</p>'
        fixed=repair_printed_arithmetic(page,'1')
        with self.assertRaisesRegex(ValueError,'unbound wording'):
            self.validate(fixed)

    def test_two_wrong_results_are_corrected_without_repeated_api_repairs(self):
        """Successive calculations are recomputed while all question spaces survive."""
        page=self.page()
        page['exercise']['questions'].append(dict(id='2',prompt='Calculate 4 * 3',answer='13',space_mm=10,
                                  calculation={'expression':'4*3','answer':13}))
        page['html']+='<p data-content="question_2"></p>'
        result,api=self.ask([page])
        self.assertEqual([q['answer'] for q in result['exercise']['questions']],['20','12'])
        self.assertEqual(api.chat.completions.create.call_count,1)


if __name__=='__main__':
    unittest.main()
