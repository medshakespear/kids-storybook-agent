"""Identify a complete printed calculation without treating word-problem fragments as totals."""
import re
from core.exercise_quality import numeric_display_text, normalize_calculation


def compound_calculation(expression: str) -> bool:
    """Detect multiple explicit arithmetic results without silently discarding either."""
    if not isinstance(expression,str):return False
    parts=re.split(r'\s+and\s+|\s*;\s*',expression.strip(),flags=re.I)
    if not 2<=len(parts)<=4:return False
    try:
        for part in parts:normalize_calculation(part)
    except ValueError:return False
    return True


def standalone_arithmetic(prompt: str) -> str | None:
    """Return validated standalone arithmetic; never infer operations from prose quantities."""
    if not isinstance(prompt,str):
        return None
    value=numeric_display_text(prompt).strip()
    value=re.sub(r'\s*(?:[.!?]\s*)?(?:show your work|explain your answer)\.?\s*$', '', value,flags=re.I)
    match=re.fullmatch(r'\s*(?:(?:what is|calculate|compute|solve|evaluate|find the value of)\s+)?'
                      r'([\d.()+−–×÷*/xX%\s-]+?)\s*(?:=\s*\?)?\s*[?.!]?\s*',value,re.I)
    if not match:
        return None
    # Restricted normalization validates the whole expression; invalid printed
    # arithmetic must not become a successful unrelated declared calculation.
    return normalize_calculation(match[1])
