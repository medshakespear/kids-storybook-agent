"""Compare preserved numerical facts independently of harmless display formatting."""
from collections import Counter
from fractions import Fraction
import re


def numeric_tokens(value: str) -> list[str]:
    """Read explicit numbers using the same display normalization as the math checker."""
    from core.exercise_quality import numeric_display_text
    if not isinstance(value, str):
        return []
    return re.findall(r'(?<![\w.])-?(?:\d+(?:\.\d+)?|\.\d+)(?:/\d+)?(?![\w.])', numeric_display_text(value))


def numeric_values(value: str) -> Counter:
    """Treat 1.00 and 1 as equal while retaining multiplicity, signs and magnitudes."""
    return Counter(Fraction(token) for token in numeric_tokens(value))


def prompt_character_limit(config: dict) -> int:
    """Allow age-appropriate task detail; measured page fit remains the hard layout limit."""
    floor = config.get('minimum_text_pt', config.get('student_font_pt', 11))
    return 220 if floor >= 14 else 320 if floor >= 13 else 480 if floor >= 12 else 600
