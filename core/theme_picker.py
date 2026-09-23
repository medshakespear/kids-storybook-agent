"""Choose random events within 30 days or original evergreen classroom activities."""

from __future__ import annotations

import random
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import unquote, urlparse
from core.calendar_rules import find_active_events, find_events_in_window, today_in_timezone


GRADE_BANDS = ["Pre-K-K", "1st-2nd", "3rd-4th", "5th-6th"]


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
    """Randomly choose events in the next 30 days, with balanced shuffled grades."""

    if not 1 <= count <= 20:
        raise ValueError("count must be between 1 and 20")
    reference = today or today_in_timezone()
    randomizer = rng or random.SystemRandom()
    events = find_events_in_window(calendar, today=reference, days=30)
    if not events:
        topics = ["classroom supply shop", "garden detectives", "animal rescue planning",
                  "invention workshop", "weather observers", "community kindness lab",
                  "playground designers", "recycling team", "library treasure hunt",
                  "space explorers", "pattern museum", "healthy habits investigation"]
        approaches = ["sorting and explaining", "counting and solving", "reading clues",
                      "matching connections", "designing and testing", "planning and reflecting"]
        events = [{"event_name": "Everyday classroom skills", "occurs_on": reference.isoformat(),
                   "theme_angles": [f"{topic}: {approach}" for topic in topics for approach in approaches],
                   "evergreen": True}]
    bands = []
    while len(bands) < count:
        cycle = list(GRADE_BANDS)
        randomizer.shuffle(cycle)
        bands.extend(cycle)
    bands = bands[:count]
    recent = _recent_pairs(state, reference)
    candidates: list[dict[str, str]] = []
    for event in events:
        for angle in event.get("theme_angles", []):
            candidates.append(
                {
                    "event_name": event["event_name"],
                    "event_date": event["occurs_on"],
                    "event_end": event.get("ends_on", event["occurs_on"]),
                    "selection_mode": "evergreen" if event.get("evergreen") else "upcoming_event",
                    "theme": angle,
                }
            )
    if not candidates:
        raise ValueError("Eligible calendar events contain no theme angles")
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
        pool = pool or candidates
        # Sample the event first so events with more angles do not dominate.
        names = sorted({(c['event_name'], c['event_date']) for c in pool})
        selected_event = randomizer.choice(names)
        choice = randomizer.choice([c for c in pool if (c['event_name'], c['event_date']) == selected_event])
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
        "printable exercise pack inspired by the broad topic or classroom skill suggested by "
        "those words. Do not access or scrape the link. Do not copy, paraphrase, or "
        "imitate the referenced product's wording, sequence, characters, page structure, "
        "trade dress, branding, or visual identity. Invent original student tasks, "
        "examples, answer keys, title, teaching approach, and visual layout. "
        "Produce complete usable exercises, not a story or a list of activity ideas. "
        "The output is a static PDF: do not promise editable fields or personalized names."
    )


def pick_webhook_grade_band(state: dict[str, Any]) -> str:
    """Pick the least recently used grade band for a webhook request."""

    last_seen = {band: "" for band in GRADE_BANDS}
    for item in state.get("generated", []):
        band = item.get("grade_band")
        if band in last_seen:
            last_seen[band] = max(last_seen[band], item.get("generated_on", ""))
    return min(GRADE_BANDS, key=lambda band: (last_seen[band], GRADE_BANDS.index(band)))
