"""Treat sentence punctuation as punctuation while retaining exact arithmetic checks."""
from copy import deepcopy
from fractions import Fraction
import unittest
from core.math_result_recovery import NUMBER, repair_declared_result
from core.creative_generator import validate_design
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class PunctuatedMathAnswerTests(unittest.TestCase):
    """Verify real questions and keys in both active bands, without provider calls."""

    def validate(self,prompt,expression,result,answer,band):
        """Compile a literal arithmetic task with the actual grade and print checks."""
        page=authored_page();page['exercise']['questions'][0].update(
            prompt=prompt,answer=answer,calculation={'expression':expression,'answer':str(result)},space_mm=25)
        config=load_grade_config()[band]
        return validate_design(page,config['student_font_pt'],quality=config,expected_title='Classroom Math',require_coherent=True)

    def test_integer_decimal_fraction_and_mixed_answers_accept_terminal_periods(self):
        """Whole tokens remain exact even when an explanatory sentence follows."""
        cases=[('What is 5-2?','5-2',3,'3. Accept explanations showing the subtraction.'),
               ('What is 7/2?','7/2',Fraction(7,2),'3.5. The quotient is between three and four.'),
               ('What is 7/2?','7/2',Fraction(7,2),'7/2. An exact fraction is acceptable.'),
               ('What is 7/2?','7/2',Fraction(7,2),'3 1/2. An exact mixed number is acceptable.'),
               ('What is 1000+0?','1000+0',1000,'1,000. This is the exact total.')]
        for band in ('3rd-4th','5th-6th'):
            for prompt,expression,result,answer in cases:
                with self.subTest(band=band,answer=answer):
                    checked=self.validate(prompt,expression,result,answer,band)
                    self.assertEqual(checked['exercise']['questions'][0]['answer'],answer)
                    self.assertIn('height:25mm',checked['html'])

    def test_decimal_fraction_and_embedded_digits_cannot_match_partial_results(self):
        """A prefix 3 in 3.5, 13 or 3/5 is not the verified result 3."""
        for answer in ('3.5. An explanation follows.','13. An explanation follows.',
                       '3/5. An explanation follows.','Q3 is the question label.','−3. An explanation follows.'):
            for band in ('3rd-4th','5th-6th'):
                with self.subTest(band=band,answer=answer),self.assertRaisesRegex(ValueError,'verified calculation answer'):
                    self.validate('What is 5-2?','5-2',3,answer,band)
        self.assertEqual(NUMBER.findall('3.5. 7/2. Q3 13.'),['3.5','7/2','13'])

    def test_punctuated_wrong_leading_result_can_be_corrected_without_losing_explanation(self):
        """The existing safe local repair can recognize the result before a full stop."""
        page=authored_page();page['exercise']['questions'][0].update(prompt='What is 5-2?',
            answer='4. The subtraction gives the remaining amount.',calculation={'expression':'5-2','answer':4})
        original=deepcopy(page);fixed=repair_declared_result(page,'1')
        self.assertEqual(fixed['exercise']['questions'][0]['answer'],'3. The subtraction gives the remaining amount.')
        self.assertEqual(fixed['exercise']['questions'][0]['calculation']['answer'],'3')
        self.assertEqual(page,original)

    def test_missing_calculation_is_supplied_only_for_a_complete_literal_task(self):
        """Python supplies a whole printed operation without guessing a word-problem formula."""
        for band in ('3rd-4th','5th-6th'):
            page=authored_page();page['exercise']['questions'][0].update(prompt='What is 5-2?',answer='3.',space_mm=25)
            config=load_grade_config()[band];original=deepcopy(page)
            checked=validate_design(page,config['student_font_pt'],quality=config,expected_title='Classroom Math',require_coherent=True)
            self.assertEqual(checked['exercise']['questions'][0]['calculation'],{'expression':'5-2','answer':'3'})
            self.assertEqual(page,original)
            page['exercise']['questions'][0].update(prompt='Each of 3 boxes holds 12+8 pencils. How many pencils in all?',answer='60.')
            with self.assertRaisesRegex(ValueError,'requires a calculation'):
                validate_design(page,config['student_font_pt'],quality=config,expected_title='Classroom Math',require_coherent=True)

    def test_missing_calculation_does_not_invent_a_numeric_prose_answer(self):
        """A qualitative key for a numeric question still needs semantic correction."""
        page=authored_page();page['exercise']['questions'][0].update(prompt='What is 5-2?',
            answer='Accept explanations about personal opinions.')
        with self.assertRaisesRegex(ValueError,'verified calculation answer'):
            validate_design(page,13,quality=load_grade_config()['3rd-4th'],expected_title='Classroom Math',require_coherent=True)
