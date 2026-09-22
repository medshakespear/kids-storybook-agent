"""Railway cron entry point for daily batch storybook generation."""

from __future__ import annotations

import json
import os
import random
import sys
import traceback
from datetime import date

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

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set.", flush=True)
        return 2

    with CALENDAR_PATH.open("r", encoding="utf-8") as handle:
        calendar = json.load(handle)
    grade_config = load_grade_config()
    state = load_state()
    count = _daily_count()
    specs = pick_daily_book_specs(calendar, state, count=count)
    successes: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []

    print(f"Starting daily run for {date.today().isoformat()}: {count} books", flush=True)
    for index, spec in enumerate(specs, start=1):
        label = f"{spec['event_name']} / {spec['grade_band']} / {spec['theme']}"
        print(f"[{index}/{count}] Generating {label}", flush=True)
        try:
            story, pdf_path = generate_book(
                theme=f"{spec['event_name']}: {spec['theme']}",
                grade_band=spec["grade_band"],
                grade_config=grade_config,
            )
            band_index = GRADE_BANDS.index(spec["grade_band"])
            update_state(
                state,
                theme=spec["theme"],
                event_name=spec["event_name"],
                grade_band=spec["grade_band"],
                title=story["title"],
                output_path=str(pdf_path.relative_to(pdf_path.parent.parent)),
                grade_band_index=band_index,
            )
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
        persisted, message = commit_state_to_github(STATE_PATH)
        print(("STATE: " if persisted else "STATE WARNING: ") + message, flush=True)

    print("\nDaily run summary", flush=True)
    print(f"  Successful: {len(successes)}", flush=True)
    for item in successes:
        print(f"    - [{item['grade_band']}] {item['title']} ({item['pdf']})", flush=True)
    print(f"  Failed: {len(failures)}", flush=True)
    for item in failures:
        print(f"    - {item['spec']}: {item['error']}", flush=True)

    # A partly successful batch is still useful. Fail only if every book failed.
    return 0 if successes else 1


if __name__ == "__main__":
    sys.exit(main())

