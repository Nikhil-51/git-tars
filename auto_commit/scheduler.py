"""Daily decision engine for Auto Commit Bot.

Determines whether the bot should create commits right now,
based on the probabilistic model, current time, and state.
Used by GitHub Actions runs to make the go/no-go decision.
"""

import hashlib
import json
import os
import random as _random
from dataclasses import dataclass
from datetime import datetime, date, timezone, timedelta
from typing import List, Optional

from auto_commit.config import Config
from auto_commit.generator import ActivityGenerator, Schedule
from auto_commit.realism import RealismValidator


def _get_deterministic_day_seed(d: date) -> int:
    """Generate a truly deterministic integer seed for a given date across Python processes."""
    seed_str = f"{d.year:04d}-{d.month:02d}-{d.day:02d}-auto-commit"
    return int(hashlib.md5(seed_str.encode("utf-8")).hexdigest(), 16) % (2**31)


@dataclass
class ScheduleDecision:
    """Result of the scheduler's decision for the current run."""
    should_commit: bool
    commit_count: int
    is_burst: bool
    times: List[datetime]
    messages: List[str]
    seed: int
    reason: str


def get_current_datetime(timezone_str: str) -> datetime:
    """
    Get the current datetime in the configured timezone.

    Uses a simple UTC offset approach without requiring pytz.
    Common timezone offsets are handled; falls back to UTC.
    """
    tz_offsets = {
        "Asia/Kolkata": timedelta(hours=5, minutes=30),
        "Asia/Calcutta": timedelta(hours=5, minutes=30),
        "US/Eastern": timedelta(hours=-5),
        "US/Central": timedelta(hours=-6),
        "US/Mountain": timedelta(hours=-7),
        "US/Pacific": timedelta(hours=-8),
        "Europe/London": timedelta(hours=0),
        "Europe/Berlin": timedelta(hours=1),
        "Europe/Paris": timedelta(hours=1),
        "Asia/Tokyo": timedelta(hours=9),
        "Asia/Shanghai": timedelta(hours=8),
        "Australia/Sydney": timedelta(hours=10),
        "UTC": timedelta(hours=0),
    }

    offset = tz_offsets.get(timezone_str, timedelta(hours=0))
    utc_now = datetime.now(timezone.utc)
    local_now = utc_now + offset
    return local_now.replace(tzinfo=None)


def load_state(state_path: str = ".auto-commit/state.json") -> dict:
    """Load the bot's state file."""
    if not os.path.exists(state_path):
        return {
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
        }

    try:
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {
            "last_run": None,
            "last_success": None,
            "total_runs": 0,
            "total_commits": 0,
            "seed": None,
            "burst_state": {"active": False, "end_date": None, "multiplier": None},
        }


def check_duplicate(state: dict, today: date, force: bool = False, total_scheduled: Optional[int] = None) -> bool:
    """
    Check if the bot has already completed its scheduled commits for today.

    Returns True if it's a duplicate (all scheduled commits completed), False if it should proceed.
    """
    if force:
        return False

    last_run = state.get("last_run")
    if last_run is None:
        return False

    try:
        last_run_date = date.fromisoformat(last_run)
        if last_run_date != today:
            return False

        if total_scheduled is not None:
            completed = state.get("commits_today", 0)
            return completed >= total_scheduled

        return True
    except (ValueError, TypeError):
        return False


def make_decision(
    config: Config,
    force: bool = False,
    state_path: str = ".auto-commit/state.json",
) -> ScheduleDecision:
    """
    Make the scheduling decision for the current run.

    1. Load state and check for duplicate execution
    2. Generate today's schedule using the probabilistic model
    3. Determine which scheduled commits are due and haven't been completed yet
    4. Return the decision
    """
    now = get_current_datetime(config.timezone)
    today = now.date()

    # Load state
    state = load_state(state_path)

    # Generate today's schedule using a date-based seed for intra-day consistency
    day_seed = config.seed
    if day_seed is None:
        day_seed = _get_deterministic_day_seed(today)

    generator = ActivityGenerator(config, seed=day_seed)
    schedule = generator.generate(start_date=today, num_days=1)
    day = schedule.days[0]

    if not day.is_active:
        return ScheduleDecision(
            should_commit=False,
            commit_count=0,
            is_burst=day.is_burst_day,
            times=[],
            messages=[],
            seed=day_seed,
            reason="No activity scheduled for today.",
        )

    # Check how many commits have already been created today
    completed_today = 0
    if state.get("last_run") == today.isoformat():
        completed_today = state.get("commits_today", 0)

    if not force and completed_today >= len(day.commits):
        return ScheduleDecision(
            should_commit=False,
            commit_count=0,
            is_burst=day.is_burst_day,
            times=[],
            messages=[],
            seed=state.get("seed", 0),
            reason=f"All {len(day.commits)} scheduled commit(s) for today have been completed.",
        )

    # Determine remaining commits for today
    remaining_commits = day.commits[completed_today:] if not force else day.commits

    if not remaining_commits:
        return ScheduleDecision(
            should_commit=False,
            commit_count=0,
            is_burst=day.is_burst_day,
            times=[],
            messages=[],
            seed=day_seed,
            reason=f"All {len(day.commits)} scheduled commit(s) for today have been completed.",
        )

    # Execute up to 5 pending commits per run so every run produces a high-volume contribution batch
    batch_size = min(len(remaining_commits), 5)
    commits_due = [c.time for c in remaining_commits[:batch_size]]
    messages_due = [c.message for c in remaining_commits[:batch_size]]

    if not commits_due:
        next_time = remaining_commits[0].time.strftime("%H:%M") if remaining_commits else "later"
        return ScheduleDecision(
            should_commit=False,
            commit_count=0,
            is_burst=day.is_burst_day,
            times=[],
            messages=[],
            seed=day_seed,
            reason=f"Next commit scheduled for {next_time}.",
        )

    total_commits = len(day.commits) if not force else len(commits_due)
    return ScheduleDecision(
        should_commit=True,
        commit_count=len(commits_due),
        is_burst=day.is_burst_day,
        times=commits_due,
        messages=messages_due,
        seed=day_seed,
        reason=f"Executing {len(commits_due)} due commit(s) ({completed_today + len(commits_due)}/{total_commits} completed today).",
    )
