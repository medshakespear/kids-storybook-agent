"""Recover equivalent asset spelling and precisely diagnose actual illustration mismatch."""
import json
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.creative_generator import ask_json, layout_contract, validate_design
from core.pipeline import load_grade_config
from tests.coherent_fixtures import authored_page


class IllustrationReferenceTests(unittest.TestCase):
    """Keep purposeful artwork identity and never guess between different subjects."""

    def validate(self,page):
        """Exercise real shared-content binding and young-reader print checks."""
        return validate_design(page,14,quality=load_grade_config()['1st-2nd'],
                               expected_title='Garden Inventors',require_coherent=True)

    def test_equivalent_quoted_and_unquoted_ids_normalize_locally(self):
        """Case, whitespace and hyphen differences retain the same declared asset."""
        for reference in ['" Scene-Art "',"'SCENE ART'",'Scene-Art']:
            with self.subTest(reference=reference):
                page=authored_page();page['images'][0]['id']='Scene Art'
                page['html']=page['html'].replace('data-asset="scene"','data-asset='+reference)
                original=deepcopy(page)
                result=self.validate(page)
                self.assertEqual(result['images'][0]['id'],'scene_art')
                self.assertEqual(result['images'][0]['prompt'],page['images'][0]['prompt'])
                self.assertIn('data-asset="scene_art"',result['html'])
                self.assertEqual(page,original)

    def test_different_subject_id_is_not_rebound_by_position(self):
        """An owl reference must not silently become the only declared plant image."""
        page=authored_page();page['html']=page['html'].replace('data-asset="scene"','data-asset="owl"')
        with self.assertRaises(ValueError) as raised:
            self.validate(page)
        self.assertIn("missing HTML data-asset IDs ['scene']",str(raised.exception))
        self.assertIn("undeclared HTML IDs ['owl']",str(raised.exception))

    def test_repeated_reference_has_id_and_occurrence_count(self):
        """Accidental repeats get precise feedback instead of a generic media failure."""
        page=authored_page();page['html']+='<img data-asset="scene" style="width:10mm;height:10mm"/>'
        with self.assertRaises(ValueError) as raised:
            self.validate(page)
        self.assertIn("repeated HTML IDs/counts {'scene': 2}",str(raised.exception))

    def test_normalization_collision_preserves_distinct_subjects(self):
        """Two distinct prompts cannot be merged because their names normalize alike."""
        page=authored_page();page['images']=[dict(id='Scene-Art',prompt='A plant.'),dict(id='scene art',prompt='An owl.')]
        with self.assertRaisesRegex(ValueError,'collide after normalization'):
            self.validate(page)

    def test_invalid_manifest_id_reports_illustration_metadata(self):
        """Invalid or non-text IDs fail clearly instead of raising an unhashable-type error."""
        for value in [None,[],12,'../scene']:
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'Illustration ID'):
                page=authored_page();page['images'][0]['id']=value
                self.validate(page)

    def test_repair_feedback_covers_all_reference_classes_in_current_schema(self):
        """The exact reported diagnostic receives a subject-preserving repair instruction."""
        bad=authored_page();bad['html']=bad['html'].replace('data-asset="scene"','data-asset="owl"')
        good=authored_page();api=Mock()
        def response(page):
            """Supply complete mocked JSON responses without provider credentials."""
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(page)),finish_reason='stop')])
        api.chat.completions.create.side_effect=[response(bad),response(good)]
        with patch('core.creative_generator.text_provider_names',return_value=['gemini']), \
             patch('core.creative_generator.text_client',return_value=(api,'test')), \
             patch('core.creative_generator.time.sleep'):
            result=ask_json(layout_contract(14,13,coherent=True),self.validate,'Activity design 2')
        repair=api.chat.completions.create.call_args.kwargs['messages'][-1]['content']
        self.assertIn('For missing HTML IDs',repair)
        self.assertIn('For undeclared HTML IDs',repair)
        self.assertIn('For repeated IDs',repair)
        self.assertIn('never reuse an unrelated picture',repair)
        self.assertIn('Return ONLY html, images and exercise',repair)
        self.assertEqual(result['images'],good['images'])
        self.assertEqual(result['exercise'],good['exercise'])
