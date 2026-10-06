"""Shared end-to-end classroom activity-pack generation pipeline."""

from __future__ import annotations

import json
import re
import tempfile
import logging
import time
from uuid import uuid4
from pathlib import Path
from typing import Any

from core.grade_policy import require_active_grade
from core.providers import text_provider_names, image_provider_name
from core.creative_generator import generate_creative_images as generate_activity_images
from core.creative_generator import strip_creative_art as strip_local_art
from core.reading_generator import generate_reading_pack as generate_activity_pack
from core.creative_layout import build_creative_pdf as build_activity_pdf
from core.calendar_rules import today_in_timezone
from core.paths import GRADE_CONFIG_PATH, OUTPUT_DIR, ensure_runtime_directories


def load_grade_config(path: str | Path = GRADE_CONFIG_PATH) -> dict[str, Any]:
    """Load and return the grade-band configuration."""

    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def slugify(value: str, max_length: int = 64) -> str:
    """Convert text to a safe, compact filename slug."""

    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug[:max_length].rstrip("-") or "activity-pack")


def generate_book(
    *,
    theme: str,
    grade_band: str,
    source_context: str | None = None,
    book_title: str | None = None,
    grade_config: dict[str, Any] | None = None,
    output_dir: str | Path = OUTPUT_DIR,
) -> tuple[dict[str, Any], Path]:
    """Generate reading passages and QCM pages with one consolidated final answer page."""

    require_active_grade(grade_band)
    text_provider_names()
    image_provider_name()
    ensure_runtime_directories()
    config = grade_config or load_grade_config()
    started = time.monotonic()
    title_options = {'book_title':book_title} if book_title is not None else {}
    story = generate_activity_pack(
        theme,
        grade_band,
        config,
        source_context=source_context,
        **title_options,
    )
    designed = time.monotonic()
    logging.getLogger(__name__).info('Design stage complete: %.1fs', designed - started)
    story['page_count'] = len(story['pages']) + 2
    story["generated_on"] = today_in_timezone().isoformat()
    with tempfile.TemporaryDirectory(prefix="activity-pack-") as art_folder:
        generate_activity_images(story, config[grade_band], art_folder)
        illustrated = time.monotonic()
        logging.getLogger(__name__).info('Illustration stage complete: %.1fs', illustrated - designed)
        filename = (
            f"{today_in_timezone().isoformat()}_{slugify(grade_band)}_{slugify(story['title'])}-{uuid4().hex[:12]}.pdf"
        )
        target = Path(output_dir) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as handle:
            staged = Path(handle.name)
        try:
            build_activity_pdf(story, config[grade_band], staged)
            staged.replace(target)
        finally:
            staged.unlink(missing_ok=True)
            strip_local_art(story)
    story['generation_seconds'] = round(time.monotonic() - started, 1)
    logging.getLogger(__name__).info('PDF complete: %s pages; PDF stage %.1fs; total %.1fs',
                                   story['page_count'], time.monotonic() - illustrated, story['generation_seconds'])
    return story, target

