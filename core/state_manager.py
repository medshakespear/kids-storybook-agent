"""Atomic local state updates and optional GitHub state persistence."""

from __future__ import annotations

import base64
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from core.paths import STATE_PATH
from core.calendar_rules import today_in_timezone


DEFAULT_STATE: dict[str, Any] = {
    "version": 1,
    "last_grade_band_index": -1,
    "generated": [],
}


def load_state(path: str | Path = STATE_PATH) -> dict[str, Any]:
    """Load state JSON, returning a fresh default when the file is absent."""

    state_path = Path(path)
    if not state_path.exists():
        return json.loads(json.dumps(DEFAULT_STATE))
    with state_path.open("r", encoding="utf-8") as handle:
        state = json.load(handle)
    state.setdefault("version", 1)
    state.setdefault("last_grade_band_index", -1)
    state.setdefault("generated", [])
    return state


def save_state(state: dict[str, Any], path: str | Path = STATE_PATH) -> Path:
    """Atomically rewrite the complete state JSON file."""

    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=state_path.parent, delete=False
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(state_path)
    return state_path


def update_state(
    state: dict[str, Any],
    *,
    theme: str,
    event_name: str,
    grade_band: str,
    title: str,
    output_path: str,
    generated_on: str | None = None,
    grade_band_index: int | None = None,
) -> dict[str, Any]:
    """Append one successful generation record and return the mutated state."""

    state.setdefault("generated", []).append(
        {
            "theme": theme,
            "event_name": event_name,
            "grade_band": grade_band,
            "title": title,
            "output_path": output_path,
            "generated_on": generated_on or today_in_timezone().isoformat(),
        }
    )
    if grade_band_index is not None:
        state["last_grade_band_index"] = grade_band_index
    # Keep state compact while retaining two years of rotation history.
    # Retain all catalog records so older books remain discoverable.
    return state


def commit_state_to_github(path: str | Path = STATE_PATH) -> tuple[bool, str]:
    """Commit ``state.json`` through GitHub's Contents API when configured.

    ``GITHUB_TOKEN`` must have Contents read/write permission. The repository is
    taken from ``GITHUB_REPOSITORY`` or Railway's owner/name variables.
    """

    import requests

    token = os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not repository:
        owner = os.environ.get("RAILWAY_GIT_REPO_OWNER")
        name = os.environ.get("RAILWAY_GIT_REPO_NAME")
        if owner and name:
            repository = f"{owner}/{name}"
    if not token or not repository:
        return False, (
            "State was saved locally, but GitHub write-back was skipped. Set "
            "GITHUB_TOKEN and GITHUB_REPOSITORY on the Railway cron service."
        )

    branch = os.environ.get("GITHUB_BRANCH", "main")
    state_path = Path(path)
    api_url = f"https://api.github.com/repos/{repository}/contents/state.json"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    current = requests.get(
        api_url, headers=headers, params={"ref": branch}, timeout=30
    )
    if current.status_code == 200:
        sha = current.json()["sha"]
    elif current.status_code == 404:
        sha = None
    else:
        return False, f"Could not read remote state.json: {current.status_code} {current.text[:300]}"

    payload: dict[str, Any] = {
        "message": f"chore: update activity generation state ({today_in_timezone().isoformat()})",
        "content": base64.b64encode(state_path.read_bytes()).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    result = requests.put(api_url, headers=headers, json=payload, timeout=30)
    if result.status_code not in {200, 201}:
        return False, f"GitHub state write-back failed: {result.status_code} {result.text[:300]}"
    commit_sha = result.json().get("commit", {}).get("sha", "unknown")
    return True, f"Committed state.json to {repository}@{branch} ({commit_sha[:8]})."
