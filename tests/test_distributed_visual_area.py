"""Regression checks for substantial multi-panel classroom illustrations."""
import base64
import unittest
from weasyprint import HTML
from core.visual_area import sufficient_visual_area
from core.creative_layout import check_visual_quality, check_document, document_markup
from core.small_overflow import recover_small_overflow
import tests.test_upper_grade_recovery as upper_recovery


class DistributedVisualAreaTests(unittest.TestCase):
    """Accept useful panel compositions without admitting tiny art or shrinking text."""
    def render(self, height=30, font=13):
        """Render four purposeful comparison panels and a large student response area."""
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="orange"/></svg>'
        uri = 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode()
        image = f'<img src="{uri}" style="width:87mm;height:{height}mm"/>'
        rows = ''.join('<tr><td>'+image+'</td><td>'+image+'</td></tr>' for _ in range(2))
        markup = f'<p style="font-size:{font}pt">Compare the four scenes. Explain your choice.</p><table style="border-spacing:0"><tbody>{rows}</tbody></table><div style="height:45mm;border:1pt solid black"></div>'
        return HTML(string=document_markup([markup],font)).render()

    def test_reported_panel_areas_meet_quality_without_a_dominant_image(self):
        """All three logged artwork totals pass as four substantial panels."""
        for area in (10150,11400,15300):
            self.assertTrue(sufficient_visual_area([area/4]*4,10000))

    def test_rendered_four_panel_page_fits_and_meets_visual_floor(self):
        """Actual WeasyPrint geometry passes with artwork, readable text and response space."""
        document = self.render()
        check_document(document,1)
        check_visual_quality(document,{'visual_area_mm2':10000,'minimum_text_pt':13})

    def test_small_panels_and_icon_collections_still_fail(self):
        """An adequate total cannot disguise a tiny panel or many small icons."""
        for areas in ([2000]*4,[4000,4000,1900,100],[2000]*5,[]):
            self.assertFalse(sufficient_visual_area(areas,10000))
        with self.assertRaisesRegex(ValueError,'Visuals are too small'):
            check_visual_quality(self.render(10),{'visual_area_mm2':10000,'minimum_text_pt':13})

    def test_font_and_pagination_checks_still_apply(self):
        """Distributed artwork does not bypass student font floors or page bounds."""
        with self.assertRaisesRegex(ValueError,'Student text is too small'):
            check_visual_quality(self.render(font=11),{'visual_area_mm2':10000,'minimum_text_pt':13})
        with self.assertRaises(ValueError):
            check_document(self.render(height=150),1)

    def test_small_spill_recovery_uses_same_panel_floor(self):
        """A modest art adjustment retains all four panels and the original workspace."""
        markup=''.join(f'<img data-asset="panel{i}" style="width:70mm;height:40mm"/>' for i in range(4))+'<div style="height:45mm"></div>'
        candidate = recover_small_overflow(markup,upper_recovery.UpperGradeRecoveryTests().document(),{'visual_area_mm2':10000})
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.count('data-asset='),4)
        self.assertIn('<div style="height:45mm"></div>',candidate)
