"""Choose days-7–37 events, matching keyword titles and original reading topics."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from typing import Any
from core.calendar_rules import find_active_events, find_events_in_window, today_in_timezone


from core.grade_policy import ACTIVE_GRADE_BANDS

GRADE_BANDS = list(ACTIVE_GRADE_BANDS)


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

    bands = [band for band in (GRADE_BANDS if grade_bands is None else grade_bands)
             if band in ACTIVE_GRADE_BANDS]
    if not bands:
        raise ValueError("At least one active grade band (3rd-4th or 5th-6th) is required.")
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
    """Choose overlapping days-7–37 events and keyword titles with balanced grades."""

    if not 1 <= count <= 20:
        raise ValueError("count must be between 1 and 20")
    reference = today or today_in_timezone()
    randomizer = rng or random.SystemRandom()
    window = calendar.get('selection_window', {})
    start_offset, end_offset = window.get('start_offset_days',7), window.get('end_offset_days',37)
    events = find_events_in_window(calendar, today=reference, days=end_offset, start_offset=start_offset)
    # Real observances take precedence. Instructional seasons fill empty holiday weeks.
    dated = [e for e in events if e.get('category') != 'seasonal_theme']
    events = dated or events
    window_start, window_end = (reference+timedelta(days=start_offset)).isoformat(), (reference+timedelta(days=end_offset)).isoformat()
    if not events:
        evergreen = calendar.get('evergreen_topics') or [
            {'keyword':'Community Helpers','topic':'How community workers solve everyday problems.'},
            {'keyword':'Garden Detectives','topic':'Plant needs and careful observations.'},
            {'keyword':'Space Explorers','topic':'Space science, evidence and discoveries.'}]
        approaches = ['real-world explanation','comparison','causes and effects','evidence and inference']
        events = [{"event_name":"Everyday classroom skills", "occurs_on":window_start,"ends_on":window_end,
                   "title_keywords":[item['keyword']],
                   "keyword_topics":{item['keyword']:item['topic']},
                   "theme_angles":[f"{item['topic']} Explore {approach} through original readings and QCM." for approach in approaches],
                   "evergreen":True} for item in evergreen]
    bands = []
    while len(bands) < count:
        cycle = list(GRADE_BANDS)
        randomizer.shuffle(cycle)
        bands.extend(cycle)
    bands = bands[:count]
    recent = _recent_pairs(state, reference)
    candidates: list[dict[str, str]] = []
    for event in events:
        titles = event.get('title_keywords') or [event['event_name']]
        if not isinstance(titles,list) or not titles or any(not isinstance(t,str) or not t.strip() or len(t)>52 for t in titles):
            raise ValueError('Calendar title_keywords must contain nonempty text of at most 52 characters')
        contexts = event.get('keyword_topics',{})
        for keyword in dict.fromkeys(titles):
            for angle in event.get('theme_angles', []):
                theme = angle
                if event.get('title_keywords'):
                    theme = f"{keyword}: {contexts.get(keyword, 'Original readings centered on '+keyword)}. {angle}"
                candidates.append({
                    "event_name":event["event_name"], "event_date":event["occurs_on"],
                    "event_end":event.get("ends_on",event["occurs_on"]),
                    "selection_mode":"evergreen" if event.get("evergreen") else 'seasonal_theme' if event.get('category')=='seasonal_theme' else "upcoming_event",
                    "theme":theme,"book_title":keyword,"title_keyword":keyword,
                    "calendar_note":event.get('note',''),
                    "selection_window_start":window_start,"selection_window_end":window_end})
    if not candidates:
        raise ValueError("Eligible calendar events contain no theme angles")
    randomizer.shuffle(candidates)

    # One event per daily batch; grade bands, keyword titles and angles can vary.
    fresh = [item for item in candidates if any((item['theme'], band) not in recent for band in bands)]
    event_names = sorted({(item['event_name'], item['event_date']) for item in (fresh or candidates)})
    batch_event = randomizer.choice(event_names)
    candidates = [item for item in candidates if (item['event_name'], item['event_date']) == batch_event]

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
        event_pool = [c for c in pool if (c['event_name'], c['event_date']) == selected_event]
        selected_title = randomizer.choice(sorted({c['book_title'] for c in event_pool}))
        choice = randomizer.choice([c for c in event_pool if c['book_title']==selected_title])
        selection = dict(choice)
        selection["grade_band"] = grade_band
        selections.append(selection)
        used_in_batch.add((choice["theme"], grade_band))
    return selections


def build_webhook_inspiration(link: str) -> str:
    """Read public page text and frame it as original educational inspiration."""
    from core.reference_reader import read_reference, reference_context
    return reference_context(read_reference(link))


def pick_webhook_grade_band(state: dict[str, Any]) -> str:
    """Pick the least recently used grade band for a webhook request."""

    last_seen = {band: "" for band in GRADE_BANDS}
    for item in state.get("generated", []):
        band = item.get("grade_band")
        if band in last_seen:
            last_seen[band] = max(last_seen[band], item.get("generated_on", ""))
    return min(GRADE_BANDS, key=lambda band: (last_seen[band], GRADE_BANDS.index(band)))

