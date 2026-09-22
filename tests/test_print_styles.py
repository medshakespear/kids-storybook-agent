"""Regression tests for harmless cover styles previously rejected by the allowlist."""
import unittest
from core.creative_layout import clean_style


class PrintStyleTests(unittest.TestCase):
    """Keep useful design styles while retaining resource and hidden-content checks."""

    def test_common_cover_styles(self):
        """Accept backgrounds, typography, sizing, and ordinary border resets."""
        result = clean_style('background:linear-gradient(135deg, #fff, #e7f4fa);font-family:DejaVu Sans,sans-serif;box-sizing:border-box;text-transform:uppercase;border:none;object-fit:contain;color:#123456 !important')
        self.assertIn('linear-gradient', result)
        self.assertIn('border:none', result)
        self.assertNotIn('!important', result)

    def test_font_units_normalized_before_layout(self):
        """Common browser sizes become readable print points without API retries."""
        self.assertEqual(clean_style('font-size:24px'), 'font-size:18pt')
        self.assertEqual(clean_style('font-size:9pt'), 'font-size:11pt')
        self.assertEqual(clean_style('font-size:56pt'), 'font-size:40pt')
        with self.assertRaisesRegex(ValueError, 'positive pt or px'):
            clean_style('font-size:2em')

    def test_overflow_reports_element_direction_and_distance(self):
        """A layout repair receives measured guidance rather than a generic failure."""
        from weasyprint import HTML
        from core.creative_layout import document_markup, check_document
        doc = HTML(string=document_markup(['<div style="width:210mm">Too wide</div>'])).render()
        with self.assertRaisesRegex(ValueError, r'<div>: right overflow 24.0mm'):
            check_document(doc, 1)

    def test_names_rejected_property(self):
        """Feedback must identify the exact declaration the AI needs to correct."""
        with self.assertRaisesRegex(ValueError, 'Unsupported CSS property "position"'):
            clean_style('position:absolute')

    def test_resource_and_hidden_content_remain_blocked(self):
        """Background support never enables remote resources or invisible exercises."""
        for value in ['background:url(https://example.com/art.png)', 'display:none',
                      'width:-10mm', 'overflow:hidden', 'font-family:var(--font)']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                clean_style(value)

    def test_negative_angles_and_cosmetic_spacing(self):
        """Negative gradient angles are valid; spacing is normalized before measuring."""
        self.assertIn('-45deg', clean_style('background:linear-gradient(-45deg, #fff, #abcdef)'))
        self.assertEqual(clean_style('margin:-2mm 4mm;letter-spacing:-0.5pt'), 'margin:0 4mm;letter-spacing:0')
        self.assertEqual(clean_style('border-style:hidden'), 'border-style:hidden')

    def test_negative_size_error_names_the_declaration(self):
        """Remaining rejections tell the model precisely which value to repair."""
        with self.assertRaisesRegex(ValueError, 'CSS height:-20mm has a negative size'):
            clean_style('height:-20mm')
        with self.assertRaisesRegex(ValueError, 'display:none hides'):
            clean_style('display:none')

    def test_malformed_declaration_is_actionable(self):
        """Syntax failures are distinguished from unsupported property names."""
        with self.assertRaisesRegex(ValueError, 'Malformed inline CSS'):
            clean_style('color')
