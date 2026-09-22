"""Unit tests for story constraint validation."""

from __future__ import annotations

import unittest

from core.story_generator import _validate_and_normalize_story


class StoryValidationTests(unittest.TestCase):
    """Verify hard constraints before image generation begins."""

    def setUp(self) -> None:
        """Create a compact test grade configuration."""

        self.config = {
            "page_count": {"min": 2, "max": 2},
            "words_per_page": {"min": 3, "max": 6},
        }

    def test_character_description_is_reused_verbatim(self) -> None:
        """A missing exact description is prefixed to each image prompt."""

        story = {
            "title": "A Tiny Test",
            "grade_band": "wrong",
            "theme": "wrong",
            "character_name": "Milo",
            "character_description": "Milo is a blue fox wearing a yellow scarf",
            "pages": [
                {"page_number": 9, "text": "Milo finds a map.", "image_prompt": "A sunny path"},
                {"page_number": 8, "text": "Friends walk home together.", "image_prompt": "A warm sunset"},
            ],
        }
        result = _validate_and_normalize_story(
            story, "Pre-K-K", "Map skills", self.config
        )
        description = result["character_description"]
        self.assertTrue(all(description in page["image_prompt"] for page in result["pages"]))
        self.assertEqual([page["page_number"] for page in result["pages"]], [1, 2])
        self.assertEqual(result["grade_band"], "Pre-K-K")

    def test_word_count_violation_is_rejected(self) -> None:
        """Out-of-range page text causes validation failure."""

        story = {
            "title": "Bad Count",
            "character_name": "Milo",
            "character_description": "A blue fox",
            "pages": [
                {"page_number": 1, "text": "Too short", "image_prompt": "A blue fox outdoors"},
                {"page_number": 2, "text": "This count is acceptable", "image_prompt": "A blue fox home"},
            ],
        }
        with self.assertRaises(ValueError):
            _validate_and_normalize_story(story, "Pre-K-K", "Test", self.config)


if __name__ == "__main__":
    unittest.main()

