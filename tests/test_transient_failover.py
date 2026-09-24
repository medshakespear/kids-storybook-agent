"""Offline regression tests for Gemini outages through the real SDK transport."""
import json
import os
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI

from core.activity_generator import ActivityGenerationError
from core.credential_pool import reset_credential_pools
from core.creative_generator import ask_json
from tests.test_key_rotation import SLOTS, completion


@patch.dict(os.environ, SLOTS, clear=True)
class TransientFailoverTests(unittest.TestCase):
    """Verify recovery, retry bounds, cooldown expiry, and request preservation."""

    def setUp(self):
        """Use a mock transport while preserving the production SDK configuration."""
        reset_credential_pools()
        self.seen = []
        self.handler = None
        self.addCleanup(reset_credential_pools)
        self.sleep = self.enterContext(patch("core.credential_pool.time.sleep"))
        self.enterContext(patch("core.providers.OpenAI", side_effect=self.client))

    def client(self, **kwargs):
        """Return the real SDK with network traffic intercepted locally."""
        return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(self.dispatch)))

    def dispatch(self, request):
        """Record keys and payloads before returning this test's response."""
        self.seen.append((request.headers["authorization"], json.loads(request.content)))
        return self.handler(request)

    def generate(self):
        """Exercise the same creative-plan call site as production generation."""
        return ask_json("Preserve this creative plan", lambda value: value, "Creative plan")

    def test_brief_503_retries_same_key(self):
        """A transient Gemini failure retries the same sticky key."""
        self.handler = lambda request: httpx.Response(503, json={}) if len(self.seen) == 1 else httpx.Response(200, json=completion())
        self.assertTrue(self.generate()["ok"])
        self.assertEqual(len(self.seen), 2)
        self.assertEqual(self.seen[0][0], self.seen[1][0])

    def test_repeated_503_stays_on_same_key(self):
        """Repeated Gemini outages never consume another key's quota."""
        self.handler = lambda request: httpx.Response(
            503, json={"error": {"message": "temporary upstream outage"}})
        with self.assertRaises(ActivityGenerationError):
            self.generate()
        self.assertGreaterEqual(len(self.seen), 1)
        first_key = self.seen[0][0]
        self.assertTrue(all(key == first_key for key, _ in self.seen))


    def test_all_503_bounded_and_keys_recover_after_cooldown(self):
        """Pool exhaustion prevents multiplied outer retries and does not disable keys."""
        self.handler = lambda request: httpx.Response(503, json={})
        with patch("core.credential_pool.time.monotonic", return_value=100) as clock:
            with self.assertRaisesRegex(ActivityGenerationError, "temporarily unavailable") as error:
                self.generate()
            self.assertNotIn("model availability", str(error.exception))
            self.assertEqual(len(self.seen), 8)
            self.assertEqual(self.sleep.call_count, 4)
            clock.return_value = 159
            with self.assertRaisesRegex(ActivityGenerationError, "no credential slots available"):
                self.generate()
            self.assertEqual(len(self.seen), 8)
            clock.return_value = 161
            self.handler = lambda request: httpx.Response(200, json=completion())
            self.assertTrue(self.generate()["ok"])
            self.assertEqual(len(self.seen), 9)

    def test_long_server_delay_cools_slots_without_short_retry(self):
        """Retry-After takes precedence and does not cause a long worker sleep."""
        self.handler = lambda request: httpx.Response(503, headers={"Retry-After": "120"}, json={})
        with patch("core.credential_pool.time.monotonic", return_value=100) as clock:
            with self.assertRaises(ActivityGenerationError):
                self.generate()
            self.assertEqual(len(self.seen), 4)
            self.sleep.assert_not_called()
            clock.return_value = 219
            with self.assertRaises(ActivityGenerationError):
                self.generate()
            self.assertEqual(len(self.seen), 4)
            clock.return_value = 221
            self.handler = lambda request: httpx.Response(200, json=completion())
            self.assertTrue(self.generate()["ok"])

    def test_short_server_delay_is_respected(self):
        """A short Retry-After cannot be undercut by exponential backoff."""
        self.handler = lambda request: httpx.Response(503, headers={"Retry-After": "7"}, json={}) if len(self.seen) == 1 else httpx.Response(200, json=completion())
        self.assertTrue(self.generate()["ok"])
        self.sleep.assert_called_once_with(7.0)

    def test_connection_timeouts_retry_same_key(self):
        """Actual SDK timeout exceptions keep using the same Gemini key."""
        def handler(request):
            """Simulate timeouts on key one and success on the second key."""
            if request.headers["authorization"].endswith("-1"):
                raise httpx.ReadTimeout("private transport message", request=request)
            return httpx.Response(200, json=completion())

        self.handler = handler
        self.assertTrue(self.generate()["ok"])
        self.assertEqual(len(self.seen), 2)
        self.assertEqual(self.seen[0][0], self.seen[1][0])

    def test_repeated_503_uses_same_key_with_growing_backoff(self):
        """Repeated Gemini 503s stay on one key and back off instead of hammering the service."""
        calls = {'count': 0}
        def handler(request):
            calls['count'] += 1
            if calls['count'] < 4:
                return httpx.Response(503, json={})
            return httpx.Response(200, json=completion())
        self.handler = handler

        with patch.dict(os.environ, {'GEMINI_TRANSPORT_ATTEMPTS': '8'}, clear=False), patch(
                'core.creative_generator.random.random', return_value=0):
            self.assertTrue(self.generate()['ok'])

        keys = [key for key, _ in self.seen]
        self.assertEqual(keys, [keys[0]] * len(keys))
        waits = [call.args[0] for call in self.sleep.call_args_list]
        self.assertEqual(waits[:3], [5.0, 10.0, 20.0])

    def test_bad_requests_and_missing_models_never_rotate(self):
        """A content/configuration problem must not spend twelve requests."""
        for status in (400, 404):
            with self.subTest(status=status):
                self.seen.clear()
                self.handler = lambda request: httpx.Response(status, json={})
                with self.assertRaises(ActivityGenerationError):
                    self.generate()
                self.assertEqual(len(self.seen), 1)
                self.sleep.assert_not_called()

    def test_transient_failure_does_not_consume_validation_attempt(self):
        """Two invalid designs plus a provider outage still allow the third logical repair."""
        sequence = [
            completion('{"value": 1}'),
            completion('{"value": 2}'),
            None,
            completion('{"value": 3}'),
        ]
        calls = {'count': 0}

        def handler(request):
            index = calls['count']
            calls['count'] += 1
            if sequence[index] is None:
                return httpx.Response(503, json={})
            return httpx.Response(200, json=sequence[index])

        self.handler = handler
        def validate(value):
            if value.get('value') != 3:
                raise ValueError('design still invalid')
            return value

        result = ask_json('repair me', validate, 'Activity design 1')
        self.assertEqual(result['value'], 3)
        self.assertEqual(len(self.seen), 4)

    def test_rate_limit_during_transient_retry_immediately_rotates(self):
        """A subsequent 429 stops retries of that key even before three attempts."""
        def handler(request):
            """Return a 503, then a quota error, then success on key two."""
            if len(self.seen) <= 2:
                return httpx.Response(503 if len(self.seen) == 1 else 429, json={})
            return httpx.Response(200, json=completion())

        self.handler = handler
        self.assertTrue(self.generate()["ok"])
        self.assertEqual([key for key, _ in self.seen],
                         [f"Bearer fake-text-secret-{i}" for i in (1, 1, 2)])
        self.sleep.assert_called_once()

    def test_slow_budget_exhaustion_gets_a_fresh_outer_attempt(self):
        """One exhausted completion budget is transient and a fresh unit attempt can recover."""
        calls = {'count': 0}
        with patch('core.credential_pool.time.monotonic', return_value=100) as clock:
            def handler(request):
                calls['count'] += 1
                if calls['count'] == 1:
                    clock.return_value = 191
                    return httpx.Response(503, json={})
                return httpx.Response(200, json=completion())
            self.handler = handler
            self.assertTrue(self.generate()['ok'])
        self.assertEqual(len(self.seen), 2)
