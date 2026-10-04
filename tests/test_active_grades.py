"""Verify that every public generation path respects the grades 3-6 restriction."""
import random
import unittest
from datetime import date
from unittest.mock import patch
from core.grade_policy import ACTIVE_GRADE_BANDS
from core.pipeline import generate_book, load_grade_config
from core.theme_picker import pick_daily_book_specs, pick_grade_bands, pick_webhook_grade_band
import webhook_server


class ActiveGradeTests(unittest.TestCase):
    """Historical state and retained legacy config cannot re-enable younger bands."""
    def test_daily_event_and_evergreen_batches_use_only_active_bands(self):
        """Balanced batches stay restricted with or without an upcoming event."""
        calendars=[{'events':[]},{'events':[{'event_name':'Test','schedule':{'kind':'fixed','month':10,'day':15},'theme_angles':['Invent','Explore']}]}]
        for calendar in calendars:
            with self.subTest(calendar=calendar):
                specs=pick_daily_book_specs(calendar,{'last_grade_band_index':3},count=8,
                    today=date(2026,10,4),rng=random.Random(4))
                bands=[spec['grade_band'] for spec in specs]
                self.assertEqual(set(bands),set(ACTIVE_GRADE_BANDS))
                self.assertEqual(bands.count('3rd-4th'),4)
                self.assertEqual(bands.count('5th-6th'),4)

    def test_old_state_and_explicit_rotations_cannot_select_disabled_bands(self):
        """Old four-band state indexes wrap safely; custom band lists are filtered."""
        for index in (-1,0,1,2,3):
            self.assertLessEqual(set(pick_grade_bands({'last_grade_band_index':index},6)),set(ACTIVE_GRADE_BANDS))
        self.assertEqual(pick_grade_bands({},2,grade_bands=['Pre-K-K','3rd-4th']),['3rd-4th']*2)
        with self.assertRaises(ValueError):
            pick_grade_bands({},1,grade_bands=['1st-2nd'])
        self.assertIn(pick_webhook_grade_band({'generated':[{'grade_band':'Pre-K-K','generated_on':'2099-01-01'}]}),ACTIVE_GRADE_BANDS)

    def test_webhook_rejects_younger_grades_without_generation(self):
        """Return clear HTTP 400 and the active options before invoking AI."""
        for band in ('Pre-K-K','1st-2nd'):
            with self.subTest(band=band),patch.object(webhook_server,'_authorized',return_value=True),patch.object(webhook_server,'generate_book') as generate:
                response=webhook_server.app.test_client().post('/generate',json={'description':'Create activities','grade_band':band})
                self.assertEqual(response.status_code,400)
                self.assertEqual(response.get_json()['allowed_grade_bands'],list(ACTIVE_GRADE_BANDS))
                generate.assert_not_called()

    def test_direct_pipeline_rejects_younger_grades_before_provider_calls(self):
        """Supplying retained config explicitly cannot bypass the shared pipeline policy."""
        self.assertIn('Pre-K-K',load_grade_config())
        for band in ('Pre-K-K','1st-2nd'):
            with self.subTest(band=band),patch('core.pipeline.text_provider_names') as text,patch('core.pipeline.image_provider_name') as images:
                with self.assertRaisesRegex(ValueError,'only 3rd-4th and 5th-6th'):
                    generate_book(theme='Test',grade_band=band,grade_config=load_grade_config())
                text.assert_not_called();images.assert_not_called()
