"""Regression checks proving images reach PDFs without any AI approval step."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from core.creative_generator import generate_creative_images
from core.image_review import ImageFileError, validate_image_files
from core.pipeline import generate_book, load_grade_config
from tests.test_creative_design import creative_fixture


class ImageFileTests(unittest.TestCase):
    """Keep file integrity checks while eliminating semantic approval failures."""

    def setUp(self):
        """Create a real, local PNG fixture."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'asset.png'
        Image.new('RGB', (300, 300), 'teal').save(self.path)

    def test_files_checked_without_text_provider(self):
        """The illustration stage never calls Gemini, including with old variables."""
        import os
        pack = creative_fixture()
        with patch.dict(os.environ, {'REVIEW_WORKERS': 'bad', 'IMAGE_REPAIR_ATTEMPTS': 'bad'}), patch(
                'core.creative_generator.generate_images', return_value=[self.path]) as generate, patch(
                'core.providers.text_client', side_effect=AssertionError('No image review allowed')) as text:
            generate_creative_images(pack, load_grade_config()['Pre-K-K'], self.temp.name)
        generate.assert_called_once()
        text.assert_not_called()
        self.assertEqual(pack['image_review'], {'status': 'disabled', 'checked': 0, 'regenerated': 0})
        self.assertEqual(pack['image_validation']['checked'], 1)
        self.assertTrue(all(page['images'][0]['path'] == str(self.path)
                            for page in [pack['cover'], *pack['pages']]))

    def test_invalid_file_sets_fail_locally(self):
        """Missing, corrupt, duplicate, tiny and incomplete files still fail clearly."""
        broken = Path(self.temp.name) / 'broken.png'
        broken.write_bytes(b'not an image')
        tiny = Path(self.temp.name) / 'tiny.png'
        Image.new('RGB', (10, 10)).save(tiny)
        for paths, count in [([], 1), ([broken], 1), ([tiny], 1),
                             ([self.path, self.path], 2), ([None], 1),
                             ([Path(self.temp.name) / 'missing.png'], 1)]:
            with self.subTest(paths=paths), self.assertRaises(ImageFileError):
                validate_image_files(paths, count)

    def test_all_grades_finish_real_pdfs_without_reviewer(self):
        """Exercise image-binding, integrity and PDF generation for both active bands."""
        for band, config in load_grade_config().items():
            if band not in {"3rd-4th", "5th-6th"}:
                continue
            with self.subTest(band=band), patch('core.pipeline.text_provider_names'), patch(
                    'core.pipeline.image_provider_name'), patch(
                    'core.pipeline.generate_activity_pack', return_value=creative_fixture(band)), patch(
                    'core.creative_generator.generate_images', return_value=[self.path]), patch(
                    'core.providers.text_client', side_effect=AssertionError('No vision calls')):
                pack, pdf = generate_book(theme='Garden', grade_band=band, output_dir=self.temp.name)
                self.assertTrue(pdf.read_bytes().startswith(b'%PDF'))
                self.assertEqual(pack['page_count'], config['activity_pages'] + 2)
                self.assertEqual(pack['image_review']['status'], 'disabled')
                self.assertEqual(pack['image_validation']['method'], 'local_file_decode')
                self.assertNotIn('path', pack['pages'][0]['images'][0])

    def test_bad_file_prevents_pdf_publication(self):
        """A broken download cannot become an apparently successful PDF."""
        with patch('core.pipeline.text_provider_names'), patch('core.pipeline.image_provider_name'), patch(
                'core.pipeline.generate_activity_pack', return_value=creative_fixture('3rd-4th')), patch(
                'core.creative_generator.generate_images', return_value=[self.path.with_name('missing.png')]), patch(
                'core.pipeline.build_activity_pdf') as render:
            with self.assertRaises(ImageFileError):
                generate_book(theme='Garden', grade_band='3rd-4th', output_dir=self.temp.name)
        render.assert_not_called()
