"""Shared end-to-end storybook generation pipeline."""

from __future__ import annotations

import json
import re
import tempfile
from uuid import uuid4
from datetime import date
from pathlib import Path
from typing import Any

from core.providers import validate_providers
from core.image_generator import generate_images
from core.paths import GRADE_CONFIG_PATH, OUTPUT_DIR, ensure_runtime_directories
from core.pdf_builder import build_pdf
from core.story_generator import generate_story


def load_grade_config(path: str | Path = GRADE_CONFIG_PATH) -> dict[str, Any]:
    """Load and return the grade-band configuration."""

    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def slugify(value: str, max_length: int = 64) -> str:
    """Convert text to a safe, compact filename slug."""

    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug[:max_length].rstrip("-") or "storybook")


def generate_book(
    *,
    theme: str,
    grade_band: str,
    source_context: str | None = None,
    grade_config: dict[str, Any] | None = None,
    output_dir: str | Path = OUTPUT_DIR,
) -> tuple[dict[str, Any], Path]:
    """Generate story text, illustrations, and a final printable PDF."""

    validate_providers()
    ensure_runtime_directories()
    config = grade_config or load_grade_config()
    story = generate_story(
        theme,
        grade_band,
        config,
        source_context=source_context,
    )
    with tempfile.TemporaryDirectory(prefix="storybook-") as temporary:
        images = generate_images(story, config[grade_band], temporary)
        filename = (
            f"{date.today().isoformat()}_{slugify(grade_band)}_{slugify(story['title'])}-{uuid4().hex[:12]}.pdf"
        )
        target = Path(output_dir) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as handle:
            staged = Path(handle.name)
        try:
            build_pdf(story, images, config[grade_band], staged)
            staged.replace(target)
        finally:
            staged.unlink(missing_ok=True)
    return story, target

