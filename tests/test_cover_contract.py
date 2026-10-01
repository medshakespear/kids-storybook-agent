"""Covers are decorative artwork, with no student puzzle numbering."""
import copy
import unittest

from core.creative_generator import layout_contract, validate_design
from core.pipeline import load_grade_config
from tests.test_creative_design import cover_fixture
from tests.test_exercise_quality import exact_page, visual_fixtures


class CoverContractTests(unittest.TestCase):
    """Exercise metadata cannot cause a valid illustrated cover to fail."""

    def test_unused_invalid_visual_metadata_is_ignored_on_cover(self):
        """Question zero or missing numbers on unused cover metadata require no AI repair."""
        for question in [0, None, 'cover']:
            with self.subTest(question=question):
                raw=cover_fixture()
                raw.update(visuals=[dict(id='decoration',kind='sort',question=question)],
                           answers='Not applicable',calculations=[{'expression':'cover'}])
                result=validate_design(raw,11,cover=True,quality=load_grade_config()['5th-6th'])
                self.assertEqual(result['visuals'],[])
                self.assertNotIn('answers',result)
                self.assertNotIn('calculations',result)
                self.assertEqual(result['images'],raw['images'])
                self.assertEqual(result['html'],raw['html'])
                self.assertEqual(raw['visuals'][0]['question'],question)

    def test_referenced_cover_puzzle_has_actionable_feedback(self):
        """Visible components must be moved or replaced deliberately, never dropped."""
        raw=cover_fixture()
        raw['html']+='<img data-visual="puzzle" style="width:175mm;height:40mm"/>'
        raw['visuals']=[dict(id='puzzle',question=0)]
        with self.assertRaisesRegex(ValueError,'Cover illustrations must use data-asset'):
            validate_design(raw,11,cover=True,quality=load_grade_config()['5th-6th'])

    def test_cover_prompt_does_not_include_student_visual_schema(self):
        """The model receives a dedicated cover contract rather than activity instructions."""
        contract=layout_contract(11,11,cover=True)
        self.assertIn('visuals: []',contract)
        self.assertIn('41mm',contract)
        self.assertNotIn('Optional exact visuals',contract)
        self.assertNotIn('question (printed question number)',contract)
        self.assertIn('Optional exact visuals',layout_contract(11,11))

    def test_student_pages_still_require_valid_question_numbers(self):
        """Only cover metadata is exempt; worksheet validation stays strict."""
        page=exact_page(copy.deepcopy(visual_fixtures()[0]))
        page['visuals'][0]['question']=0
        with self.assertRaisesRegex(ValueError,'Visual question number'):
            validate_design(page,14,quality=load_grade_config()['1st-2nd'])
