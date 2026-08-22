"""Activity file manager for Auto Commit Bot.

Manages the three .auto-commit/ files:
- activity.json: last activity timestamp, total counts
- state.json: run state, duplicate protection, burst state
- history.json: commit history log

Every commit makes a real change to activity.json (never empty commits).
Never stores authentication tokens or secrets.
"""

import json
import os
from datetime import datetime, date
from typing import Optional


_AUTO_COMMIT_DIR = ".auto-commit"
_ACTIVITY_FILE = os.path.join(_AUTO_COMMIT_DIR, "activity.json")
_STATE_FILE = os.path.join(_AUTO_COMMIT_DIR, "state.json")
_HISTORY_FILE = os.path.join(_AUTO_COMMIT_DIR, "history.json")


def ensure_directory() -> None:
    """Ensure the .auto-commit directory exists."""
    os.makedirs(_AUTO_COMMIT_DIR, exist_ok=True)


def _load_json(filepath: str, default: dict) -> dict:
    """Load a JSON file, returning the default if it doesn't exist or is invalid."""
    if not os.path.exists(filepath):
        return default.copy()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default.copy()


def _save_json(filepath: str, data: dict) -> None:
    """Save data to a JSON file with pretty printing."""
    ensure_directory()
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        f.write("\n")


# ─── Activity File ──────────────────────────────────────────

def load_activity() -> dict:
    """Load the activity file."""
    return _load_json(_ACTIVITY_FILE, {
        "last_activity": None,
        "total_commits": 0,
        "total_active_days": 0,
    })


def update_activity(timestamp: datetime, total_commits: int, total_active_days: int) -> dict:
    """
    Update the activity file with new data.

    This is the file that changes on every commit, ensuring
    no commit is ever empty.
    """
    data = {
        "last_activity": timestamp.isoformat(),
        "total_commits": total_commits,
        "total_active_days": total_active_days,
    }
    _save_json(_ACTIVITY_FILE, data)
    return data


# ─── State File ──────────────────────────────────────────────

def load_state() -> dict:
    """Load the state file."""
    return _load_json(_STATE_FILE, {
        "last_run": None,
        "last_success": None,
        "total_runs": 0,
        "total_commits": 0,
        "seed": None,
        "burst_state": {
            "active": False,
            "end_date": None,
            "multiplier": None,
        },
    })


def update_state(
    run_date: date,
    success: bool,
    commits_this_run: int,
    seed: Optional[int] = None,
    burst_active: bool = False,
    burst_end_date: Optional[date] = None,
    burst_multiplier: Optional[float] = None,
) -> dict:
    """Update the state file after a run."""
    state = load_state()

    last_run = state.get("last_run")
    if last_run and last_run == run_date.isoformat():
        state["commits_today"] = state.get("commits_today", 0) + commits_this_run
    else:
        state["commits_today"] = commits_this_run

    state["last_run"] = run_date.isoformat()
    state["total_runs"] = state.get("total_runs", 0) + 1
    state["total_commits"] = state.get("total_commits", 0) + commits_this_run

    if success:
        state["last_success"] = run_date.isoformat()

    if seed is not None:
        state["seed"] = seed

    state["burst_state"] = {
        "active": burst_active,
        "end_date": burst_end_date.isoformat() if burst_end_date else None,
        "multiplier": burst_multiplier,
    }

    _save_json(_STATE_FILE, state)
    return state


# ─── History File ──────────────────────────────────────────

def load_history() -> dict:
    """Load the history file."""
    return _load_json(_HISTORY_FILE, {"runs": []})


def append_history(
    timestamp: datetime,
    commit_hash: str,
    message: str,
) -> dict:
    """Append a new entry to the history file."""
    history = load_history()

    entry = {
        "timestamp": timestamp.isoformat(),
        "commit": commit_hash,
        "message": message,
    }

    history["runs"].append(entry)

    # Keep history manageable (last 1000 entries)
    if len(history["runs"]) > 1000:
        history["runs"] = history["runs"][-1000:]

    _save_json(_HISTORY_FILE, history)
    return history


# ─── Convenience ──────────────────────────────────────────

def get_files_to_stage() -> list:
    """Return the list of .auto-commit/ files to stage."""
    return [_ACTIVITY_FILE, _STATE_FILE, _HISTORY_FILE]


def get_total_commits() -> int:
    """Get the total number of commits from the state file."""
    state = load_state()
    return state.get("total_commits", 0)


def get_total_active_days() -> int:
    """Get the total number of active days from the activity file."""
    activity = load_activity()
    return activity.get("total_active_days", 0)
