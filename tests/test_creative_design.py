"""Offline checks for freeform AI design, rendering boundaries, and pipeline routing."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.creative_generator import ask_json, validate_design, generate_creative_pack, compact_answers
from core.creative_layout import check_page, build_creative_pdf, fragment
from core.pipeline import load_grade_config, generate_book
from tests.activity_fixtures import attach_test_art


def design_fixture(index=0):
    """Provide three different original compositions for renderer testing, not production."""
    layouts = [
        '<h1 style="color:#0b787a;background-color:#dff4ef;padding:4mm;border-radius:5mm">Garden Detectives</h1><p>Look at the plant. Invent a shelter that lets sunlight reach it.</p><img data-asset="scene" style="width:175mm;height:75mm"/><div style="border:1mm solid #efae32;border-radius:5mm;height:80mm;padding:4mm">Sketch your shelter here.</div><p>Explain one design choice: ____________________</p>',
        '<h1 style="color:#e56e44">Build a Garden Plan</h1><table style="border-spacing:4mm"><tr><td style="background-color:#e5f5f0;padding:3mm"><img data-asset="scene" style="width:65mm;height:70mm"/><p>This plant needs light and water.</p></td><td style="border:1mm solid #329298;padding:4mm"><h2>Your mission</h2><p>Design a path to reach your plants.</p><p>Leave room for watering.</p></td></tr></table><div style="height:95mm;border:1mm dashed #e8aa35;padding:3mm">Draw your garden map.</div>',
        '<h1 style="color:#38618b">A Plant Comic</h1><p>Draw what might happen next. Show how the gardener helps.</p><table style="border-spacing:3mm"><tr><td style="border:1mm solid #17a1a1;padding:3mm"><img data-asset="scene" style="width:74mm;height:68mm"/><p>1. A plant needs care.</p></td><td style="border:1mm solid #e58b53;padding:3mm;height:90mm"><p>2. Draw the next scene.</p></td></tr></table><div style="background-color:#e7f4fa;padding:4mm;height:60mm;border-radius:4mm"><h2>Tell your ending</h2><p>________________________________</p><p>________________________________</p></div>'
    ]
    return dict(html=layouts[index % 3], images=[dict(id='scene', prompt='An original potted plant on white.')], answers='Open-ended: accept a plan that provides sunlight, water and access.', title=f'Investigation {index+1}', page_number=index+1)


def creative_fixture(band='Pre-K-K'):
    """Build a complete pack with fixture artwork attached later by the test."""
    cfg = load_grade_config()[band]
    return dict(title='Garden Makers', overview='Investigate, invent and explain.', theme='Garden',
                grade_band=band, resource_type='activity_pack', character_description='Original garden objects.',
                art_direction='Teal, orange and yellow educational art.', design_engine='creative_html_v1',
                cover=cover_fixture(), pages=[design_fixture(i) for i in range(cfg['activity_pages'])])


def cover_fixture():
    """Provide a proper cover with reserved space for the real store logo."""
    return dict(html='<h1 style="color:#0b787a;text-align:center;font-size:30pt">Garden Makers</h1>'
                '<p style="text-align:center;color:#d56e44;font-size:17pt">Investigate • Invent • Explain</p>'
                '<img data-asset="scene" style="width:180mm;height:125mm"/>'
                '<p style="text-align:center;background-color:#dff4ef;padding:5mm">Creative classroom challenges</p>',
                images=[dict(id='scene', prompt='An original potted plant on white.')])


def attach_creative_test_art(pack, config, folder):
    """Use clearly synthetic plant artwork to test embedding without API calls."""
    stub = {'pages': []}
    attach_test_art(stub, folder)
    for page in [pack['cover'], *pack['pages']]:
        for asset in page['images']:
            asset['path'] = str(Path(folder) / 'test-plant.png')


class CreativeTests(unittest.TestCase):
    """Check custom compositions rather than fixed exercise templates."""

    def test_all_grades_and_layouts(self):
        """Three distinct freeform compositions print across all four grade bands."""
        for band, config in load_grade_config().items():
            with self.subTest(band=band), tempfile.TemporaryDirectory() as folder:
                pack = creative_fixture(band)
                for page in pack['pages']:
                    validate_design(page, config['student_font_pt'])
                attach_creative_test_art(pack, config, folder)
                self.assertTrue(build_creative_pdf(pack, config, Path(folder) / 'pack.pdf').is_file())

    def test_h4_and_long_answer_do_not_reject_valid_layout(self):
        """Common heading levels and long keys survive the design validation stage."""
        page = design_fixture()
        page['html'] = '<h4>Investigate and invent</h4>' + page['html']
        page['answers'] = ['1. Accept a shelter with access to sunlight. ' * 10]
        validated = validate_design(page, 15)
        self.assertGreater(len(validated['answers']), 300)
        with patch('core.creative_generator.ask_json', return_value={'answers': '1. A shelter with access to sunlight.'}) as request:
            fixed = compact_answers(validated, 3)
        request.assert_called_once()
        self.assertEqual(fixed['html'], validated['html'])
        self.assertEqual(fixed['images'], validated['images'])
        self.assertLessEqual(len(fixed['answers']), 300)

    def test_short_key_requires_no_extra_call(self):
        """Existing compact answers use no additional provider quota."""
        page = design_fixture()
        with patch('core.creative_generator.ask_json') as request:
            self.assertEqual(compact_answers(page, 1), page)
        request.assert_not_called()

    def test_reject_external_or_hidden_content(self):
        """AI markup cannot load files, fetch URLs, run scripts, or hide overflow."""
        for body in ['<script>bad()</script>', '<img src="file:///etc/passwd"/>',
                     '<div style="background-color:url(https://example.com)">x</div>',
                     '<p style="display:none">x</p>', '<p style="position:absolute">x</p>']:
            page = design_fixture()
            page['html'] = body
            with self.subTest(body=body), self.assertRaises(ValueError):
                fragment(page, preview=True)

    def test_overflow_rejected_before_image_spending(self):
        """An oversized page is sent for repair rather than silently clipped."""
        page = design_fixture()
        page['html'] += '<div style="height:300mm">Too much content</div>'
        with self.assertRaises(ValueError):
            check_page(page, 15)

    def test_pipeline_routes_creative_pack_and_cleans_paths(self):
        """Active cron/web pipeline embeds the new model-authored design format."""
        pack = creative_fixture()
        with tempfile.TemporaryDirectory() as folder, patch('core.pipeline.text_provider_names'), patch('core.pipeline.image_provider_name'), patch('core.pipeline.generate_activity_pack', return_value=pack), patch('core.pipeline.generate_activity_images', side_effect=attach_creative_test_art):
            result, path = generate_book(theme='Garden', grade_band='Pre-K-K', output_dir=folder)
            self.assertTrue(path.is_file())
            self.assertNotIn('path', result['pages'][0]['images'][0])

    def test_description_only_webhook(self):
        """Teachers can provide a creative brief without inventing a reference URL."""
        import webhook_server
        with patch.object(webhook_server, '_authorized', return_value=True), patch.object(webhook_server, 'generate_book', return_value=(creative_fixture(), Path('test.pdf'))) as generate, patch.object(webhook_server, 'register_book'):
            response = webhook_server.app.test_client().post('/generate', json={'description':'Create a colorful garden invention challenge.', 'grade_band':'Pre-K-K'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('garden invention', generate.call_args.kwargs['source_context'])

    def test_asset_mismatch_reports_both_sides(self):
        """A bad data-asset reference reports declared and referenced IDs in one validation error."""
        page = design_fixture()
        page['html'] = page['html'].replace('data-asset="scene"', 'data-asset="missing"')
        with self.assertRaisesRegex(ValueError, r'declared IDs \[scene\].*HTML data-asset IDs \[missing\]'):
            validate_design(page, 15)

    def test_cover_asset_mismatch_gets_cover_specific_repair(self):
        """A declared cover image with no matching img receives cover-specific repair guidance."""
        api = Mock()
        bad = cover_fixture()
        bad['images'] = [dict(id='cover_illustration', prompt='A bold original fire-safety illustration.')]
        bad['html'] = '<h1>Fire Prevention Week</h1><p>Grades 5-6</p>'
        good = cover_fixture()
        def response(value):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))])
        api.chat.completions.create.side_effect = [response(bad), response(good)]
        with patch('core.creative_generator.text_provider_names', return_value=['gemini']), patch(
                'core.creative_generator.text_client', return_value=(api, 'test')), patch(
                'core.creative_generator.time.sleep'):
            result = ask_json('Create a cover.', lambda raw: validate_design(raw, 15, cover=True), 'Cover design')
        self.assertEqual(result['images'][0]['id'], 'scene')
        repair = api.chat.completions.create.call_args_list[1].kwargs['messages'][-1]['content']
        self.assertIn('This is a COVER', repair)
        self.assertIn('Do not solve the mismatch by deleting the image element', repair)

    def test_asset_validation_gets_manifest_sync_repair(self):
        """Image-manifest failures receive exact instructions to synchronize HTML and images."""
        api = Mock()
        bad = design_fixture()
        bad['html'] = bad['html'].replace('data-asset="scene"', 'data-asset="missing"')
        good = design_fixture()
        def response(value):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))])
        api.chat.completions.create.side_effect = [response(bad), response(good)]
        with patch('core.creative_generator.text_provider_names', return_value=['gemini']), patch(
                'core.creative_generator.text_client', return_value=(api, 'test')), patch(
                'core.creative_generator.time.sleep'):
            result = ask_json('Create one activity.', lambda raw: validate_design(raw, 15), 'Activity design 2')
        self.assertEqual(result['images'][0]['id'], 'scene')
        repair = api.chat.completions.create.call_args_list[1].kwargs['messages'][-1]['content']
        self.assertIn('Repair the image manifest and HTML together', repair)
        self.assertIn('synchronize images[].id and every data-asset reference', repair)

    def test_page_retry_keeps_plan_and_completed_designs(self):
        """An invalid layout repairs only that page while preserving prior creative work."""
        config = load_grade_config()
        config['Pre-K-K']['activity_pages'] = 2
        plan = dict(title='Garden Makers', overview='Make and investigate.', art_direction='Teal and coral, clear outlines.',
                    character_description='Original friendly gardening objects.', cover_brief='Big plant and cheerful title.',
                    pages=[dict(title=f'Mission {i}', learning_goal='Explain a design.', activity_concept=f'Original challenge {i}', layout_brief=f'Composition {i}') for i in range(2)])
        invalid = design_fixture(1)
        invalid['html'] = '<script>bad()</script>'
        api = Mock()
        def response(value):
            """Wrap fixture JSON as a chat completion without contacting a provider."""
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))])
        api.chat.completions.create.side_effect = [response(plan), response(cover_fixture()),
                                                  response(design_fixture(1)), response(invalid), response(design_fixture(2))]
        with patch.dict(os.environ, {'DESIGN_WORKERS': '1'}), patch('core.creative_generator.text_provider_names', return_value=['gemini']), patch('core.creative_generator.text_client', return_value=(api, 'test')), patch('core.creative_generator.time.sleep'):
            pack = generate_creative_pack('Garden', 'Pre-K-K', config, source_context='Invent a garden tool.')
        self.assertEqual(pack['pages'][0]['html'], design_fixture(1)['html'])
        self.assertEqual(pack['pages'][1]['html'], design_fixture(2)['html'])
        self.assertEqual(api.chat.completions.create.call_count, 5)
        self.assertEqual(pack['design_engine'], 'creative_html_v1')
