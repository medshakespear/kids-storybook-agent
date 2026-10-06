"""Unit tests for calendar rotation and URL inspiration."""

from __future__ import annotations

import unittest
from datetime import date

from core.theme_picker import (
    build_webhook_inspiration,
    find_active_events,
    pick_daily_book_specs,
    pick_grade_bands,
)
from core.calendar_rules import find_events_in_window
import random


class ThemePickerTests(unittest.TestCase):
    """Verify deterministic picker behavior with a small synthetic calendar."""

    def setUp(self) -> None:
        """Create minimal state and calendar fixtures."""

        self.calendar = {
            "events": [
                {
                    "event_name": "Test Day",
                    "month": 2,
                    "day": 15,
                    "schedule": {"kind": "fixed", "month": 2, "day": 15},
                    "theme_angles": ["Angle one", "Angle two", "Angle three"],
                }
            ]
        }
        self.state = {"last_grade_band_index": -1, "generated": []}

    def test_finds_event_only_on_exact_date(self) -> None:
        """A future fixed-date event is never used before its date."""

        self.assertEqual(find_active_events(self.calendar, today=date(2026, 1, 25)), [])
        events = find_active_events(self.calendar, today=date(2026, 2, 15))
        self.assertEqual(events[0]["event_name"], "Test Day")
        self.assertEqual(events[0]["occurs_on"], "2026-02-15")

    def test_grade_rotation_spreads_coverage(self) -> None:
        """Each pair covers both active bands."""

        bands = pick_grade_bands(self.state, 6)
        self.assertEqual(bands, ["3rd-4th", "5th-6th"] * 3)

    def test_daily_specs_include_grade_and_event(self) -> None:
        """Batch specs contain all pipeline inputs."""

        import random

        specs = pick_daily_book_specs(
            self.calendar,
            self.state,
            count=4,
            today=date(2026, 2, 5),
            rng=random.Random(7),
        )
        self.assertEqual(len(specs), 4)
        self.assertTrue(all(item["event_name"] == "Test Day" for item in specs))
        self.assertEqual(len({item["grade_band"] for item in specs}), 2)

    def test_url_seed_forbids_copying(self) -> None:
        """Webhook guidance uses URL words while explicitly requiring originality."""

        guidance = build_webhook_inspiration(
            "https://example.com/Product/Data-Collection-Sheets-For-Goals-123"
        )
        self.assertIn("data collection sheets", guidance)
        self.assertIn("Do not copy", guidance)
        self.assertIn("Do not access or scrape", guidance)

    def test_invalid_url_is_rejected(self) -> None:
        """Non-HTTP URL input is invalid."""

        with self.assertRaises(ValueError):
            build_webhook_inspiration("not-a-url")

    def test_window_boundaries_and_year_rollover(self):
        """Include ongoing periods and day 30, but exclude day 31 and past events."""
        events = [
            {'event_name': name, 'schedule': {'kind':'fixed', 'month':month, 'day':day}, 'theme_angles':['A']}
            for name, month, day in [('Past',12,19), ('Today',12,20), ('Boundary',1,19), ('Outside',1,20)]
        ]
        events.append({'event_name':'Ongoing', 'schedule':{'kind':'month','month':12}, 'theme_angles':['B']})
        found = find_events_in_window({'events':events}, today=date(2026,12,20))
        self.assertEqual({e['event_name'] for e in found}, {'Today','Boundary','Ongoing'})
        self.assertEqual(next(e for e in found if e['event_name']=='Boundary')['occurs_on'], '2027-01-19')

    def test_random_upcoming_selection(self):
        """Different seeds can choose different events without preferring the nearest."""
        calendar = {'events': [
            {'event_name':name, 'schedule':{'kind':'fixed','month':2,'day':day}, 'theme_angles':['Angle '+name]}
            for name,day in [('Near',1),('Later',7)]
        ]}
        choices = {pick_daily_book_specs(calendar, self.state, count=1, today=date(2026,1,25), rng=random.Random(seed))[0]['event_name'] for seed in range(20)}
        self.assertEqual(choices, {'Near','Later'})
        spec = pick_daily_book_specs(calendar, self.state, count=1, today=date(2026,1,25), rng=random.Random(0))[0]
        self.assertEqual(spec['selection_mode'], 'upcoming_event')


if __name__ == "__main__":
    unittest.main()
