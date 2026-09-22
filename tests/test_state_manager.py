"""Unit tests for JSON state behavior."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.state_manager import load_state, save_state, update_state


class StateManagerTests(unittest.TestCase):
    """Verify atomic state save/load and record updates."""

    def test_round_trip_and_update(self) -> None:
        """A successful generation record survives a save/load round trip."""

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = load_state(state_path)
            update_state(
                state,
                theme="Helping the garden",
                event_name="Earth Day",
                grade_band="1st-2nd",
                title="The Small Green Team",
                output_path="output/book.pdf",
                generated_on="2026-04-01",
                grade_band_index=1,
            )
            save_state(state, state_path)
            restored = load_state(state_path)
            self.assertEqual(restored["last_grade_band_index"], 1)
            self.assertEqual(restored["generated"][0]["title"], "The Small Green Team")


if __name__ == "__main__":
    unittest.main()

