"""Preserve substantial illustrations and response areas through dense reading-page recovery."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.creative_generator import ask_json, layout_contract, validate_design
from core.illustration_gallery import illustration_grid
from core.layout_recovery import layout_recovery_candidates, reading_panel_recovery
from core.pipeline import load_grade_config
from core.response_schemas import design_schema
from tests import test_landscape_layout_recovery as landscape_fixtures


class MultipleReadingRecoveryTests(unittest.TestCase):
    """Regress the overflow followed by two undersized 3344mm2 panels."""

    def page(self, count=2):
        """Create a dense reading task with every image declared and initially undersized."""
        page = landscape_fixtures.LandscapeRecoveryTests().dense_page()
        page['images'] = [dict(id=f'scene{i}', prompt='An original purposeful garden illustration without text.')
                          for i in range(count)]
        page['html'] = page['html'].replace('<img data-asset="scene" style="width:175mm;height:75mm"/>',
            ''.join(f'<img data-asset="scene{i}" style="width:76mm;height:44mm"/>' for i in range(count)))
        if count > 2:
            for question in page['exercise']['questions']:
                question['space_mm'] = 25
        return page

    def validate(self, page, band):
        """Measure real A4 page geometry, readability and meaningful artwork area."""
        return validate_design(page, 12, quality=load_grade_config()[band],
            expected_title='Garden Investigators', require_coherent=True)

    def test_dense_two_panel_page_fits_when_previous_candidates_overflow(self):
        """Keep both illustrations, all wording and both full-width 55mm response panels."""
        page = self.page()
        original = deepcopy(page)
        for band in ['3rd-4th', '5th-6th']:
            with self.subTest(band=band):
                candidates = list(layout_recovery_candidates(page, 12, load_grade_config()[band]['visual_area_mm2']))
                self.assertEqual(len(candidates), 3)
                for stacked in candidates[:2]:
                    with self.assertRaisesRegex(ValueError, 'Design overflow'):
                        self.validate(stacked, band)
                result = self.validate(candidates[2], band)
                self.assertEqual(result['exercise'], original['exercise'])
                self.assertEqual(result['images'], original['images'])
                self.assertEqual(result['html'].count('height:55mm'), 2)
                for image in page['images']:
                    self.assertEqual(result['source_layout'].count('data-asset="'+image['id']+'"'), 1)
        self.assertEqual(page, original)

    def test_grid_retains_three_and_four_substantial_panels(self):
        """All declared assets pass the existing collective visual-area and print checks."""
        for count in [3, 4]:
            for band in ['3rd-4th', '5th-6th']:
                with self.subTest(count=count, band=band):
                    page = self.page(count)
                    candidate = reading_panel_recovery(page, 12, load_grade_config()[band]['visual_area_mm2'])
                    result = self.validate(candidate, band)
                    self.assertEqual(result['images'], page['images'])
                    self.assertEqual(result['exercise'], page['exercise'])
                    self.assertEqual(result['html'].count('height:25mm'), 2)
                    for image in page['images']:
                        self.assertEqual(result['source_layout'].count('data-asset="'+image['id']+'"'), 1)

    def test_one_provider_response_recovers_the_complete_two_panel_page(self):
        """The production path uses measured reflow before another model design request."""
        page = self.page()
        api = Mock()
        api.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(page)), finish_reason='stop')])
        with patch('core.creative_generator.text_provider_names', return_value=['gemini']), \
             patch('core.creative_generator.text_client', return_value=(api, 'test')), \
             patch('core.creative_generator.time.sleep'):
            result = ask_json(layout_contract(12,12,coherent=True),
                lambda raw:self.validate(raw,'3rd-4th'),'Activity design 1',
                response_schema=design_schema(dict(render_mode='authored',mechanic='design shelter'),
                    load_grade_config()['3rd-4th']))
        self.assertEqual(api.chat.completions.create.call_count, 1)
        self.assertEqual(result['images'], page['images'])
        self.assertEqual(result['exercise'], page['exercise'])

    def test_untracked_work_or_wording_is_not_discarded(self):
        """The new gallery cannot hide independent student tasks to force page fit."""
        for extra in ['<div style="height:40mm"></div>', '<p>Write another explanation.</p>']:
            page = self.page()
            page['html'] += extra
            self.assertIsNone(reading_panel_recovery(page, 12, 8000))

    def test_grid_rejects_invalid_or_impossible_budgets(self):
        """Duplicate assets, unsafe IDs and dimensions exceeding the budget remain invalid."""
        for ids, area in [(['a','a'],8000), (['a','../b'],8000), (['a','b'],float('nan')),
                          (['a','b'],0), (['a','b'],100000)]:
            with self.assertRaises(ValueError):
                illustration_grid(ids, area)


if __name__ == '__main__':
    unittest.main()
