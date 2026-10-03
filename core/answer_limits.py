"""Bound teacher-facing criteria without imposing student prompt-length limits."""


def answer_character_limit(config: dict) -> int:
    """Allow a short multi-part criterion for upper grades; keep early-grade keys concise."""
    return 400 if config.get('student_font_pt', 15) <= 12 else 180
