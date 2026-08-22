"""Tests for the scheduler module."""

from datetime import date, timedelta
import pytest

from auto_commit.config import Config
from auto_commit.scheduler import check_duplicate, load_state


class TestDuplicateProtection:
    """Test the duplicate execution protection."""

    def test_no_previous_run_allows_execution(self):
        state = {"last_run": None}
        assert check_duplicate(state, date.today()) is False

    def test_same_day_blocks_execution(self):
        today = date.today()
        state = {"last_run": today.isoformat()}
        assert check_duplicate(state, today) is True

    def test_different_day_allows_execution(self):
        yesterday = date.today() - timedelta(days=1)
        state = {"last_run": yesterday.isoformat()}
        assert check_duplicate(state, date.today()) is False

    def test_force_bypasses_duplicate_check(self):
        today = date.today()
        state = {"last_run": today.isoformat()}
        assert check_duplicate(state, today, force=True) is False

    def test_invalid_date_in_state_allows_execution(self):
        state = {"last_run": "not-a-date"}
        assert check_duplicate(state, date.today()) is False

    def test_empty_state_allows_execution(self):
        state = {}
        assert check_duplicate(state, date.today()) is False


class TestStateLoading:
    """Test state file loading."""

    def test_load_nonexistent_state(self, tmp_path):
        state = load_state(str(tmp_path / "nonexistent.json"))
        assert state["last_run"] is None
        assert state["total_runs"] == 0

    def test_load_valid_state(self, tmp_path):
        import json
        state_file = tmp_path / "state.json"
        state_data = {
            "last_run": "2025-01-15",
            "last_success": "2025-01-15",
            "total_runs": 10,
            "total_commits": 25,
            "seed": 42,
            "burst_state": {"active": False, "end_date": None, "multiplier": None}
        }
        state_file.write_text(json.dumps(state_data))

        state = load_state(str(state_file))
        assert state["last_run"] == "2025-01-15"
        assert state["total_runs"] == 10

    def test_load_corrupted_state_returns_default(self, tmp_path):
        state_file = tmp_path / "bad_state.json"
        state_file.write_text("{invalid json")

        state = load_state(str(state_file))
        assert state["last_run"] is None
