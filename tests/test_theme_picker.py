"""Unit tests for calendar rotation and URL inspiration."""

from __future__ import annotations

import unittest
from datetime import date

from core.theme_picker import (
    build_webhook_inspiration,
    find_upcoming_events,
    pick_daily_book_specs,
    pick_grade_bands,
)


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
                    "theme_angles": ["Angle one", "Angle two", "Angle three"],
                }
            ]
        }
        self.state = {"last_grade_band_index": -1, "generated": []}

    def test_finds_event_in_one_to_four_week_window(self) -> None:
        """Events inside the configured horizon are returned."""

        events = find_upcoming_events(self.calendar, today=date(2026, 1, 25))
        self.assertEqual(events[0]["event_name"], "Test Day")
        self.assertEqual(events[0]["occurs_on"], "2026-02-15")

    def test_grade_rotation_spreads_coverage(self) -> None:
        """The first four picks cover every configured band once."""

        bands = pick_grade_bands(self.state, 6)
        self.assertEqual(bands[:4], ["Pre-K-K", "1st-2nd", "3rd-4th", "5th-6th"])
        self.assertEqual(bands[4:], ["Pre-K-K", "1st-2nd"])

    def test_daily_specs_include_grade_and_event(self) -> None:
        """Batch specs contain all pipeline inputs."""

        import random

        specs = pick_daily_book_specs(
            self.calendar,
            self.state,
            count=4,
            today=date(2026, 1, 25),
            rng=random.Random(7),
        )
        self.assertEqual(len(specs), 4)
        self.assertTrue(all(item["event_name"] == "Test Day" for item in specs))
        self.assertEqual(len({item["grade_band"] for item in specs}), 4)

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


if __name__ == "__main__":
    unittest.main()

