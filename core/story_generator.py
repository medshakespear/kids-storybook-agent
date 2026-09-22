"""Generate and validate grade-appropriate story scripts with OpenAI."""

from __future__ import annotations

import json
import os
import random
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openai import OpenAI


class StoryGenerationError(RuntimeError):
    """Raised when a valid story cannot be generated after all retries."""


def _word_count(text: str) -> int:
    """Return a simple whitespace-based word count."""

    return len([word for word in text.strip().split() if word])


def _story_schema(page_min: int, page_max: int) -> dict[str, Any]:
    """Build the strict JSON schema sent to the Chat Completions API."""

    page_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["page_number", "text", "image_prompt"],
        "properties": {
            "page_number": {"type": "integer", "minimum": 1},
            "text": {"type": "string"},
            "image_prompt": {"type": "string"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "title",
            "grade_band",
            "theme",
            "character_name",
            "character_description",
            "pages",
        ],
        "properties": {
            "title": {"type": "string"},
            "grade_band": {"type": "string"},
            "theme": {"type": "string"},
            "character_name": {"type": "string"},
            "character_description": {"type": "string"},
            "pages": {
                "type": "array",
                "minItems": page_min,
                "maxItems": page_max,
                "items": page_schema,
            },
        },
    }


def _validate_and_normalize_story(
    story: dict[str, Any],
    grade_band: str,
    theme: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Validate generation constraints and normalize consistency fields."""

    page_range = config["page_count"]
    word_range = config["words_per_page"]
    pages = story.get("pages")
    if not isinstance(pages, list):
        raise ValueError("The response did not contain a pages list.")
    if not page_range["min"] <= len(pages) <= page_range["max"]:
        raise ValueError(
            f"Expected {page_range['min']}-{page_range['max']} pages; got {len(pages)}."
        )

    description = str(story.get("character_description", "")).strip()
    if not description:
        raise ValueError("character_description must not be empty.")

    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            raise ValueError(f"Page {index} is not an object.")
        page["page_number"] = index
        text = str(page.get("text", "")).strip()
        count = _word_count(text)
        if not word_range["min"] <= count <= word_range["max"]:
            raise ValueError(
                f"Page {index} has {count} words; expected "
                f"{word_range['min']}-{word_range['max']}."
            )
        prompt = str(page.get("image_prompt", "")).strip()
        if not prompt:
            raise ValueError(f"Page {index} has an empty image_prompt.")
        if description not in prompt:
            page["image_prompt"] = f"{description}. {prompt}"
        page["text"] = text

    story["grade_band"] = grade_band
    story["theme"] = theme
    story["title"] = str(story.get("title", "")).strip()
    story["character_name"] = str(story.get("character_name", "")).strip()
    story["character_description"] = description
    if not story["title"] or not story["character_name"]:
        raise ValueError("title and character_name must not be empty.")
    return story


def generate_story(
    theme: str,
    grade_band: str,
    grade_config: dict[str, Any],
    *,
    source_context: str | None = None,
    client: "OpenAI | None" = None,
    max_retries: int = 4,
) -> dict[str, Any]:
    """Generate one validated story using OpenAI Chat Completions.

    Args:
        theme: The event, lesson, or original story angle.
        grade_band: A key from ``grade_config.json``.
        grade_config: The complete grade configuration mapping.
        source_context: Optional originality guidance for webhook requests.
        client: Optional injected OpenAI client, primarily for tests.
        max_retries: Maximum API/validation attempts.

    Returns:
        A validated story dictionary matching the repository's story schema.
    """

    if grade_band not in grade_config:
        raise ValueError(f"Unknown grade band: {grade_band}")
    if not theme.strip():
        raise ValueError("theme must not be empty")

    config = grade_config[grade_band]
    page_min = int(config["page_count"]["min"])
    page_max = int(config["page_count"]["max"])
    word_min = int(config["words_per_page"]["min"])
    word_max = int(config["words_per_page"]["max"])
    if client is None:
        from openai import OpenAI

        openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    else:
        openai_client = client
    model = os.environ.get("OPENAI_TEXT_MODEL", "gpt-4.1-mini")
    originality_context = source_context or (
        "Create an entirely original story. Do not imitate any existing book, "
        "franchise, character, visual identity, wording, or plot structure."
    )

    system_prompt = (
        "You are an expert children's author and elementary literacy specialist. "
        "Return only JSON matching the supplied schema. Keep the story warm, safe, "
        "inclusive, classroom-appropriate, and satisfying. Avoid trademarks, real "
        "product branding, copyrighted characters, violence, and frightening imagery."
    )
    user_prompt = f"""
Write one original illustrated storybook.

Grade band: {grade_band}
Theme or lesson: {theme}
Pages: between {page_min} and {page_max}, not counting the title page.
Words on EVERY page: between {word_min} and {word_max}, inclusive.
Vocabulary guidance: {config['vocabulary_notes']}
Sentence guidance: {config['sentence_complexity_notes']}
Originality guidance: {originality_context}

Create one main character. Make character_description a single, concrete visual
description covering age/species, face, hair/fur, clothing, colors, and one distinctive
accessory. Copy that exact character_description verbatim inside EVERY image_prompt.
Each image_prompt must describe the page action, setting, composition, mood, and lighting;
it must request a clean illustration with no words, letters, captions, logos, or watermark.
Number pages consecutively from 1. Give the story a clear beginning, middle, and ending.
""".strip()

    last_error: Exception | None = None
    validation_feedback = ""
    for attempt in range(max_retries):
        try:
            response = openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_prompt + validation_feedback,
                    },
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "kids_storybook",
                        "strict": True,
                        "schema": _story_schema(page_min, page_max),
                    },
                },
                temperature=0.8,
                max_completion_tokens=7000,
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("OpenAI returned empty story content.")
            story = json.loads(content)
            return _validate_and_normalize_story(story, grade_band, theme, config)
        except Exception as exc:  # API and validation failures share retry behavior.
            last_error = exc
            validation_feedback = (
                f"\n\nThe previous attempt was invalid: {exc}. Regenerate the entire "
                "story and obey every numeric constraint exactly."
            )
            if attempt < max_retries - 1:
                time.sleep(min((2**attempt) + random.random(), 20))

    raise StoryGenerationError(
        f"Could not generate a valid story after {max_retries} attempts: {last_error}"
    ) from last_error
