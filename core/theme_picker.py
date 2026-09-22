"""Select upcoming school themes and derive safe webhook inspiration prompts."""

from __future__ import annotations

import random
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import unquote, urlparse


GRADE_BANDS = ["Pre-K-K", "1st-2nd", "3rd-4th", "5th-6th"]


def _occurrence(event: dict[str, Any], today: date) -> date:
    """Return the next annual occurrence of a calendar event."""

    candidate = date(today.year, int(event["month"]), int(event["day"]))
    if candidate < today:
        candidate = date(today.year + 1, int(event["month"]), int(event["day"]))
    return candidate


def find_upcoming_events(
    calendar: dict[str, Any],
    *,
    today: date | None = None,
    min_days: int = 7,
    max_days: int = 28,
) -> list[dict[str, Any]]:
    """Find events occurring between one and four weeks from a date."""

    reference = today or date.today()
    events = calendar.get("events", [])
    matches: list[dict[str, Any]] = []
    for event in events:
        occurrence = _occurrence(event, reference)
        distance = (occurrence - reference).days
        if min_days <= distance <= max_days:
            enriched = dict(event)
            enriched["occurs_on"] = occurrence.isoformat()
            enriched["days_away"] = distance
            matches.append(enriched)
    return sorted(matches, key=lambda item: (item["days_away"], item["event_name"]))


def _recent_pairs(state: dict[str, Any], today: date, days: int = 120) -> set[tuple[str, str]]:
    """Return recently generated theme/grade pairs."""

    cutoff = today - timedelta(days=days)
    pairs: set[tuple[str, str]] = set()
    for item in state.get("generated", []):
        try:
            generated_on = datetime.strptime(item["generated_on"], "%Y-%m-%d").date()
        except (KeyError, TypeError, ValueError):
            continue
        if generated_on >= cutoff:
            pairs.add((item.get("theme", ""), item.get("grade_band", "")))
    return pairs


def pick_grade_bands(
    state: dict[str, Any], count: int, *, grade_bands: list[str] | None = None
) -> list[str]:
    """Choose grade bands in a rotating, evenly spread sequence."""

    bands = grade_bands or GRADE_BANDS
    if not bands:
        raise ValueError("At least one grade band is required.")
    start = (int(state.get("last_grade_band_index", -1)) + 1) % len(bands)
    return [bands[(start + offset) % len(bands)] for offset in range(count)]


def pick_daily_book_specs(
    calendar: dict[str, Any],
    state: dict[str, Any],
    *,
    count: int,
    today: date | None = None,
    rng: random.Random | None = None,
) -> list[dict[str, str]]:
    """Pick a varied batch of upcoming event angles and grade bands."""

    if not 1 <= count <= 20:
        raise ValueError("count must be between 1 and 20")
    reference = today or date.today()
    randomizer = rng or random.SystemRandom()
    events = find_upcoming_events(calendar, today=reference)
    if not events:
        # A dense calendar should avoid this, but use the nearest annual events safely.
        events = sorted(
            (
                {**event, "occurs_on": _occurrence(event, reference).isoformat()}
                for event in calendar.get("events", [])
            ),
            key=lambda item: item["occurs_on"],
        )[:6]
    if not events:
        raise ValueError("calendar.json contains no events")

    bands = pick_grade_bands(state, count)
    recent = _recent_pairs(state, reference)
    candidates: list[dict[str, str]] = []
    for event in events:
        for angle in event.get("theme_angles", []):
            candidates.append(
                {
                    "event_name": event["event_name"],
                    "event_date": event["occurs_on"],
                    "theme": angle,
                }
            )
    if not candidates:
        raise ValueError("Upcoming calendar events contain no theme angles")
    randomizer.shuffle(candidates)

    selections: list[dict[str, str]] = []
    used_in_batch: set[tuple[str, str]] = set()
    for grade_band in bands:
        eligible = [
            item
            for item in candidates
            if (item["theme"], grade_band) not in recent
            and (item["theme"], grade_band) not in used_in_batch
        ]
        pool = eligible or [
            item for item in candidates if (item["theme"], grade_band) not in used_in_batch
        ]
        choice = randomizer.choice(pool or candidates)
        selection = dict(choice)
        selection["grade_band"] = grade_band
        selections.append(selection)
        used_in_batch.add((choice["theme"], grade_band))
    return selections


def build_webhook_inspiration(link: str) -> str:
    """Derive an original niche/angle prompt from URL text without scraping it."""

    parsed = urlparse(link)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("link must be a valid http or https URL")
    raw = unquote(f"{parsed.netloc} {parsed.path}").lower()
    tokens = re.findall(r"[a-z][a-z0-9]+", raw)
    ignored = {
        "www", "com", "org", "net", "product", "products", "item", "shop",
        "teacherspayteachers", "https", "html", "php", "the", "and", "for",
    }
    useful = [token for token in tokens if token not in ignored and not token.isdigit()]
    seed = " ".join(useful[:14]) or parsed.netloc
    return (
        f"Use only this URL-derived niche seed: '{seed}'. Create a fresh educational "
        "storybook angle inspired by the broad topic or classroom skill suggested by "
        "those words. Do not access or scrape the link. Do not copy, paraphrase, or "
        "imitate the referenced product's wording, sequence, characters, page structure, "
        "trade dress, branding, or visual identity. Invent a new premise, plot, cast, "
        "title, teaching approach, and illustration direction."
    )


def pick_webhook_grade_band(state: dict[str, Any]) -> str:
    """Pick the least recently used grade band for a webhook request."""

    last_seen = {band: "" for band in GRADE_BANDS}
    for item in state.get("generated", []):
        band = item.get("grade_band")
        if band in last_seen:
            last_seen[band] = max(last_seen[band], item.get("generated_on", ""))
    return min(GRADE_BANDS, key=lambda band: (last_seen[band], GRADE_BANDS.index(band)))

