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

    def test_names_rejected_property(self):
        """Feedback must identify the exact declaration the AI needs to correct."""
        with self.assertRaisesRegex(ValueError, 'Unsupported CSS property "position"'):
            clean_style('position:absolute')

    def test_resource_and_hidden_content_remain_blocked(self):
        """Background support never enables remote resources or invisible exercises."""
        for value in ['background:url(https://example.com/art.png)', 'display:none',
                      'margin-left:-10mm', 'overflow:hidden', 'font-family:var(--font)']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                clean_style(value)

    def test_malformed_declaration_is_actionable(self):
        """Syntax failures are distinguished from unsupported property names."""
        with self.assertRaisesRegex(ValueError, 'Malformed inline CSS'):
            clean_style('color')
