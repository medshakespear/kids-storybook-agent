"""Exercise real request routing with mocked HTTP transports and fake secrets."""
import base64
import io
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import Mock, patch

import httpx
from openai import OpenAI
from PIL import Image

from core.credential_pool import Credential, CredentialPool, ProviderError, reset_credential_pools, retry_after_seconds
from core.creative_generator import ask_json
from core.image_generator import generate_images, ImageGenerationError
from core.providers import configured_credentials, text_client, validate_providers
from tests.test_providers import STORY, CONFIG

SLOTS = {
    "IMAGE_WORKERS": "1",
    **{f"GEMINI_API_KEY_{i}": f"fake-text-secret-{i}" for i in range(1, 5)},
    **{f"CLOUDFLARE_API_TOKEN_{i}": f"fake-image-secret-{i}" for i in range(1, 5)},
    **{f"CLOUDFLARE_ACCOUNT_ID_{i}": str(i) * 32 for i in range(1, 5)},
}


def completion(content='{"ok": true}'):
    """Supply the response envelope consumed by the actual OpenAI SDK."""
    return {"id": "test", "object": "chat.completion", "created": 0, "model": "test",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}]}


def image_response():
    """Return a genuine encoded PNG without any paid image-generation call."""
    buffer = io.BytesIO()
    Image.new("RGB", (256, 256), "teal").save(buffer, "PNG")
    return Mock(status_code=200, headers={}, json=Mock(return_value={
        "success": True, "result": {"image": base64.b64encode(buffer.getvalue()).decode()}}))


@patch.dict(os.environ, SLOTS, clear=True)
class KeyRotationTests(unittest.TestCase):
    """Verify four-slot behavior, bounds, compatibility, and secret handling."""

    def setUp(self):
        """Clear simulated cooldowns before each independent test."""
        reset_credential_pools()

    def test_numbered_only_and_legacy_aliases(self):
        """All-four configuration works; explicit slot one overrides the legacy key."""
        validate_providers()
        self.assertEqual(len(configured_credentials("gemini")), 4)
        self.assertEqual(len(configured_credentials("cloudflare")), 4)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "unused-fifth-key"}):
            keys = configured_credentials("gemini")
            self.assertEqual(keys[0].api_key, SLOTS["GEMINI_API_KEY_1"])
            self.assertEqual(len(keys), 4)
        with patch.dict(os.environ, {"GEMINI_API_KEY_2": SLOTS["GEMINI_API_KEY_1"]}):
            self.assertEqual(len(configured_credentials("gemini")), 3)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "legacy", "GEMINI_API_KEY_4": "last"}, clear=True):
            self.assertEqual([key.api_key for key in configured_credentials("gemini")], ["legacy", "last"])

    def test_missing_cloudflare_pair_fails_before_generation(self):
        """Every token must resolve to its account, with no secret value in the error."""
        with patch.dict(os.environ, {"CLOUDFLARE_ACCOUNT_ID_3": ""}):
            with self.assertRaisesRegex(ValueError, "CLOUDFLARE_ACCOUNT_ID_3"):
                validate_providers()
        with patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN_2": ""}):
            with self.assertRaisesRegex(ValueError, "CLOUDFLARE_API_TOKEN_2"):
                validate_providers()

    def test_gemini_fourth_slot_completes_same_unit_and_stays_selected(self):
        """Quota failover preserves the prompt and the next unit uses the healthy key."""
        seen = []

        def handler(request):
            """Limit the first three configured keys and accept the fourth."""
            seen.append((request.headers["authorization"], json.loads(request.content)))
            if request.headers["authorization"] != "Bearer fake-text-secret-4":
                return httpx.Response(429, headers={"Retry-After": "120"},
                                      json={"error": {"message": "private upstream content"}})
            return httpx.Response(200, json=completion())

        def sdk_client(**kwargs):
            """Replace only the HTTP transport, preserving all production arguments."""
            self.assertEqual(kwargs["max_retries"], 0)
            return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

        with patch("core.providers.OpenAI", side_effect=sdk_client), patch("core.creative_generator.time.sleep") as sleep:
            with self.assertLogs("core.credential_pool", level="INFO") as logs:
                self.assertTrue(ask_json("same design", lambda value: value, "Design 2")["ok"])
                self.assertTrue(ask_json("next design", lambda value: value, "Design 3")["ok"])
            sleep.assert_not_called()
        self.assertEqual([auth for auth, _ in seen], [f"Bearer fake-text-secret-{i}" for i in (1, 2, 3, 4, 4)])
        self.assertTrue(all(body == seen[0][1] for _, body in seen[:4]))
        self.assertNotIn("private upstream content", str(logs.output))
        for key, value in SLOTS.items():
            if key != 'IMAGE_WORKERS':
                self.assertNotIn(value, str(logs.output))

    def test_gemini_validation_repair_does_not_rotate(self):
        """Invalid JSON is a content repair, not an excuse to exhaust more keys."""
        seen = []

        def handler(request):
            """Return one malformed design followed by a corrected design."""
            seen.append(request.headers["authorization"])
            return httpx.Response(200, json=completion('{bad' if len(seen) == 1 else '{"ok": true}'))

        def sdk_client(**kwargs):
            """Inject a local transport into each short-lived SDK client."""
            return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

        with patch("core.providers.OpenAI", side_effect=sdk_client), patch("core.creative_generator.time.sleep"):
            self.assertTrue(ask_json("test", lambda value: value, "Design")["ok"])
        self.assertEqual(seen, ["Bearer fake-text-secret-1"] * 2)

    def test_gemini_all_limited_exits_and_honors_retry_after(self):
        """A second call during cooldown makes no network requests; expiry recovers."""
        seen = []

        def handler(request):
            """Provide the rate-limit response used for all four credentials."""
            seen.append(request)
            return httpx.Response(429, headers={"Retry-After": "120"}, json={"error": {"message": "secret"}})

        def sdk_client(**kwargs):
            """Bind the same local HTTP mock to each SDK instance."""
            return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

        with patch("core.credential_pool.time.monotonic", return_value=100) as clock, patch("core.providers.OpenAI", side_effect=sdk_client):
            api, model = text_client("gemini")
            for moment in (100, 219):
                clock.return_value = moment
                with self.assertRaisesRegex(ProviderError, "no credential slots available") as error:
                    api.chat.completions.create(model=model, messages=[])
                self.assertFalse(error.exception.retryable)
                self.assertNotIn("secret", str(error.exception))
            self.assertEqual(len(seen), 4)
            clock.return_value = 221
            with self.assertRaises(ProviderError):
                api.chat.completions.create(model=model, messages=[])
            self.assertEqual(len(seen), 8)
            api.close()

    def test_cloudflare_pairs_rotate_without_regenerating_previous_images(self):
        """Account and token advance together and only the failed page is retried."""
        story = dict(STORY, pages=[dict(STORY["pages"][0], page_number=i) for i in (1, 2, 3)])
        limited = Mock(status_code=429, headers={"Retry-After": "120"}, json=Mock(return_value={}))
        with tempfile.TemporaryDirectory() as folder, patch("core.image_generator.requests.post",
                side_effect=[image_response(), limited, limited, limited, image_response(), image_response()]) as post:
            self.assertEqual(len(generate_images(story, CONFIG, folder)), 3)
        self.assertEqual(post.call_count, 6)
        for call, slot in zip(post.call_args_list, (1, 1, 2, 3, 4, 4)):
            self.assertIn(f"/accounts/{str(slot) * 32}/", call.args[0])
            self.assertEqual(call.kwargs["headers"]["Authorization"], f"Bearer fake-image-secret-{slot}")
        self.assertTrue(all(call.kwargs["json"] == post.call_args_list[1].kwargs["json"] for call in post.call_args_list[1:5]))

    def test_cloudflare_all_limited_makes_only_four_calls(self):
        """The outer image retry loop cannot repeatedly cycle through exhausted keys."""
        response = Mock(status_code=429, headers={}, json=Mock(return_value={}))
        with tempfile.TemporaryDirectory() as folder, patch("core.image_generator.requests.post", return_value=response) as post, patch("core.image_generator.time.sleep") as sleep:
            with self.assertRaisesRegex(ImageGenerationError, "no credential slots available"):
                generate_images(STORY, CONFIG, folder)
            self.assertEqual(post.call_count, 4)
            sleep.assert_not_called()

    def test_cloudflare_shared_account_skips_all_its_tokens_on_quota(self):
        """A second token for the same account cannot reset its account-level quota."""
        response = Mock(status_code=429, headers={}, json=Mock(return_value={}))
        with patch.dict(os.environ, {"CLOUDFLARE_ACCOUNT_ID_2": "1" * 32}), tempfile.TemporaryDirectory() as folder, patch("core.image_generator.requests.post", side_effect=[response, image_response()]) as post:
            generate_images(STORY, CONFIG, folder)
        self.assertIn("/accounts/" + "3" * 32 + "/", post.call_args.args[0])

    def test_cloudflare_auth_switches_but_bad_requests_do_not(self):
        """Auth rotates slots; a sanitized 400 retry stays on the same credential."""
        for status, count in ((401, 2), (403, 2), (400, 2), (404, 1)):
            with self.subTest(status=status):
                reset_credential_pools()
                bad = Mock(status_code=status, headers={}, json=Mock(return_value={}))
                with tempfile.TemporaryDirectory() as folder, patch("core.image_generator.requests.post", side_effect=[bad, image_response()]) as post:
                    if status in {401, 403, 400}:
                        generate_images(STORY, CONFIG, folder)
                    else:
                        with self.assertRaises(ImageGenerationError):
                            generate_images(STORY, CONFIG, folder)
                    self.assertEqual(post.call_count, count)
                    if status == 400:
                        self.assertEqual(post.call_args_list[0].kwargs['headers'],
                                         post.call_args_list[1].kwargs['headers'])
                        self.assertNotEqual(post.call_args_list[0].kwargs['json']['prompt'],
                                            post.call_args_list[1].kwargs['json']['prompt'])


class PoolMechanicsTests(unittest.TestCase):
    """Test shared quotas, timing, and concurrent callers independently of HTTP."""

    def test_known_project_group_and_threads_skip_cooling_keys(self):
        """Concurrent calls all avoid the already cooled-down project group."""
        pool = CredentialPool("gemini", (
            Credential("one", "secret-one", quota_group="project-a"),
            Credential("two", "secret-two", quota_group="project-a"),
            Credential("three", "secret-three", quota_group="project-b")), 60)
        calls = []

        def request(credential):
            """Cool project A once and return the healthy slot name."""
            calls.append(credential.label)
            if credential.label == "one":
                raise ProviderError("rate limited", status_code=429, rotate=True)
            return credential.label

        self.assertEqual(pool.run(request), "three")
        with ThreadPoolExecutor(max_workers=4) as executor:
            self.assertEqual(list(executor.map(lambda _: pool.run(request), range(8))), ["three"] * 8)
        self.assertNotIn("two", calls)
        self.assertNotIn("secret", repr(pool.credentials))

    def test_concurrent_callers_use_different_idle_credentials(self):
        """Parallel requests reserve separate keys instead of piling onto the sticky cursor."""
        pool = CredentialPool("gemini", (
            Credential("one", "secret-one"),
            Credential("two", "secret-two"),
        ), 60)
        barrier = threading.Barrier(2)
        used = []

        def request(credential):
            used.append(credential.label)
            barrier.wait(timeout=5)
            return credential.label

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: pool.run(request), range(2)))
        self.assertEqual(set(results), {"one", "two"})
        self.assertEqual(set(used), {"one", "two"})

    def test_all_transient_failures_are_retryable_but_quota_exhaustion_is_not(self):
        """Temporary provider outages may retry later; quota exhaustion stays fail-fast."""
        transient_pool = CredentialPool("gemini", (
            Credential("one", "secret-one"),
            Credential("two", "secret-two"),
        ), 60)

        def outage(_credential):
            raise ProviderError("temporary", True, status_code=503, rotate=True)

        with self.assertRaises(ProviderError) as transient_error:
            transient_pool.run(outage)
        self.assertTrue(transient_error.exception.retryable)
        self.assertLessEqual(transient_error.exception.retry_after or 99, 15)

        quota_pool = CredentialPool("gemini", (
            Credential("one", "secret-one"),
            Credential("two", "secret-two"),
        ), 60)

        def quota(_credential):
            raise ProviderError("quota", True, status_code=429, rotate=True, retry_after=120)

        with self.assertRaises(ProviderError) as quota_error:
            quota_pool.run(quota)
        self.assertFalse(quota_error.exception.retryable)

    def test_retry_after_supports_dates_and_google_retry_info(self):
        """The longest valid server delay is honored and malformed values are ignored."""
        future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=180), usegmt=True)
        self.assertGreater(retry_after_seconds({"retry-after": future}), 178)
        body = {"error": {"details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "120.5s"}]}}
        self.assertEqual(retry_after_seconds({"retry-after": "30"}, body), 120.5)
        self.assertIsNone(retry_after_seconds({"retry-after": "nan"}))
        self.assertIsNone(retry_after_seconds({"retry-after": "bad"}, {"details": None}))

    def test_daily_cloudflare_limit_waits_until_reset(self):
        """Daily allocation errors retain a longer cooldown than the short default."""
        environment = {"CLOUDFLARE_API_TOKEN": "token", "CLOUDFLARE_ACCOUNT_ID": "a" * 32}
        response = Mock(status_code=429, headers={}, json=Mock(return_value={"errors": [{"code": 3036}]}))
        with patch.dict(os.environ, environment, clear=True), patch("core.image_generator.requests.post", return_value=response), patch("core.image_generator.datetime") as date:
            date.now.return_value = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
            date.combine = datetime.combine
            date.min = datetime.min
            from core.image_generator import _cloudflare_request
            with self.assertRaises(ProviderError) as error:
                _cloudflare_request("test", Credential("one", "token", "a" * 32))
            self.assertEqual(error.exception.retry_after, 43200)
