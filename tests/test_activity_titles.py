"""Printed activity titles tolerate typographic differences but not missing headings."""
import copy
import unittest

from core.creative_generator import validate_plan
from core.exercise_quality import validate_exercises, activity_title
from core.pipeline import load_grade_config
from tests.test_exercise_quality import exact_page, visual_fixtures


class ActivityTitleTests(unittest.TestCase):
    """Numbering is separate from the matching worksheet and answer-key title."""

    def test_page_label_is_optional_in_printed_title(self):
        """The reported pottery title passes when Page 4 is printed separately or omitted."""
        page=exact_page(copy.deepcopy(visual_fixtures()[0]))
        page['html']=page['html'].replace('Harvest Sort','Patterns in Traditional Pottery')
        validate_exercises(page,load_grade_config()['1st-2nd'],
                           'Page 4: Patterns in Traditional Pottery')
        self.assertEqual(activity_title('Activity 4 — Patterns in Traditional Pottery'),
                         'Patterns in Traditional Pottery')

    def test_visible_typography_does_not_change_title_identity(self):
        """Styled spans, ampersands and typographic punctuation keep the same title words."""
        page=exact_page(copy.deepcopy(visual_fixtures()[0]))
        page['html']=page['html'].replace('Harvest Sort','Pottery &amp; <strong>Patterns</strong> — Today!')
        validate_exercises(page,{},'Page 4: Pottery and Patterns: Today')
        with self.assertRaisesRegex(ValueError,'exact planned'):
            validate_exercises(page,{},'Pottery and Patterns: Tomorrow')

    def test_artwork_brief_cannot_satisfy_printed_heading(self):
        """A title mentioned only in an illustration prompt is not visible student text."""
        page=exact_page(copy.deepcopy(visual_fixtures()[0]))
        page['images']=[dict(id='art',prompt='Patterns in Traditional Pottery')]
        page['html']+='<img data-asset="art" style="width:100mm;height:60mm"/>'
        with self.assertRaisesRegex(ValueError,'Put it visibly'):
            validate_exercises(page,{},'Patterns in Traditional Pottery')

    def test_plan_titles_store_no_page_prefix_and_remain_distinct(self):
        """Page prefixes cannot disguise identical activity titles in the plan."""
        plan=dict(title='Pottery Study',overview='Original exploration',art_direction='Teal and warm orange',
                  character_description='Original objects',cover_brief='An original pottery scene',pages=[
                      dict(title='Page 1: Pattern Hunt',learning_goal='Compare shapes',activity_concept='Find a pattern',layout_brief='A large scene'),
                      dict(title='Activity 2: Design Studio',learning_goal='Invent a pattern',activity_concept='Design a pattern',layout_brief='Open drawing panels')])
        result=validate_plan(plan,2)
        self.assertEqual([p['title'] for p in result['pages']],['Pattern Hunt','Design Studio'])
        plan['pages'][1]['title']='Page 2: Pattern Hunt'
        with self.assertRaisesRegex(ValueError,'different title'):
            validate_plan(plan,2)
