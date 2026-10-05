"""Whole-question arithmetic checks and local repairs across both active grade bands."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from core.printed_arithmetic import standalone_arithmetic
from core.creative_generator import ask_json,layout_contract,validate_design
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class PrintedArithmeticConsistencyTests(unittest.TestCase):
    """Never equate a word-problem fragment with its final calculation."""
    def page(self,prompt,expression,answer):
        """Supply one question with art, writing space and a shared numeric key."""
        page=authored_page();page['exercise']['questions'][0].update(
            prompt=prompt,answer=str(answer),calculation={'expression':expression,'answer':str(answer)},space_mm=25)
        return page

    def validate(self,page,band):
        """Apply full content and measured print checks for the selected active band."""
        config=load_grade_config()[band]
        return validate_design(page,config['student_font_pt'],quality=config,
            expected_title='Classroom Math',require_coherent=True)

    def test_word_problem_fragments_are_not_final_answers(self):
        """Fraction operators, intermediate totals and date ranges cannot cause false mismatches."""
        cases=[('Find 1/2 of 36 items.','36/2',18),
               ('Each of 3 boxes holds 12+8 pencils. How many pencils in all?','3*(12+8)',60),
               ('From 2020-2024, a class made 30 murals. They shared 12. How many remain?','30-12',18)]
        for band in ('3rd-4th','5th-6th'):
            for prompt,expression,answer in cases:
                with self.subTest(band=band,prompt=prompt):
                    result=self.validate(self.page(prompt,expression,answer),band)
                    self.assertEqual(result['computed_math'],[])
                    self.assertEqual(result['exercise']['questions'][0]['calculation']['expression'],expression)

    def test_whole_expressions_are_checked_including_parentheses(self):
        """A contradictory operation remains an error and includes both complete expressions."""
        for band in ('3rd-4th','5th-6th'):
            for prompt in ('What is 12+8?','Compute (12+8)*3. Show your work.'):
                with self.subTest(band=band,prompt=prompt),self.assertRaisesRegex(ValueError,'printed expression.*declared expression'):
                    self.validate(self.page(prompt,'12-8',4),band)

    def test_conflicting_standalone_calculation_is_fixed_without_another_api_call(self):
        """Printed arithmetic drives expression/result/key; original tasks and layout survive."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=self.page('Compute (12+8)*3.','12-8',4);original=deepcopy(page)
                api=Mock();api.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
                with patch('core.creative_generator.text_provider_names',return_value=['gemini']),patch(
                    'core.creative_generator.text_client',return_value=(api,'test')),patch('core.creative_generator.time.sleep'):
                    result=ask_json(layout_contract(13,12,coherent=True),lambda draft:self.validate(draft,band),'Activity design 3')
                question=result['exercise']['questions'][0]
                self.assertEqual(question['calculation'],{'expression':'(12+8)*3','answer':'60'})
                self.assertEqual(question['answer'],'60')
                self.assertEqual(question['prompt'],original['exercise']['questions'][0]['prompt'])
                self.assertEqual(question['space_mm'],25)
                self.assertEqual(result['source_layout'],original['html'])
                self.assertEqual(result['images'],original['images'])
                self.assertEqual(api.chat.completions.create.call_count,1)
                self.assertEqual(page,original)

    def test_extraction_is_whole_and_restricted(self):
        """Accept normal printed notation without guessing word-problem operations or executing code."""
        for prompt in ('Find 1/2 of 36','A class buys 3+4 packs of 5. How many?','Calculate __import__(1)'):
            self.assertIsNone(standalone_arithmetic(prompt))
        self.assertEqual(standalone_arithmetic('Calculate 3 × (4 + 2)?'),'3 * (4 + 2)')
        with self.assertRaises((ValueError,ZeroDivisionError)):
            standalone_arithmetic('Calculate 3/0')
        with self.assertRaises(ValueError):
            standalone_arithmetic('Compute x+3')
