"""Sorting flexibility and stray-calculation regression checks for both active grades."""
from copy import deepcopy
import unittest
from core.calculation_attachment import detach_conceptual_calculation
from core.creative_generator import validate_design
from core.pipeline import load_grade_config
from core.task_visuals import build_visual, answer_text, SHAPES
from tests.coherent_fixtures import authored_page, exact_page


class SortAndConceptualCalculationTests(unittest.TestCase):
    """Preserve original task data and retain verification for quantitative questions."""
    def test_conceptual_question_keeps_oxygen_answer_all_active_grades(self):
        """A stray 3-1 calculation cannot force an unrelated numeric answer into a science key."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                page=authored_page();question=page['exercise']['questions'][0]
                question.update(prompt='Which part of the fire triangle does a lid remove?',
                    answer='Oxygen. The lid blocks outside air from reaching the fire.',
                    calculation={'expression':'3-1','answer':2},space_mm=20)
                original=deepcopy(page);config=load_grade_config()[band]
                result=validate_design(page,config['student_font_pt'],quality=config,
                    expected_title='Fire Science',require_coherent=True)
                corrected=result['exercise']['questions'][0]
                self.assertNotIn('calculation',corrected)
                for field in ('prompt','answer','id','space_mm'):
                    self.assertEqual(corrected[field],question[field])
                self.assertEqual(result['calculations'],[])
                self.assertIn('Oxygen',result['answers'])
                self.assertEqual(page,original)

    def test_arithmetic_and_ambiguous_questions_keep_calculation(self):
        """Words, numeric facts and quantitative actions prevent local detachment."""
        for prompt in ('What is 3-1?','Explain why three minus one equals two.',
                       'How many candles remain?', 'Explain the remaining amount.',
                       'Which part represents half the total?', 'What causes a 10 percent reduction?',
                       'Choose the best result.'):
            question={'prompt':prompt,'answer':'Two.', 'calculation':{'expression':'3-1','answer':2}}
            original=deepcopy(question);detach_conceptual_calculation(question)
            self.assertEqual(question,original)

    def test_wrong_numeric_key_still_rejected(self):
        """The shared answer verification remains mandatory for genuine arithmetic."""
        page=authored_page();page['exercise']['questions'][0].update(
            prompt='What is 3-1?',answer='Oxygen.',calculation={'expression':'3-1','answer':2})
        with self.assertRaisesRegex(ValueError,'verified calculation answer'):
            validate_design(page,13,quality=load_grade_config()['3rd-4th'],
                expected_title='Math',require_coherent=True)

    def test_two_to_eight_sort_groups_fit_both_active_grades(self):
        """Python draws all original bins and computes exact memberships in a readable grid."""
        shapes=sorted(SHAPES)
        for count in range(2,9):
            items=[{'shape':shapes[i%count],'color':'teal','size':'large'} for i in range(max(4,count))]
            spec={'id':'groups','question':1,'kind':'sort','attribute':'shape','items':items}
            _,answer=build_visual(spec)
            for index,item in enumerate(items,1):
                self.assertIn(item['shape'].title()+':',answer)
            for band in ('3rd-4th','5th-6th'):
                with self.subTest(groups=count,band=band):
                    page=exact_page(spec);page['html']=page['html'].replace('height:150mm','height:165mm')
                    config=load_grade_config()[band]
                    result=validate_design(page,config['student_font_pt'],quality=config,
                        expected_title='Sorting Studio',require_coherent=True)
                    self.assertEqual(result['exercise']['visual']['items'],items)
                    self.assertEqual(answer_text(result),answer)

    def test_one_group_still_rejected_with_actionable_diagnostic(self):
        """A non-sortable collection is not silently changed into a different student task."""
        spec={'id':'groups','question':1,'kind':'sort','attribute':'shape',
              'items':[{'shape':'star','color':'teal','size':'large'}]*4}
        with self.assertRaisesRegex(ValueError,'at least two groups'):
            build_visual(spec)
