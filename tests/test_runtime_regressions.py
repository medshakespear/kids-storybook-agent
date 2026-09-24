"""Offline regression checks for API boundaries and exhausted image retries."""
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import cron_job
import webhook_server as web
from core.creative_generator import _synchronize_asset_references
from core.image_generator import generate_images, ImageGenerationError, _cloudflare_request
from core.credential_pool import Credential, ProviderError
from tests.test_providers import STORY, CONFIG, ENV


class RuntimeRegressionTests(unittest.TestCase):
    """Exercise failure paths without calling providers or changing persisted state."""

    def test_last_image_attempt_cannot_return_none(self):
        """A final HTTP 400 always raises, including a one-attempt budget."""
        cases = [(1, [ProviderError('bad prompt', status_code=400)]),
                 (2, [ProviderError('temporary', True), ProviderError('bad prompt', status_code=400)])]
        for attempts, errors in cases:
            with self.subTest(attempts=attempts), tempfile.TemporaryDirectory() as folder, patch.dict(
                    os.environ, ENV, clear=True), patch(
                    'core.image_generator._cloudflare_image', side_effect=errors), patch(
                    'core.image_generator.time.sleep'):
                with self.assertRaises(ImageGenerationError):
                    generate_images(STORY, CONFIG, folder, max_retries=attempts)

    def test_non_object_cloudflare_response_is_sanitized(self):
        """Unexpected HTTP-200 JSON is retryable, without leaking its contents."""
        response = Mock(status_code=200)
        response.json.return_value = ['private response']
        with patch('core.image_generator.requests.post', return_value=response):
            with self.assertRaises(ProviderError) as error:
                _cloudflare_request('A plant.', Credential('test', 'test-key', 'a' * 32))
        self.assertTrue(error.exception.retryable)
        self.assertNotIn('private response', str(error.exception))

    def test_malformed_request_returns_json_without_generation(self):
        """Malformed hosts, ports and falsey invalid grade bands are client errors."""
        bodies = [{'link': 'https://[broken'}, {'link': 'https://example.com:nope'},
                  {'link': 'https://:80'}, {'description': 'Garden', 'grade_band': []},
                  {'description': 'Garden', 'grade_band': ''},
                  {'description': 'Garden', 'grade_band': 0}]
        with patch.object(web, '_authorized', return_value=True), patch.object(web, 'generate_book') as generate:
            for body in bodies:
                with self.subTest(body=body):
                    response = web.app.test_client().post('/generate', json=body)
                    self.assertEqual(response.status_code, 400)
                    self.assertIn('error', response.json)
        generate.assert_not_called()

    def test_invalid_cron_count_has_clear_setup_error(self):
        """A typo in Railway variables gets a useful summary instead of a traceback."""
        output = io.StringIO()
        with patch.dict(os.environ, {'DAILY_BOOK_COUNT': 'invalid'}), patch(
                'cron_job.validate_providers'), patch('cron_job.fetch_library_state', return_value=None), patch(
                'cron_job.load_state', return_value={'generated': []}), redirect_stdout(output):
            self.assertEqual(cron_job.main(), 2)
        self.assertIn('Daily run setup failed', output.getvalue())

    def test_asset_reference_repair_preserves_html_attributes(self):
        """Regex replacement inserts the matched attribute instead of literal backreferences."""
        html = '<img data-asset="wrong" style="width:80mm;height:55mm"/>'
        fixed = _synchronize_asset_references(html, ['scene'])
        self.assertIn('data-asset="scene"', fixed)
        self.assertNotIn('\\g<', fixed)
        self.assertEqual(fixed.count('<img'), 1)
