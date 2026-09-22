"""Shared filesystem paths used by the application."""

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
CALENDAR_PATH = BASE_DIR / "calendar.json"
GRADE_CONFIG_PATH = BASE_DIR / "grade_config.json"
STATE_PATH = BASE_DIR / "state.json"
OUTPUT_DIR = BASE_DIR / "output"


def ensure_runtime_directories() -> None:
    """Create directories that are expected to exist at runtime."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

