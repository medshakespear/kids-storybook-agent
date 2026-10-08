"""Offline Gemini failover and shared deadline checks through the real SDK."""
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


@patch.dict(os.environ,SLOTS,clear=True)
class TransientFailoverTests(unittest.TestCase):
    """Simulate time passage, outages and recovery without real sleeps or API calls."""

    def setUp(self):
        """Keep real SDK payloads while replacing transport and monotonic clock."""
        reset_credential_pools()
        self.addCleanup(reset_credential_pools)
        self.seen=[]
        self.now=100.0
        self.handler=None
        self.enterContext(patch('core.credential_pool.time.monotonic',side_effect=lambda:self.now))
        self.sleep=self.enterContext(patch('core.credential_pool.time.sleep',side_effect=self.advance))
        self.enterContext(patch('core.providers.OpenAI',side_effect=self.client))

    def advance(self,seconds):
        """Honor virtual backoff while avoiding wall-clock delay."""
        self.now+=seconds

    def client(self,**kwargs):
        """Build a real SDK client with a local mock HTTP transport."""
        return OpenAI(**kwargs,http_client=httpx.Client(transport=httpx.MockTransport(self.dispatch)))

    def dispatch(self,request):
        """Record credential and unchanged JSON request for each HTTP attempt."""
        self.seen.append((request.headers['authorization'],json.loads(request.content)))
        return self.handler(request)

    def generate(self):
        """Exercise the production JSON call rather than pool internals alone."""
        return ask_json('Preserve this creative plan',lambda value:value,'Creative plan')

    def test_503_immediately_uses_next_available_key(self):
        """Failover avoids an outer retry wait when another credential succeeds."""
        self.handler=lambda request:httpx.Response(503,json={}) if len(self.seen)==1 else httpx.Response(200,json=completion())
        self.assertTrue(self.generate()['ok'])
        self.assertEqual([key for key,_ in self.seen],['Bearer fake-text-secret-1','Bearer fake-text-secret-2'])
        self.assertEqual(self.seen[0][1],self.seen[1][1])
        self.sleep.assert_not_called()

    def test_timeouts_rotate_without_leaking_transport_message(self):
        """Actual SDK timeout exceptions try the next credential."""
        def handler(request):
            """Simulate one timeout followed by a healthy key."""
            if len(self.seen)==1:
                raise httpx.ReadTimeout('private transport message',request=request)
            return httpx.Response(200,json=completion())
        self.handler=handler
        self.assertTrue(self.generate()['ok'])
        self.assertNotEqual(self.seen[0][0],self.seen[1][0])
        self.sleep.assert_not_called()

    def test_repeated_outage_is_bounded_and_keys_recover(self):
        """Each configured slot is tried with finite rounds and temporary cooldowns."""
        self.handler=lambda request:httpx.Response(503,json={})
        with self.assertRaisesRegex(ActivityGenerationError,'temporarily unavailable'):
            self.generate()
        self.assertLessEqual(len(self.seen),12)
        self.assertEqual(len({key for key,_ in self.seen}),4)
        self.advance(16)
        self.handler=lambda request:httpx.Response(200,json=completion())
        self.assertTrue(self.generate()['ok'])

    def test_long_retry_after_does_not_exceed_completion_budget(self):
        """Do not sleep beyond the shared deadline or retry a blocked credential."""
        self.handler=lambda request:httpx.Response(503,headers={'Retry-After':'120'},json={})
        with patch.dict(os.environ,{'GEMINI_TRANSPORT_BUDGET_SECONDS':'120'}), self.assertRaisesRegex(ActivityGenerationError,'time budget exhausted'):
            self.generate()
        self.assertEqual(len(self.seen),4)
        self.sleep.assert_not_called()

    def test_short_retry_after_is_honored_when_all_slots_are_blocked(self):
        """An outer cooldown wait respects server guidance before retrying."""
        self.handler=lambda request:httpx.Response(503,headers={'Retry-After':'7'},json={}) if len(self.seen)<=4 else httpx.Response(200,json=completion())
        self.assertTrue(self.generate()['ok'])
        self.assertEqual(len(self.seen),5)
        self.assertGreaterEqual(self.sleep.call_args.args[0],7)

    def test_bad_request_and_missing_model_never_rotate(self):
        """Configuration/prompt defects stop after one HTTP request."""
        for status in (400,404):
            self.seen=[]
            self.handler=lambda request:httpx.Response(status,json={})
            with self.assertRaises(ActivityGenerationError):
                self.generate()
            self.assertEqual(len(self.seen),1)
        self.sleep.assert_not_called()

    def test_transport_failure_does_not_consume_content_validation_attempt(self):
        """A repaired response still gets the configured content-validation budget."""
        sequence=[completion('{"value":1}'),completion('{"value":2}'),None,completion('{"value":3}')]
        def handler(request):
            """Return two bad drafts, one outage, then a valid draft."""
            response=sequence[len(self.seen)-1]
            return httpx.Response(503,json={}) if response is None else httpx.Response(200,json=response)
        self.handler=handler
        def validate(value):
            """Accept the third logical content draft."""
            if value['value']!=3:raise ValueError('design still invalid')
            return value
        self.assertEqual(ask_json('Repair me',validate,'Activity design 1')['value'],3)
        self.assertEqual(len(self.seen),4)

    def test_timeout_and_quota_failures_visit_distinct_keys(self):
        """503 followed by 429 cannot trap the request on the first key."""
        self.handler=lambda request:httpx.Response(503 if len(self.seen)==1 else 429,json={}) if len(self.seen)<=2 else httpx.Response(200,json=completion())
        self.assertTrue(self.generate()['ok'])
        self.assertEqual([key for key,_ in self.seen],[f'Bearer fake-text-secret-{i}' for i in (1,2,3)])
        self.sleep.assert_not_called()

    def test_slow_timeouts_share_one_deadline_across_pool_rounds(self):
        """The outer loop cannot restart a new 120-second budget after each timeout."""
        def handler(request):
            """Advance time as if each slow request consumed its actual timeout."""
            self.advance(min(40,max(0,220-self.now)))
            raise httpx.ReadTimeout('private',request=request)
        self.handler=handler
        with patch.dict(os.environ,{'GEMINI_TRANSPORT_BUDGET_SECONDS':'120'}), self.assertRaisesRegex(ActivityGenerationError,'time budget exhausted'):
            self.generate()
        self.assertEqual(len(self.seen),3)
        self.assertLessEqual(self.now,220)
        self.sleep.assert_not_called()

    def test_default_budget_reaches_fourth_key_after_slow_timeouts(self):
        """Three slow requests cannot starve a healthy fourth configured key."""
        timeouts=[]
        def handler(request):
            """Consume real configured per-request timeouts before the fourth success."""
            timeout=request.extensions['timeout']['read']
            timeouts.append(timeout)
            if len(self.seen)<4:
                self.advance(timeout)
                raise httpx.ReadTimeout('private',request=request)
            self.advance(15)
            return httpx.Response(200,json=completion())
        self.handler=handler
        self.assertTrue(self.generate()['ok'])
        self.assertEqual([key for key,_ in self.seen],[f'Bearer fake-text-secret-{i}' for i in (1,2,3,4)])
        self.assertEqual(timeouts,[60,60,60,60])
        self.assertEqual(self.now,295)
        self.sleep.assert_not_called()

    def test_nested_repair_failure_keeps_cause_without_parent_retry(self):
        """Nested repair errors are not mislabeled HTTP outages or repeated drafts."""
        self.handler=lambda request:httpx.Response(200,json=completion())
        error=ActivityGenerationError('Reading 5 evidence repair: gemini: request retry time budget exhausted; retry later.')
        def validate(value):
            """Simulate a slow, separately bounded scoped content repair failing."""
            self.advance(250)
            raise error
        with self.assertRaises(ActivityGenerationError) as caught:
            ask_json('Retain the completed draft',validate,'Reading 5')
        self.assertIs(caught.exception,error)
        self.assertEqual(len(self.seen),1)
        self.assertNotIn('request failed (ActivityGenerationError)',str(caught.exception))
        self.assertNotIn('completion transport time budget',str(caught.exception))
        self.sleep.assert_not_called()


if __name__=='__main__':
    unittest.main()
