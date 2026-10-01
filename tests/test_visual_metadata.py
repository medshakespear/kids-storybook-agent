"""Normalize harmless puzzle formatting without inventing missing metadata."""
import copy
import unittest

from core.creative_generator import validate_design
from core.pipeline import load_grade_config
from core.task_visuals import normalize_visual_metadata, page_visuals, VISUAL_CONTRACT
from tests.test_exercise_quality import exact_page, visual_fixtures


class VisualMetadataTests(unittest.TestCase):
    """HTML references and exact answer keys retain a single unambiguous identity."""

    def test_string_number_and_display_id_are_normalized_together(self):
        """A string integer and cosmetic capitalization/spacing cost no model retry."""
        page=exact_page(copy.deepcopy(visual_fixtures()[0]))
        page['visuals'][0].update(id='Sort Cards',question=' 1 ')
        page['html']=page['html'].replace('data-visual="sorting"','data-visual="Sort Cards"')
        fixed=validate_design(page,14,quality=load_grade_config()['1st-2nd'])
        self.assertEqual(fixed['visuals'][0]['id'],'sort_cards')
        self.assertEqual(fixed['visuals'][0]['question'],1)
        self.assertIn('data-visual="sort_cards"',fixed['html'])
        self.assertEqual(page['visuals'][0]['id'],'Sort Cards')
        self.assertEqual(page['visuals'][0]['question'],' 1 ')
        self.assertEqual(set(page_visuals(fixed)),{'sort_cards'})

    def test_missing_values_are_not_invented(self):
        """Missing IDs or numbering require the model to identify the intended task."""
        for field in ['id','question']:
            page=exact_page(copy.deepcopy(visual_fixtures()[0]))
            del page['visuals'][0][field]
            with self.subTest(field=field),self.assertRaises(ValueError):
                validate_design(page,14,quality=load_grade_config()['1st-2nd'])
            self.assertNotIn(field,page['visuals'][0])

    def test_ambiguous_ids_and_invalid_numbers_are_rejected(self):
        """Normalization cannot merge puzzles or treat floats and booleans as task numbers."""
        page=exact_page(copy.deepcopy(visual_fixtures()[0]))
        page['visuals'][0]['id']='Sort Cards'
        page['visuals'].append(dict(page['visuals'][0],id='sort-cards',question=2))
        with self.assertRaisesRegex(ValueError,'collide'):
            normalize_visual_metadata(page)
        for number in [0,31,True,1.5,'Q1','1.0',None]:
            page=exact_page(copy.deepcopy(visual_fixtures()[0]))
            page['visuals'][0]['question']=number
            with self.subTest(number=number),self.assertRaisesRegex(ValueError,'Visual question'):
                validate_design(page,14,quality=load_grade_config()['1st-2nd'])

    def test_contract_specifies_json_types_and_reference_example(self):
        """Initial drafting sees the same integer and ID rules as strict validation."""
        self.assertIn('JSON INTEGER 1-30',VISUAL_CONTRACT)
        self.assertIn('"id":"trail","question":1',VISUAL_CONTRACT)
