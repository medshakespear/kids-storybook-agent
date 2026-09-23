"""Regression cases for nowrap, table padding, and small printable-page overflows."""
import tempfile
import unittest
from pathlib import Path

from weasyprint import HTML
from core.creative_layout import clean_style, check_page, check_document, document_markup, fragment, data_only_fetcher
from core.creative_generator import validate_design
from tests.test_creative_design import design_fixture, attach_creative_test_art


def wide_page():
    """Represent a model-authored two-column activity with overcommitted widths."""
    return dict(title='Observation Challenge', answers='Accept a comparison supported by the observations.',
        images=[{'id': 'scene', 'prompt': 'An original potted plant.'}],
        html='<h2>Observation Challenge</h2><table style="width:100%;border-spacing:3mm"><tr>'
             '<td style="width:50%;padding:5mm"><div style="width:94mm;padding:4mm">'
             '<h4>Observe the plant</h4><img data-asset="scene" style="width:82mm;height:55mm"/>'
             '<p style="white-space:nowrap">Write one detail: _________________________________</p></div></td>'
             '<td style="width:50%;padding:5mm"><div style="width:94mm;padding:4mm">'
             '<h4>Explain your reasoning</h4><p>What would change if the plant received less light?</p>'
             '<div style="height:60mm;border:1mm solid #17a1a1">Use this space for your explanation.</div>'
             '</div></td></tr></table>')


class LayoutReflowTests(unittest.TestCase):
    """Local layout repairs keep content and readable typography intact."""

    def test_white_space_accepts_wrapping_and_normalizes_unbreakable_modes(self):
        """Common whitespace declarations no longer waste a generation attempt."""
        self.assertEqual(clean_style('white-space:nowrap'), 'white-space:normal')
        self.assertEqual(clean_style('white-space:pre'), 'white-space:pre-wrap')
        self.assertEqual(clean_style('white-space:pre-line'), 'white-space:pre-line')
        self.assertEqual(clean_style('white-space:break-spaces'), 'white-space:pre-wrap')
        with self.assertRaises(ValueError):
            clean_style('white-space:garbage')

    def test_width_reflow_fixes_real_overflow_and_survives_final_render(self):
        """The preview and actual PNG render use the same measured repair mode."""
        page = wide_page()
        original = HTML(string=document_markup([fragment(page, True)]), url_fetcher=data_only_fetcher).render()
        with self.assertRaises(ValueError):
            check_document(original, 1)
        fixed = validate_design(page, 13)
        self.assertIn(fixed['print_layout'], {'reflow', 'compact'})
        self.assertEqual(fixed['html'], page['html'])
        with tempfile.TemporaryDirectory() as folder:
            pack = {'cover': fixed, 'pages': []}
            attach_creative_test_art(pack, {}, folder)
            doc = HTML(string=document_markup([fragment(fixed)], 13), url_fetcher=data_only_fetcher).render()
            check_document(doc, 1)
            text = ' '.join(getattr(box, 'text', '') for box in doc.pages[0]._page_box.descendants())
            self.assertIn('What would change', text)
            self.assertIn('explanation', text)

    def test_cosmetic_compaction_fixes_pagination_without_shrinking_text(self):
        """Removing excess paragraph spacing retains every task at its original size."""
        page = design_fixture()
        page['html'] = '<img data-asset="scene" style="width:80mm;height:45mm"/>' + ''.join(
            f'<p style="font-size:14pt;margin-bottom:12mm">Question {i}: Explain your observation.</p>' for i in range(1, 15))
        fixed = validate_design(page, 14)
        self.assertEqual(fixed['print_layout'], 'compact')
        doc = HTML(string=document_markup([fragment(fixed, True)], 14), url_fetcher=data_only_fetcher).render()
        check_document(doc, 1)
        text_boxes = [box for box in doc.pages[0]._page_box.descendants() if getattr(box, 'text', '').startswith('Question')]
        self.assertEqual(len(text_boxes), 14)
        self.assertTrue(all(abs(box.style['font_size'] - 14 * 96 / 72) < .01 for box in text_boxes))

    def test_large_fixed_response_area_is_not_clipped_or_shrunk(self):
        """An impossible page still requires model reflow instead of losing content."""
        page = design_fixture()
        page['html'] += '<div style="height:300mm">Essential response area</div>'
        with self.assertRaises(ValueError):
            check_page(page, 15)
        self.assertNotIn('print_layout', page)
        self.assertIn('height:300mm', page['html'])
