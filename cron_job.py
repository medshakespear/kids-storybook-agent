"""Railway cron entry point for daily classroom activity packs."""

from __future__ import annotations

import json
import logging
import os
import random
import sys
import traceback
from datetime import date

from core.providers import text_provider_names
from core.calendar_rules import today_in_timezone
from core.delivery import deliver_book, fetch_library_state
from core.paths import CALENDAR_PATH, STATE_PATH
from core.pipeline import generate_book, load_grade_config
from core.state_manager import (
    commit_state_to_github,
    load_state,
    save_state,
    update_state,
)
from core.theme_picker import GRADE_BANDS, pick_daily_book_specs


def _daily_count() -> int:
    """Return a validated daily batch size, defaulting randomly to 6-8."""

    configured = os.environ.get("DAILY_BOOK_COUNT")
    if configured is None:
        return random.randint(6, 8)
    count = int(configured)
    if not 1 <= count <= 20:
        raise ValueError("DAILY_BOOK_COUNT must be between 1 and 20")
    return count


def main() -> int:
    """Run today's batch, continue after per-book errors, and persist results."""

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(levelname)s %(name)s: %(message)s")
    try:
        text_provider_names()
    except ValueError as exc:
        print(f"ERROR: {exc}", flush=True)
        return 2

    with CALENDAR_PATH.open("r", encoding="utf-8") as handle:
        calendar = json.load(handle)
    grade_config = load_grade_config()
    state = fetch_library_state() or load_state()
    count = _daily_count()
    today = today_in_timezone()
    specs = pick_daily_book_specs(calendar, state, count=count, today=today)
    successes: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []

    print(f"Starting daily run for {today.isoformat()} ({os.getenv('BOOK_TIMEZONE', 'UTC')}): {count} activity packs", flush=True)
    for index, spec in enumerate(specs, start=1):
        label = f"{spec['event_name']} / {spec['grade_band']} / {spec['theme']}"
        print(f"  THEME MODE: {spec['selection_mode']}; period {spec['event_date']} to {spec['event_end']}", flush=True)
        print(f"[{index}/{count}] Generating {label}", flush=True)
        try:
            story, pdf_path = generate_book(
                theme=f"{spec['event_name']}: {spec['theme']}",
                grade_band=spec["grade_band"],
                grade_config=grade_config,
            )
            story.update({key: spec[key] for key in ('event_name', 'event_date', 'event_end', 'selection_mode')})
            delivered = deliver_book({**story, "theme": spec["theme"]}, pdf_path)
            if delivered:
                print(f"  DELIVERED: {pdf_path.name}", flush=True)
            else:
                print("  LOCAL ONLY: set BOOK_LIBRARY_URL for dashboard delivery", flush=True)
            band_index = GRADE_BANDS.index(spec["grade_band"])
            update_state(
                state,
                theme=spec["theme"],
                event_name=spec["event_name"],
                grade_band=spec["grade_band"],
                title=story["title"],
                output_path=f"output/{pdf_path.name}",
                grade_band_index=band_index,
                generated_on=today.isoformat(),
            )
            state['generated'][-1].update(resource_type='activity_pack',
                selection_mode=spec['selection_mode'], event_date=spec['event_date'], event_end=spec['event_end'])
            save_state(state, STATE_PATH)
            successes.append(
                {"title": story["title"], "grade_band": spec["grade_band"], "pdf": str(pdf_path)}
            )
            print(f"  SUCCESS: {story['title']} -> {pdf_path}", flush=True)
        except Exception as exc:  # Keep the remaining batch alive.
            failures.append({"spec": label, "error": str(exc)})
            print(f"  FAILED: {label}: {exc}", flush=True)
            traceback.print_exc()

    if successes:
        try:
            persisted, message = commit_state_to_github(STATE_PATH)
        except Exception as exc:
            persisted, message = False, f"GitHub write-back failed: {exc}"
        print(("STATE: " if persisted else "STATE WARNING: ") + message, flush=True)

    print("\nDaily run summary", flush=True)
    print(f"  Successful: {len(successes)}", flush=True)
    for item in successes:
        print(f"    - [{item['grade_band']}] {item['title']} ({item['pdf']})", flush=True)
    print(f"  Failed: {len(failures)}", flush=True)
    for item in failures:
        print(f"    - {item['spec']}: {item['error']}", flush=True)

    # Preserve successful packs but surface any failures in Railway's run status.
    return 0 if successes and not failures else 1


if __name__ == "__main__":
    sys.exit(main())
