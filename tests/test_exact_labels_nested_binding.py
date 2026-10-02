"""Keep creative add-on actions and nested canonical text without accepting new tasks."""
from copy import deepcopy
import unittest

from core.creative_generator import validate_design
from core.pipeline import load_grade_config
from core.question_labels import renumber_open_exact_question
from tests.coherent_fixtures import authored_page,exact_page,visual_examples


class ExactLabelsNestedBindingTests(unittest.TestCase):
    """Regress reserved exact-question IDs followed by inferred nested-slot failures."""

    def validate(self,page):
        """Compile and measure an actual lower-grade worksheet."""
        return validate_design(page,14,quality=load_grade_config()['1st-2nd'],
                               expected_title='Garden Detectives',require_coherent=True)

    def exact(self,prompt='Draw your own friendly pumpkin.'):
        """Create a computed visual and a separately authored open extension."""
        page=exact_page(visual_examples()[3])
        page['exercise']['questions']=[{'id':'1','prompt':prompt,
            'answer':'Accept an original friendly pumpkin drawing.','space_mm':20}]
        page['html']+='<div data-content="question_1"></div>'
        return page

    def test_open_extension_is_renumbered_with_its_slot_and_key(self):
        """Keep the computed puzzle as 1 and the real drawing action as 2."""
        page=self.exact(); original=deepcopy(page)
        result=self.validate(page)
        question=result['exercise']['questions'][0]
        self.assertEqual(question,{**original['exercise']['questions'][0],'id':'2'})
        self.assertEqual(result['visuals'][0]['question'],1)
        self.assertIn('2. Draw your own friendly pumpkin.',result['html'])
        self.assertIn('2. Accept an original',result['answers'])
        self.assertEqual(page,original)

    def test_repeated_closed_puzzle_action_is_not_renumbered_automatically(self):
        """A duplicate count/match question still requires a semantic correction."""
        for prompt in ['Count the pumpkins.','Draw lines to match the pumpkins.','Draw a circle on the correct pumpkin.',
                       'Write the number of pumpkins.']:
            page=self.exact(prompt)
            with self.subTest(prompt=prompt),self.assertRaisesRegex(ValueError,'reserved label 1'):
                self.validate(page)

    def test_ambiguous_question_ids_and_slots_are_not_rewritten(self):
        """Only one uniquely identified slot can move to the unused label."""
        for case in ['duplicate_id','duplicate_slot','missing_slot']:
            page=self.exact()
            if case=='duplicate_id': page['exercise']['questions'].append(deepcopy(page['exercise']['questions'][0]))
            elif case=='duplicate_slot': page['html']+='<div data-content="question_1"></div>'
            else: page['html']=page['html'].replace('question_1','question_9')
            before=deepcopy(page)
            with self.subTest(case=case):
                self.assertEqual(renumber_open_exact_question(page['exercise'],page['html']),before['html'])
                self.assertEqual(page,before)

    def test_nested_paragraph_copy_binds_complete_canonical_directions(self):
        """A pure text wrapper can bind as a whole instead of failing on nested p."""
        page=authored_page(); exercise=deepcopy(page['exercise'])
        page['html']=page['html'].replace('<p data-content="directions"></p>',
            '<div>Help a plant grow.<p>Invent a shelter that lets sunlight reach it.</p></div>')
        result=self.validate(page)
        self.assertEqual(result['html'].count(exercise['directions']),1)
        self.assertEqual(result['exercise'],exercise)

    def test_nested_extra_wording_and_work_panels_are_not_discarded(self):
        """Nested block support cannot consume a new instruction or blank workspace."""
        for body in ['<p>Now count the stars.</p>', '<div></div>',
                     '<div style="height:45mm"></div>',
                     '<p><img data-asset="scene" style="width:175mm;height:75mm"/></p>']:
            page=authored_page()
            page['html']=page['html'].replace('<p data-content="directions"></p>',
                '<div>'+page['exercise']['directions']+body+'</div>')
            with self.subTest(body=body),self.assertRaises(ValueError):
                self.validate(page)


if __name__=='__main__':
    unittest.main()
