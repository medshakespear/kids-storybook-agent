"""Fit an oversized illustration without shortening exercises or student work areas."""
from copy import deepcopy
import unittest

from core.creative_generator import validate_design
from core.pipeline import load_grade_config
from core.small_overflow import recover_paginated_art
from tests.coherent_fixtures import authored_page


class PaginatedArtRecoveryTests(unittest.TestCase):
    """Measure actual A4 pagination and visual area for both active grades."""

    def test_large_art_spill_fits_with_all_text_and_response_space(self):
        """Reduce only the 210mm image height while retaining the same asset and task."""
        for band in ('3rd-4th','5th-6th'):
            with self.subTest(band=band):
                config=dict(load_grade_config()[band],purposeful_activity_layout=False,
                    stimulus_limit=8,context_caption_limit=24,items_per_page=2)
                page=authored_page();page['html']=page['html'].replace('height:75mm','height:210mm')
                original=deepcopy(page)
                result=validate_design(page,config['student_font_pt'],quality=config,
                    expected_title='Garden Design',require_coherent=True)
                self.assertEqual(result['exercise']['questions'],original['exercise']['questions'])
                self.assertEqual(result['images'],original['images'])
                self.assertIn('height:45mm',result['html'])
                self.assertNotIn('height:210mm',result['html'])
                self.assertIn(original['exercise']['directions'],result['html'])
                self.assertEqual(page,original)

    def test_no_art_cannot_force_overfull_response_areas_to_fit(self):
        """Keep failure when shrinking art cannot leave sufficient space for student work."""
        config=dict(load_grade_config()['3rd-4th'],purposeful_activity_layout=False,stimulus_limit=8)
        page=authored_page();page['html']+='<div style="height:260mm;border:0.4mm solid #167E80"></div>'
        with self.assertRaisesRegex(ValueError,'Design overflow'):
            validate_design(page,config['student_font_pt'],quality=config,
                expected_title='Garden Design',require_coherent=True)

    def test_computed_diagrams_are_not_shrunk(self):
        """A multi-page spill cannot lower exact SVG label sizes."""
        from types import SimpleNamespace
        doc=SimpleNamespace(pages=[None,None])
        self.assertIsNone(recover_paginated_art('<img data-visual="maze" style="width:175mm;height:210mm"/>',
            doc,{'visual_area_mm2':8000}))
