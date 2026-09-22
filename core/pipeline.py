"""Shared end-to-end classroom activity-pack generation pipeline."""

from __future__ import annotations

import json
import re
import tempfile
from uuid import uuid4
from pathlib import Path
from typing import Any

from core.providers import text_provider_names, image_provider_name
from core.activity_images import generate_activity_images, strip_local_art
from core.activity_generator import generate_activity_pack
from core.activity_pdf import build_activity_pdf
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
    grade_config: dict[str, Any] | None = None,
    output_dir: str | Path = OUTPUT_DIR,
) -> tuple[dict[str, Any], Path]:
    """Generate illustrated exercises with one consolidated final answer page."""

    text_provider_names()
    image_provider_name()
    ensure_runtime_directories()
    config = grade_config or load_grade_config()
    story = generate_activity_pack(
        theme,
        grade_band,
        config,
        source_context=source_context,
    )
    story["generated_on"] = today_in_timezone().isoformat()
    with tempfile.TemporaryDirectory(prefix="activity-pack-") as art_folder:
        generate_activity_images(story, config[grade_band], art_folder)
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
    return story, target
