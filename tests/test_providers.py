"""Provider routing, fallback, and image decoding tests without external calls."""
import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from openai import OpenAI
from PIL import Image

from core.providers import validate_providers, text_provider_names, text_client
from core.credential_pool import reset_credential_pools
from core.story_generator import generate_story, StoryGenerationError
from core.image_generator import generate_images, ImageGenerationError, _image_prompt, _sanitize_cloudflare_prompt

ENV = {"GEMINI_API_KEY": "test-gemini", "GROQ_API_KEY": "test-groq",
       "CLOUDFLARE_API_TOKEN": "test-cloudflare", "CLOUDFLARE_ACCOUNT_ID": "a" * 32}
STORY = {"title": "A Friendly Fox", "grade_band": "Pre-K-K", "theme": "Sharing",
         "character_name": "Milo", "character_description": "Milo is a blue fox with a yellow scarf.",
         "pages": [{"page_number": 1, "text": "Milo shares his crayons.",
                    "image_prompt": "Milo smiles in a sunny classroom."}]}
CONFIG = {"page_count": {"min": 1, "max": 1}, "words_per_page": {"min": 3, "max": 6},
          "vocabulary_notes": "Simple", "sentence_complexity_notes": "Short",
          "illustration_style": "Bold simple shapes"}


class ProviderTests(unittest.TestCase):
    """Exercise provider boundaries and avoid accidental paid fallback."""

    def setUp(self):
        """Keep process-local cooldowns independent between test scenarios."""
        reset_credential_pools()

    @patch.dict(os.environ, ENV, clear=True)
    def test_defaults_need_no_openai_key(self):
        """New defaults validate with only the new credentials."""
        validate_providers()
        self.assertEqual(text_provider_names(), ["gemini"])
        api, model = text_client("gemini")
        self.assertEqual(str(api.base_url), "https://generativelanguage.googleapis.com/v1beta/openai/")
        self.assertEqual(model, "gemini-3.5-flash-lite")
        api.close()

    @patch.dict(os.environ, {"OPENAI_API_KEY": "old-key"}, clear=True)
    def test_old_openai_key_does_not_enable_paid_calls(self):
        """An old key cannot silently override the new provider selection."""
        with self.assertRaisesRegex(ValueError, "GEMINI_API_KEY"):
            validate_providers()

    @patch.dict(os.environ, ENV, clear=True)
    def test_cloudflare_jpeg_to_png(self):
        """Cloudflare's envelope is decoded into a real image usable by WeasyPrint."""
        data = io.BytesIO()
        Image.new("RGB", (512, 512), "coral").save(data, format="JPEG")
        response = Mock(status_code=200)
        response.json.return_value = {"success": True, "result": {"image": base64.b64encode(data.getvalue()).decode()}}
        with tempfile.TemporaryDirectory() as folder, patch("core.image_generator.requests.post", return_value=response) as post:
            paths = generate_images(STORY, CONFIG, folder)
            self.assertEqual(len(paths), 1)
            with Image.open(paths[0]) as image:
                self.assertEqual(image.format, "PNG")
            self.assertEqual(post.call_args.kwargs["json"]["steps"], 4)
            self.assertNotIn("width", post.call_args.kwargs["json"])
            self.assertIn(STORY["character_description"], post.call_args.kwargs["json"]["prompt"])
            from core.pdf_builder import build_pdf
            pdf = build_pdf(STORY, paths, {**CONFIG, "text_placement_style": "bottom_band"}, Path(folder) / "test.pdf")
            self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))

    @patch.dict(os.environ, ENV, clear=True)
    def test_cloudflare_auth_fails_once_without_leaking_body(self):
        """Invalid credentials do not consume four retries or leak response text."""
        with tempfile.TemporaryDirectory() as folder, patch("core.image_generator.requests.post", return_value=Mock(status_code=403, text="secret")) as post:
            with self.assertRaises(ImageGenerationError) as error:
                generate_images(STORY, CONFIG, folder)
            self.assertNotIn("secret", str(error.exception))
            self.assertEqual(post.call_count, 1)
            self.assertEqual(list(Path(folder).iterdir()), [])

    @patch.dict(os.environ, ENV, clear=True)
    def test_cloudflare_400_retries_with_sanitized_prompt(self):
        """A bad-request image prompt is normalized once before failing the page."""
        data = io.BytesIO()
        Image.new("RGB", (512, 512), "coral").save(data, format="PNG")
        bad = Mock(status_code=400, headers={})
        good = Mock(status_code=200)
        good.json.return_value = {"success": True, "result": {"image": base64.b64encode(data.getvalue()).decode()}}
        long_story = dict(STORY, pages=[dict(STORY["pages"][0],
            image_prompt=("Scene with\x00 control spacing. " * 120))])
        with tempfile.TemporaryDirectory() as folder, patch(
                "core.image_generator.requests.post", side_effect=[bad, good]) as post:
            paths = generate_images(long_story, CONFIG, folder, max_retries=2)
        self.assertEqual(len(paths), 1)
        self.assertEqual(post.call_count, 2)
        first_prompt = post.call_args_list[0].kwargs["json"]["prompt"]
        second_prompt = post.call_args_list[1].kwargs["json"]["prompt"]
        self.assertNotEqual(first_prompt, second_prompt)
        self.assertEqual(second_prompt, _sanitize_cloudflare_prompt(first_prompt))
        self.assertLessEqual(len(second_prompt), 1800)

    @patch.dict(os.environ, ENV, clear=True)
    def test_cloudflare_rate_limit_has_bounded_retries(self):
        """An exhausted pool exits without retrying a credential during cooldown."""
        with tempfile.TemporaryDirectory() as folder, patch("core.image_generator.requests.post", return_value=Mock(status_code=429)) as post, patch("core.image_generator.time.sleep") as sleep:
            with self.assertRaises(ImageGenerationError):
                generate_images(STORY, CONFIG, folder, max_retries=2)
            self.assertEqual(post.call_count, 1)
            sleep.assert_not_called()

    @patch.dict(os.environ, {**ENV, "TEXT_FALLBACK_PROVIDER": "none"}, clear=True)
    def test_404_identifies_model_and_uses_real_gemini_route(self):
        """404 diagnostics expose the model, never raw error content, and do not retry."""
        seen = []

        def handler(request):
            """Capture the actual configured client path and return a missing model."""
            seen.append(request)
            return httpx.Response(404, json={"error": {"message": "private-response-secret"}})

        def sdk_client(**kwargs):
            """Keep production client arguments, replacing only network transport."""
            return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

        with patch("core.providers.OpenAI", side_effect=sdk_client), patch("core.story_generator.time.sleep") as sleep:
            with self.assertRaises(StoryGenerationError) as error:
                generate_story("Sharing", "Pre-K-K", {"Pre-K-K": CONFIG})
        self.assertEqual(len(seen), 1)
        self.assertEqual(str(seen[0].url), "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
        self.assertIn("gemini-3.5-flash-lite", str(error.exception))
        self.assertIn("GEMINI_TEXT_MODEL", str(error.exception))
        self.assertNotIn("private-response-secret", str(error.exception))
        self.assertNotIn("gemini: gemini:", str(error.exception))
        sleep.assert_not_called()

    @patch.dict(os.environ, {**ENV, "TEXT_PROVIDER": "groq"}, clear=True)
    def test_retired_groq_is_not_used(self):
        """Old Groq credentials never cause fallback or routing."""
        with self.assertRaisesRegex(ValueError, "no longer supported"):
            text_provider_names()

    @patch.dict(os.environ, {**ENV, "GEMINI_TEXT_MODEL": " models/gemini-3.5-flash-lite "}, clear=True)
    def test_gemini_model_name_normalization(self):
        """Copied model resource names normalize to the compatible API model ID."""
        api, model = text_client("gemini")
        self.assertEqual(model, "gemini-3.5-flash-lite")
        api.close()

    def test_long_prompt_keeps_character(self):
        """Scene truncation preserves verbatim identity and the provider limit."""
        prompt = _image_prompt(STORY, {"image_prompt": "Sunny classroom. " * 400}, CONFIG["illustration_style"])
        self.assertLessEqual(len(prompt), 2048)
        self.assertIn(STORY["character_description"], prompt)
