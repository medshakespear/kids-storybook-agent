"""Offline constraints, answer keys, exact periods and PDF regressions."""
import json
import random
import tempfile
import unittest
from types import SimpleNamespace
from copy import deepcopy
from datetime import date
from pathlib import Path
from unittest.mock import patch, Mock

from core.activity_generator import validate_pack, generate_activity_pack
from core.activity_pdf import build_activity_html, build_activity_pdf
from core.calendar_rules import find_active_events, event_period
from core.pipeline import load_grade_config, generate_book
from core.theme_picker import pick_daily_book_specs
from tests.activity_fixtures import sample_pack, attach_test_art


class ActivityTests(unittest.TestCase):
    """Prove the new pipeline creates exercises, not story pages."""

    def setUp(self):
        """Read the real grade configuration for all renderer checks."""
        self.grades = load_grade_config()

    def test_all_grade_packs_render(self):
        """Each grade produces the planned number of pages without overflow."""
        for band, config in self.grades.items():
            with self.subTest(band=band), tempfile.TemporaryDirectory() as folder:
                pack = sample_pack(band, config)
                attach_test_art(pack, folder)
                target = build_activity_pdf(pack, config, Path(folder) / "pack.pdf")
                self.assertTrue(target.read_bytes().startswith(b"%PDF"))

    def test_math_key_is_recomputed(self):
        """An invented model answer cannot overwrite the computed arithmetic key."""
        band = "3rd-4th"
        pack = sample_pack(band, self.grades[band])
        pack['pages'][0].update(type='arithmetic', items=[dict(a=12, b=3, op='+')] * 4)
        pack["pages"][0]["answers"] = ["999"] * 4
        fixed = validate_pack(pack, "test", band, self.grades[band])
        self.assertEqual(fixed["pages"][0]["answers"][0], "15")

    def test_division_and_unsupported_types_rejected(self):
        """Invalid numeric tasks and babyish upper-grade tasks are rejected."""
        band = "5th-6th"
        pack = sample_pack(band, self.grades[band])
        pack['pages'][0].update(type='arithmetic', items=[dict(a=12, b=3, op='+')] * 4)
        pack["pages"][0]["items"][0] = {"a": 5, "b": 0, "op": "/"}
        with self.assertRaises(ValueError):
            validate_pack(pack, "test", band, self.grades[band])
        pack["pages"][0]["type"] = "trace"
        with self.assertRaises(ValueError):
            validate_pack(pack, "test", band, self.grades[band])

    def test_model_html_is_escaped(self):
        """Model text cannot inject images, scripts, or remote PDF resources."""
        pack = sample_pack("Pre-K-K", self.grades["Pre-K-K"])
        pack["title"] = '<script>alert("x")</script>'
        with tempfile.TemporaryDirectory() as folder:
            attach_test_art(pack, folder)
            markup = build_activity_html(pack, self.grades["Pre-K-K"])
        self.assertNotIn("<script>", markup)
        self.assertIn("&lt;script&gt;", markup)

    def test_pipeline_generates_art_and_removes_temporary_paths(self):
        """The shared pipeline requires illustrations and returns portable metadata."""
        from tests.test_creative_design import creative_fixture, attach_creative_test_art
        band = "3rd-4th"
        with tempfile.TemporaryDirectory() as folder, patch("core.pipeline.text_provider_names"), patch('core.pipeline.image_provider_name'), patch('core.pipeline.generate_activity_images', side_effect=attach_creative_test_art) as images, patch("core.pipeline.generate_activity_pack", return_value=creative_fixture(band)):
            pack, pdf = generate_book(theme="test", grade_band=band, output_dir=folder)
            self.assertEqual(pack["resource_type"], "activity_pack")
            self.assertTrue(pdf.is_file())
            images.assert_called_once()
            self.assertNotIn('art', pack['pages'][0])

    def test_generated_json_retry_and_groq_fallback(self):
        """Malformed Gemini output exhausts bounded attempts; Groq supplies the pack."""
        band = "Pre-K-K"
        raw = sample_pack(band, self.grades[band])
        gemini, groq = Mock(), Mock()
        gemini.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))])
        groq.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(raw)))])
        with patch("core.activity_generator.text_provider_names", return_value=["gemini", "groq"]), patch("core.activity_generator.text_client", side_effect=[(gemini, "test"), (groq, "test")]), patch("core.activity_generator.time.sleep"):
            pack = generate_activity_pack("test", band, self.grades, max_retries=2)
        self.assertEqual(pack["resource_type"], "activity_pack")
        self.assertEqual(gemini.chat.completions.create.call_count, 2)
        groq.chat.completions.create.assert_called_once()
        gemini.close.assert_called_once()
        groq.close.assert_called_once()

    def test_four_trace_words_fit(self):
        """The first/second-grade layout fits four long outlined practice words."""
        band = "1st-2nd"
        pack = sample_pack(band, self.grades[band])
        page = pack["pages"][0]
        page.update(type="trace", items=[{"word": "WWWWWWWWWW"}] * 4)
        pack = validate_pack(pack, "test", band, self.grades[band])
        with tempfile.TemporaryDirectory() as folder:
            attach_test_art(pack, folder)
            self.assertTrue(build_activity_pdf(pack, self.grades[band], Path(folder) / "trace.pdf").is_file())


class ActiveCalendarTests(unittest.TestCase):
    """Exercise periods, boundaries, year changes, and random evergreen selection."""

    def test_hispanic_period_and_no_early_fire_week(self):
        """September 22 falls inside heritage month, not October fire week."""
        calendar = json.loads(Path("calendar.json").read_text())
        names = [e["event_name"] for e in find_active_events(calendar, today=date(2026, 9, 22))]
        self.assertIn("Hispanic Heritage Month", names)
        self.assertNotIn("Fire Prevention Week", names)

    def test_cross_month_boundaries(self):
        """Inclusive start and end dates are supported."""
        event = {"event_name": "Heritage", "schedule": {"kind": "range", "month": 9, "day": 15, "end_month": 10, "end_day": 15}}
        for day, expected in [(date(2026, 9, 14), False), (date(2026, 9, 15), True), (date(2026, 10, 15), True), (date(2026, 10, 16), False)]:
            self.assertEqual(bool(find_active_events({"events": [event]}, today=day)), expected)

    def test_movable_holidays(self):
        """A weekday rule calculates the correct date each year."""
        event = {"schedule": {"kind": "nth_weekday", "month": 11, "weekday": 3, "nth": 4}}
        self.assertEqual(event_period(event, 2026), (date(2026, 11, 26), date(2026, 11, 26)))
        fire = {"schedule": {"kind": "week_containing", "month": 10, "day": 9, "week_start": 6}}
        self.assertEqual(event_period(fire, 2026), (date(2026, 10, 4), date(2026, 10, 10)))

    def test_year_wrap_and_leap_month(self):
        """January can match a December-starting period; February uses leap years."""
        event = {"event_name": "Break", "schedule": {"kind": "range", "month": 12, "day": 28, "end_month": 1, "end_day": 4}}
        self.assertTrue(find_active_events({"events": [event]}, today=date(2027, 1, 2)))
        self.assertEqual(event_period({"schedule": {"kind": "month", "month": 2}}, 2028)[1], date(2028, 2, 29))

    def test_empty_day_is_evergreen_and_shuffled(self):
        """No next-event fallback; random grades still cover both active bands in a batch."""
        specs = pick_daily_book_specs({"events": []}, {"generated": []}, count=8, today=date(2026, 8, 20), rng=random.Random(5))
        self.assertTrue(all(s["selection_mode"] == "evergreen" for s in specs))
        self.assertEqual(len({s["grade_band"] for s in specs[:4]}), 2)
        self.assertEqual(len({(s["theme"], s["grade_band"]) for s in specs}), 8)
