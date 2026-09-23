"""Review actual image inputs, selective repairs, and refusal to publish unchecked art."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.image_review import ImageReviewError, _generation_repair_prompt, review_batch, review_and_repair_images, validate_reviews
from core.image_generator import _image_prompt
from core.creative_generator import generate_creative_images
from core.pipeline import generate_book, load_grade_config
from tests.test_creative_design import creative_fixture, attach_creative_test_art


def verdict(approved=True):
    """Return a complete, synthetic reviewer verdict for routing tests."""
    return {'approved': approved, 'issues': [] if approved else ['Missing the required watering can.'],
            'replacement_prompt': '' if approved else 'A potted plant next to one clearly visible watering can on white.'}


class VisualReviewTests(unittest.TestCase):
    """Prove that image pixels and task context are reviewed, not just the prompts."""

    def setUp(self):
        """Create deterministic local artwork without a provider call."""
        self.folder = self.enterContext(tempfile.TemporaryDirectory())
        self.pack = creative_fixture()
        self.config = load_grade_config()['Pre-K-K']
        attach_creative_test_art(self.pack, self.config, self.folder)
        self.images = [{'page_number': i, 'image_prompt': f'Original requirement {i}',
                        'contexts': [{'page_number': i, 'asset_id_on_page': 'plant', 'worksheet_html': '<p>Which plant needs water?</p>', 'answers': 'The dry plant.'}]}
                       for i in (1, 2)]
        data = (Path(self.folder) / 'test-plant.png').read_bytes()
        self.paths = [Path(self.folder) / f'page_{i:02d}.png' for i in (1, 2)]
        for path in self.paths:
            path.write_bytes(data)

    def test_actual_pixels_and_context_sent_and_client_closed(self):
        """Each image is transmitted as inline PNG with its original worksheet uses."""
        api = Mock()
        raw = {'reviews': [dict(image_id=i, **verdict()) for i in (1, 2)]}
        api.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(raw)), finish_reason='stop')])
        with patch('core.image_review.text_provider_names', return_value=['gemini']), patch('core.image_review.text_client', return_value=(api, 'test')):
            result = review_batch(self.pack, self.images, dict(zip((1, 2), self.paths)))
        self.assertEqual(set(result), {1, 2})
        content = api.chat.completions.create.call_args.kwargs['messages'][0]['content']
        pictures = [part for part in content if part['type'] == 'image_url']
        self.assertEqual(len(pictures), 2)
        self.assertTrue(all(p['image_url']['url'].startswith('data:image/png;base64,iVBOR') for p in pictures))
        self.assertIn('The dry plant', str(content))
        api.close.assert_called_once()

    def test_invalid_or_missing_verdicts_never_count_as_approval(self):
        """Missing IDs, duplicate IDs, string booleans, and conflicting verdicts fail."""
        cases = [[], [dict(image_id=1, **verdict())],
                 [dict(image_id=1, **verdict()), dict(image_id=1, **verdict())],
                 [dict(image_id=1, approved='true', issues=[]), dict(image_id=2, **verdict())],
                 [dict(image_id=1, approved=True, issues=['Wrong object']), dict(image_id=2, **verdict())]]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                validate_reviews({'reviews': rows}, {1, 2})

    def test_repair_only_rejected_asset_then_check_original_requirements(self):
        """Approved files are retained and the retry is judged against the original task."""
        approved_bytes = self.paths[0].read_bytes()
        with patch('core.image_review.review_batch', side_effect=[{1: verdict(), 2: verdict(False)}, {2: verdict()}]) as review, patch('core.image_review.generate_images', return_value=[self.paths[1]]) as generate:
            summary = review_and_repair_images(self.pack, self.config, self.images, self.paths, self.folder)
        self.assertEqual(summary['regenerated'], 1)
        self.assertEqual(summary['checked'], 2)
        self.assertEqual(summary['status'], 'passed')
        requested = generate.call_args.args[0]['pages']
        self.assertEqual([p['page_number'] for p in requested], [2])
        self.assertIn('watering can', requested[0]['image_prompt'])
        self.assertEqual(review.call_args_list[1].args[1][0]['image_prompt'], 'Original requirement 2')
        self.assertEqual(self.paths[0].read_bytes(), approved_bytes)

    def test_repeated_rejection_or_incomplete_repair_stops(self):
        """There is exactly one regeneration round, and no silent acceptance."""
        with patch.dict(os.environ, {'IMAGE_REPAIR_ATTEMPTS': '1'}), patch('core.image_review.review_batch', side_effect=[{1: verdict(False), 2: verdict()}, {1: verdict(False)}]), patch('core.image_review.generate_images', return_value=[self.paths[0]]) as generate:
            with self.assertRaisesRegex(ImageReviewError, 'still failed'):
                review_and_repair_images(self.pack, self.config, self.images, self.paths, self.folder)
            generate.assert_called_once()
        with patch('core.image_review.review_batch', return_value={1: verdict(False), 2: verdict()}), patch('core.image_review.generate_images', return_value=[]):
            with self.assertRaisesRegex(ImageReviewError, 'incomplete'):
                review_and_repair_images(self.pack, self.config, self.images, self.paths, self.folder)

    def test_api_failure_prevents_pdf_publication(self):
        """The active pipeline cannot create a PDF if review is unavailable."""
        with patch('core.pipeline.text_provider_names'), patch('core.pipeline.image_provider_name'), patch('core.pipeline.generate_activity_pack', return_value=self.pack), patch('core.pipeline.generate_activity_images', side_effect=ImageReviewError('Review unavailable')), patch('core.pipeline.build_activity_pdf') as render:
            with self.assertRaises(ImageReviewError):
                generate_book(theme='Garden', grade_band='Pre-K-K', output_dir=self.folder)
        render.assert_not_called()
        self.assertEqual(list(Path(self.folder).glob('*.pdf')), [])

    def test_active_image_pipeline_deduplicates_but_reviews_all_uses(self):
        """A repeated image gets one check containing every worksheet where it appears."""
        with patch('core.creative_generator.generate_images', return_value=[self.paths[0]]) as images, patch('core.image_review.review_and_repair_images', return_value={'status': 'passed'}) as review:
            generate_creative_images(self.pack, self.config, self.folder)
        self.assertEqual(len(images.call_args.args[0]['pages']), 1)
        unique = review.call_args.args[2]
        self.assertEqual(len(unique[0]['contexts']), len(self.pack['pages']) + 1)
        self.assertEqual(self.pack['image_review']['status'], 'passed')
        self.assertEqual(self.pack['pages'][0]['images'][0]['path'], str(self.paths[0]))

    def test_review_schema_failure_is_bounded(self):
        """Bad review JSON gets one correction attempt, then fails closed."""
        api = Mock()
        api.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='{"reviews": []}'), finish_reason='stop')])
        with patch('core.image_review.text_provider_names', return_value=['gemini']), patch('core.image_review.text_client', return_value=(api, 'test')):
            with self.assertRaisesRegex(ImageReviewError, 'invalid verdicts twice'):
                review_batch(self.pack, self.images, dict(zip((1, 2), self.paths)))
        self.assertEqual(api.chat.completions.create.call_count, 2)
        api.close.assert_called_once()

    def test_second_repair_uses_latest_feedback_and_keeps_approved_assets(self):
        """Two distinct targeted prompts can recover one image without restarting others."""
        second = dict(verdict(False), issues=['The watering can is hidden behind the plant.'],
                      replacement_prompt='Plant on the left and watering can clearly separated on the right.')
        with patch('core.image_review.review_batch', side_effect=[{1: verdict(), 2: verdict(False)},
                    {2: second}, {2: verdict()}]) as review, patch('core.image_review.generate_images', return_value=[self.paths[1]]) as generate:
            summary = review_and_repair_images(self.pack, self.config, self.images, self.paths, self.folder)
        self.assertEqual(summary['regenerated'], 2)
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(generate.call_args.args[0]['pages'][0]['image_prompt'], second['replacement_prompt'])
        checked = review.call_args.args[1][0]
        self.assertEqual(checked['image_prompt'], 'Original requirement 2')
        self.assertEqual(checked['latest_generation_prompt'], second['replacement_prompt'])
        self.assertEqual(checked['previous_issues'], second['issues'])
        self.assertEqual(checked['repair_attempt'], 2)

    def test_second_repair_turns_misidentification_into_shape_constraints(self):
        """Repeated object confusion gets a concrete physical correction, not another vague retry."""
        wrong = {'approved': False,
                 'issues': ['The guiro is a flat round disk with strings and tuning pegs.'],
                 'replacement_prompt': 'An isolated guiro percussion instrument on white.'}
        prompt = _generation_repair_prompt('A guiro instrument.', wrong, 2)
        self.assertIn('flat round disk', prompt)
        self.assertIn('strings and tuning pegs', prompt)
        self.assertIn('physical shape, proportions, material, texture and distinctive parts', prompt)
        self.assertIn('Do not include the mistaken form or parts described above', prompt)

    def test_second_repair_simplifies_persistent_anatomy_failures(self):
        """Repeated anatomy defects trigger a hard-reset composition instead of more complex prompting."""
        bad = {'approved': False,
               'issues': [
                   "The dog's hand is detached and floating beside the pole.",
                   "The mouse's arm is detached from its body.",
                   "The dog's neck and torso are distorted.",
                   "The smoke alarm is hanging on a wire with no solid ceiling."
               ],
               'replacement_prompt': 'A dog, mouse, pole, and smoke alarm in a fire-safety scene.'}
        prompt = _generation_repair_prompt('Original fire-safety scene.', bad, 2)
        self.assertIn('HARD RESET AFTER FAILED ANATOMY REPAIR', prompt)
        self.assertIn('remove decorative or unnecessary characters', prompt)
        self.assertIn('hands attached to wrists', prompt)
        self.assertIn('Avoid reaching, grabbing, twisting', prompt)
        self.assertIn('solid wall or ceiling plane', prompt)
        self.assertIn('never dangling from a wire', prompt)

    def test_final_rejection_reports_defect_and_actual_pdf_page(self):
        """Persistent failures explain their location instead of returning only image IDs."""
        with patch('core.image_review.review_batch', side_effect=[{1: verdict(), 2: verdict(False)},
                    {2: verdict(False)}, {2: verdict(False)}]), patch('core.image_review.generate_images', return_value=[self.paths[1]]) as generate:
            with self.assertRaises(ImageReviewError) as error:
                review_and_repair_images(self.pack, self.config, self.images, self.paths, self.folder)
        self.assertEqual(generate.call_count, 2)
        self.assertIn('Missing the required watering can', str(error.exception))
        self.assertIn('activity 2 (PDF page 3)', str(error.exception))
        self.assertEqual(error.exception.failures[0]['pdf_pages'], [3])

    def test_corrective_scene_never_truncated_by_style(self):
        """The complete scene, including an essential final correction, reaches Cloudflare."""
        scene = 'An original plant scene. ' * 26 + 'MUST SHOW ROOTS.'
        pack = dict(self.pack, character_description='C' * 350)
        prompt = _image_prompt(pack, {'image_prompt': scene}, 'S' * 650)
        self.assertLessEqual(len(prompt), 2048)
        self.assertIn(scene, prompt)
        self.assertNotIn(pack['character_description'], prompt)
        self.assertIn('Never add story cast', prompt)

    def test_activity_asset_prompt_does_not_leak_named_cast(self):
        """Object-only activity art never inherits recurring story characters."""
        pack = dict(self.pack, character_description='Pip the fox and Barnaby the scholarly owl')
        prompt = _image_prompt(pack, {'image_prompt': 'A simple wooden bridge alone on white.'},
                               'Warm watercolor classroom art.')
        self.assertIn('A simple wooden bridge alone on white.', prompt)
        self.assertNotIn('Pip', prompt)
        self.assertNotIn('Barnaby', prompt)
        self.assertIn('no characters in foreground or background', prompt)

    def test_reviewer_treats_original_prompt_as_subject_authority(self):
        """Repair guidance cannot use the pack-wide cast to populate solitary assets."""
        api = Mock()
        raw = {'reviews': [dict(image_id=i, **verdict()) for i in (1, 2)]}
        api.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(raw)), finish_reason='stop')])
        self.pack['character_description'] = 'Pip the fox and Barnaby the scholarly owl'
        with patch('core.image_review.text_provider_names', return_value=['gemini']), patch(
                'core.image_review.text_client', return_value=(api, 'test')):
            review_batch(self.pack, self.images, dict(zip((1, 2), self.paths)))
        instructions = api.chat.completions.create.call_args.kwargs['messages'][0]['content'][0]['text']
        self.assertNotIn('Pip the fox', instructions)
        self.assertNotIn('Barnaby', instructions)
        self.assertIn('original_prompt is the authority', instructions)
        self.assertIn('MUST NOT introduce any subject or character absent from original_prompt', instructions)
