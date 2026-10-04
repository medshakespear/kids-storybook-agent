"""Distinguish safe arithmetic literals from grade-level final-result constraints."""
from fractions import Fraction
import unittest
from core.exercise_quality import calculate
from core.creative_generator import validate_design
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class LargeLiteralArithmeticTests(unittest.TestCase):
    """Accept legitimate percentage bases without weakening result or syntax checks."""
    def test_reported_percentage_expressions_evaluate_exactly(self):
        """Both equivalent reported expressions calculate 1800 using exact fractions."""
        for expression in ('12000*15/100','12000*0.15'):
            self.assertEqual(calculate(expression),Fraction(1800))
        self.assertEqual(calculate('12000*0.125'),Fraction(1500))

    def page(self, expression='12000*15/100', result='1800'):
        """Create an upper-grade percentage task using supplied numerical data."""
        page=authored_page()
        page['exercise']['questions']=[{'id':'1','prompt':'What is 15 percent of 12000?',
            'answer':result,'calculation':{'expression':expression,'answer':result},'space_mm':20}]
        return page

    def validate(self,page):
        """Run shared answer verification, grade limits and rendered print checks."""
        return validate_design(page,11,quality=load_grade_config()['5th-6th'],
            expected_title='Percentage Challenge',require_coherent=True)

    def test_upper_grade_page_passes_real_validation(self):
        """A large input with a grade-appropriate result works without a provider repair."""
        for expression in ('12000*15/100','12000*0.15'):
            result=self.validate(self.page(expression))
            self.assertIn('1800',result['answers'])
            self.assertEqual(result['exercise']['questions'][0]['space_mm'],20)

    def test_magnitude_failure_is_not_misreported_as_unsupported_syntax(self):
        """Oversized literals and intermediate results remain bounded with specific errors."""
        with self.assertRaisesRegex(ValueError,'Arithmetic literal is too large'):
            calculate('1000001/1000')
        with self.assertRaisesRegex(ValueError,'Arithmetic result is too large'):
            calculate('1000000*2')

    def test_grade_result_and_wrong_answers_are_still_rejected(self):
        """The evaluator's safety limit cannot replace grade difficulty or correct answers."""
        page=self.page('12000+1','12001')
        page['exercise']['questions'][0]['prompt']='What is 12000 + 1?'
        with self.assertRaisesRegex(ValueError,'outside this grade band'):
            self.validate(page)
        with self.assertRaises(ValueError):
            self.validate(self.page(result='1801'))

    def test_executable_and_unsupported_expressions_remain_rejected(self):
        """Variables, powers, functions and modulo never execute."""
        for expression in ('x+2','12000**2','abs(-12000)','12000%15','__import__("os")'):
            with self.subTest(expression=expression),self.assertRaises(ValueError):
                calculate(expression)
