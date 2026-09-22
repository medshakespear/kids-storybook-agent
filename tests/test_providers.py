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
from core.story_generator import generate_story, StoryGenerationError
from core.image_generator import generate_images, ImageGenerationError, _image_prompt

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

    @patch.dict(os.environ, ENV, clear=True)
    def test_defaults_need_no_openai_key(self):
        """New defaults validate with only the new credentials."""
        validate_providers()
        self.assertEqual(text_provider_names(), ["gemini", "groq"])
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
    def test_gemini_auth_error_falls_back_to_groq(self):
        """An auth failure skips retries and Groq returns a locally validated story."""
        requests_seen = []

        def handler(request):
            """Simulate real SDK wire responses and record selected endpoints."""
            requests_seen.append(request)
            if request.url.host == "generativelanguage.googleapis.com":
                return httpx.Response(401, json={"error": {"message": "private-response-secret"}})
            body = json.loads(request.content)
            self.assertEqual(body["response_format"], {"type": "json_object"})
            return httpx.Response(200, json={"choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(STORY)}}]})

        def make_client(name):
            """Construct compatible clients on a mock HTTP transport."""
            host = "generativelanguage.googleapis.com" if name == "gemini" else "api.groq.com"
            return OpenAI(api_key="test", base_url=f"https://{host}/v1/", max_retries=0,
                          http_client=httpx.Client(transport=httpx.MockTransport(handler))), "model"

        with patch("core.story_generator.text_client", side_effect=make_client), patch("core.story_generator.time.sleep") as sleep:
            result = generate_story("Sharing", "Pre-K-K", {"Pre-K-K": CONFIG})
        self.assertEqual(len(requests_seen), 2)
        sleep.assert_not_called()
        self.assertIn(STORY["character_description"], result["pages"][0]["image_prompt"])

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
    def test_cloudflare_rate_limit_has_bounded_retries(self):
        """Rate limits back off but cannot create an endless cron run."""
        with tempfile.TemporaryDirectory() as folder, patch("core.image_generator.requests.post", return_value=Mock(status_code=429)) as post, patch("core.image_generator.time.sleep") as sleep:
            with self.assertRaises(ImageGenerationError):
                generate_images(STORY, CONFIG, folder, max_retries=2)
            self.assertEqual(post.call_count, 2)
            sleep.assert_called_once()

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
    def test_groq_default_routes_to_groq(self):
        """GPT-OSS requests use Groq's credential and endpoint, not OpenAI's."""
        seen = []

        def handler(request):
            """Return a valid story through the Groq-compatible wire format."""
            seen.append(request)
            return httpx.Response(200, json={"choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(STORY)}}]})

        def sdk_client(**kwargs):
            """Retain actual provider routing while preventing network traffic."""
            return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

        with patch("core.providers.OpenAI", side_effect=sdk_client):
            generate_story("Sharing", "Pre-K-K", {"Pre-K-K": CONFIG})
        self.assertEqual(str(seen[0].url), "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(json.loads(seen[0].content)["model"], "openai/gpt-oss-20b")
        self.assertEqual(seen[0].headers["authorization"], "Bearer test-groq")

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
