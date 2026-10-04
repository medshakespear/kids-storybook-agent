"""Active grade scope shared by daily selection, webhook validation and generation."""

ACTIVE_GRADE_BANDS = ("3rd-4th", "5th-6th")


def require_active_grade(grade_band: str) -> None:
    """Reject disabled grades before spending provider credits or creating files."""
    if grade_band not in ACTIVE_GRADE_BANDS:
        raise ValueError('This agent generates only 3rd-4th and 5th-6th grade packs.')
