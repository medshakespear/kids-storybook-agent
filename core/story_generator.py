"""Generate and validate grade-appropriate story scripts with configurable text providers."""

from __future__ import annotations

import json
import logging
import random
import time
from typing import TYPE_CHECKING, Any

from core.providers import text_provider_names, text_client, safe_api_error

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

    if not isinstance(story, dict):
        raise ValueError("Story must be a JSON object.")
    for field in ("title", "character_name", "character_description"):
        if not isinstance(story.get(field), str) or not story[field].strip():
            raise ValueError(f"{field} must be a nonempty string.")
    if len(story["character_description"]) > 400:
        raise ValueError("character_description must be at most 400 characters.")
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
        for field in ("text", "image_prompt"):
            if not isinstance(page.get(field), str):
                raise ValueError(f"Page {index} {field} must be a string.")
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
    """Generate one validated story using the selected provider and optional Groq fallback.

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
    providers = ["injected"] if client is not None else text_provider_names()
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
accessory, in at most 400 characters. Keep each image_prompt under 1000 characters. Copy that exact character_description verbatim inside EVERY image_prompt.
Each image_prompt must describe the page action, setting, composition, mood, and lighting;
it must request a clean illustration with no words, letters, captions, logos, or watermark.
Number pages consecutively from 1. Give the story a clear beginning, middle, and ending.
""".strip()

    system_prompt += "\nRequired JSON schema: " + json.dumps(_story_schema(page_min, page_max))
    if max_retries < 1:
        raise ValueError("max_retries must be positive")
    errors = []
    for provider in providers:
        api, model = (client, "test-model") if client is not None else text_client(provider)
        logging.getLogger(__name__).info("Using story provider %s, model %s", provider, model)
        feedback = ""
        try:
            for attempt in range(max_retries):
                try:
                    response = api.chat.completions.create(
                        model=model,
                        messages=[{"role": "system", "content": system_prompt},
                                  {"role": "user", "content": user_prompt + feedback}],
                        response_format={"type": "json_object"},
                        temperature=0.8,
                        max_completion_tokens=8000,
                    )
                    content = response.choices[0].message.content
                    if not content:
                        raise ValueError("Provider returned empty story content.")
                    story = _validate_and_normalize_story(json.loads(content), grade_band, theme, config)
                    logging.getLogger(__name__).info("Story generated with %s (%s)", provider, model)
                    return story
                except (ValueError, IndexError, TypeError) as exc:
                    error = "Story JSON or grade constraints failed validation."
                    feedback = (f"\nPrevious response failed validation: {exc}. "
                                "Regenerate complete JSON satisfying every constraint.")
                except Exception as exc:
                    failure = safe_api_error(provider, exc, model=model)
                    error = str(failure)
                    if not failure.retryable:
                        break
                if attempt < max_retries - 1:
                    time.sleep(min(2 ** attempt + random.random(), 20))
            errors.append(error)
            logging.getLogger(__name__).warning("%s exhausted; trying next configured provider if available", provider)
        finally:
            if client is None:
                api.close()
    raise StoryGenerationError("Could not generate a valid story. " + "; ".join(errors)) from None
