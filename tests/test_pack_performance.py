"""Check concurrency and page/branding contracts without timing live providers."""
import base64
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from weasyprint import HTML
from core.creative_generator import generate_creative_pack
from core.creative_layout import pack_markup, check_document, data_only_fetcher
from core.image_generator import generate_images
from core.pipeline import load_grade_config
from core.runtime import ordered_parallel
from tests.test_creative_design import creative_fixture, cover_fixture, design_fixture
from tests.coherent_fixtures import authored_page
from tests.test_key_rotation import SLOTS, image_response
from tests.test_providers import STORY, CONFIG


class PackPerformanceTests(unittest.TestCase):
    """Prove independent work overlaps while output order remains stable."""

    def test_ordered_parallel_really_overlaps(self):
        """A three-party barrier cannot pass if tasks are secretly sequential."""
        barrier = threading.Barrier(3)
        def task(number):
            """Wait for all workers, then return an ordering-sensitive result."""
            barrier.wait(timeout=5)
            return number * 2
        self.assertEqual(ordered_parallel(task, [3, 1, 2], 3), [6, 2, 4])

    def test_image_calls_overlap_and_paths_stay_in_page_order(self):
        """Three independent HTTP image calls run together with stable file ordering."""
        barrier = threading.Barrier(3)
        data = base64.b64decode(image_response().json()['result']['image'])
        def generate(prompt):
            """Synchronize fake image requests instead of measuring elapsed time."""
            barrier.wait(timeout=5)
            return data
        story = dict(STORY, pages=[dict(STORY['pages'][0], page_number=i) for i in (3, 1, 2)])
        with patch.dict(os.environ, {**SLOTS, 'IMAGE_WORKERS': '3'}, clear=True), patch('core.image_generator._cloudflare_image', side_effect=generate), tempfile.TemporaryDirectory() as folder:
            paths = generate_images(story, CONFIG, folder)
            self.assertEqual([path.name for path in paths], ['page_03.png', 'page_01.png', 'page_02.png'])
            self.assertTrue(all(path.is_file() for path in paths))

    def test_designs_overlap_without_reordering_activities(self):
        """One plan is followed by nine designs in three concurrent waves."""
        barrier = threading.Barrier(3)
        config = load_grade_config()
        plan = dict(title='Garden Makers', overview='Make and investigate.', art_direction='Teal and coral.',
                    character_description='Original garden objects.', cover_brief='A friendly garden.',
                    pages=[dict(title=f'Mission {i}', learning_goal='Design.', activity_concept=f'Challenge {i}',
                                layout_brief=f'Layout {i}', render_mode='authored', mechanic=f'challenge {i}') for i in range(1, 9)])
        def ask(prompt, validate, label, *args, **kwargs):
            """Use actual page validation, but emulate provider overlap deterministically."""
            if label == 'Creative plan':
                return validate(plan)
            if label == 'Exercise proofreading':
                return validate({'pages':[{'page_number':i,'issues':[]} for i in range(1,9)]})
            barrier.wait(timeout=5)
            if label == 'Cover design':
                return validate(cover_fixture())
            page = authored_page(mechanic='challenge '+label.split()[-1])
            return validate(page)
        with patch.dict(os.environ, {'DESIGN_WORKERS': '3'}), patch('core.creative_generator.ask_json', side_effect=ask), patch('core.creative_generator.text_worker_limit', return_value=3):
            pack = generate_creative_pack('Garden', 'Pre-K-K', config)
        self.assertEqual([p['page_number'] for p in pack['pages']], list(range(1, 9)))

    def test_all_grades_have_ten_or_twelve_pages_with_one_logo(self):
        """Branding and one final key fit without shrinking or adding pages."""
        for band, config in load_grade_config().items():
            with self.subTest(band=band):
                expected = 10 if band in {'Pre-K-K', '1st-2nd'} else 12
                pack = creative_fixture(band)
                markup = pack_markup(pack, config, preview=True)
                self.assertEqual(markup.count('class="store-logo"'), 1)
                self.assertEqual(markup.count('<h1>Answer Key</h1>'), 1)
                self.assertEqual(len(pack['pages']) + 2, expected)
                check_document(HTML(string=markup, url_fetcher=data_only_fetcher).render(), expected)

    def test_logo_is_the_unmodified_uploaded_file(self):
        """The committed logo matches the original image bytes exactly."""
        import hashlib
        data = Path('assets/store-logo.png').read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), '06eb1d8a8fdcc320144c6de4549bc82f8042064f4012d0cf09ce9f85777afaa7')
