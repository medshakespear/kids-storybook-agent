"""Offline tests for illustrated worksheet assets and consolidated keys."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weasyprint import HTML
from core.activity_images import generate_activity_images
from core.activity_generator import validate_visuals
from core.activity_pdf import build_activity_html
from core.pipeline import load_grade_config
from tests.activity_fixtures import sample_pack, attach_test_art


class IllustrationTests(unittest.TestCase):
    """Check API request reuse, missing-art failures, and final-answer-page structure."""

    def setUp(self):
        """Load the real lower-grade configuration."""
        self.config = load_grade_config()['Pre-K-K']
        self.pack = sample_pack('Pre-K-K', self.config)

    def test_deduplicates_and_binds(self):
        """Repeated briefs share an image without losing per-item attachments."""
        with tempfile.TemporaryDirectory() as folder:
            attach_test_art(self.pack, folder)
            path = Path(folder) / 'test-plant.png'
            def fake_images(pack, config, directory):
                """Record each unique brief through the mocked image backend."""
                prompts = [p['image_prompt'] for p in pack['pages']]
                self.assertEqual(len(prompts), len(set(prompts)))
                self.assertEqual(pack['resource_type'], 'activity_pack')
                return [path] * len(prompts)
            with patch('core.activity_images.generate_images', side_effect=fake_images) as api:
                generate_activity_images(self.pack, self.config, folder)
            api.assert_called_once()
            self.assertEqual(self.pack['pages'][0]['items'][0]['art'], str(path))

    def test_missing_brief_and_failed_art_rejected(self):
        """Neither absent prompts nor an incomplete backend response is silently accepted."""
        del self.pack['pages'][0]['items'][0]['image_prompt']
        with self.assertRaises(ValueError):
            validate_visuals(self.pack)
        with self.assertRaises(ValueError):
            build_activity_html(self.pack, self.config)
        self.pack = sample_pack('Pre-K-K', self.config)
        with tempfile.TemporaryDirectory() as folder, patch('core.activity_images.generate_images', return_value=[]):
            with self.assertRaises(ValueError):
                generate_activity_images(self.pack, self.config, folder)

    def test_single_final_key_and_no_guide(self):
        """The final page contains every key and no teacher-guide pages are emitted."""
        with tempfile.TemporaryDirectory() as folder:
            attach_test_art(self.pack, folder)
            markup = build_activity_html(self.pack, self.config)
            self.assertNotIn('Your teaching plan', markup)
            self.assertNotIn('Teaching tip', markup)
            self.assertEqual(markup.count('class="sheet answer-sheet"'), 1)
            self.assertEqual(markup.count('class="key-block"'), len(self.pack['pages']))
            document = HTML(string=markup).render()
            self.assertEqual(len(document.pages), self.config["activity_pages"] + 2)

    def test_matching_picture_layout(self):
        """Four illustrated matching rows fit and answer letters reflect shuffling."""
        config = load_grade_config()['1st-2nd']
        pack = sample_pack('1st-2nd', config)
        page = pack['pages'][0]
        page.update(type='matching', items=[dict(left='Plant', right='Water') for _ in range(4)], answers=['Plant -> Water'] * 4)
        with tempfile.TemporaryDirectory() as folder:
            attach_test_art(pack, folder)
            markup = build_activity_html(pack, config)
            self.assertIn('1: D', markup)
            self.assertEqual(len(HTML(string=markup).render().pages), config["activity_pages"] + 2)
