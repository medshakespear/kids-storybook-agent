"""Stable workbook choices shared by the web form and generation pipeline."""

DEFAULT_BOOK_TYPE = 'reading_qcm'
BOOK_TYPES = {
    'reading_qcm': 'Reading passages + QCM',
    'varied_activities': 'Simple varied exercises',
}


def require_book_type(value=DEFAULT_BOOK_TYPE):
    """Reject unknown types before provider calls or background job creation."""
    if not isinstance(value, str) or value not in BOOK_TYPES:
        raise ValueError('book_type must be reading_qcm or varied_activities.')
    return value
