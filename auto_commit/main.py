"""CLI entry point for Auto Commit Bot.

Supports:
  python -m auto_commit.main                   # Normal execution
  python -m auto_commit.main --preview         # Statistics + grid
  python -m auto_commit.main --dry-run         # Full schedule, no git
  python -m auto_commit.main --test            # Run test suite
  python -m auto_commit.main --force           # Bypass duplicate check
  python -m auto_commit.main --summary         # GitHub Actions summary
  python -m auto_commit.main --days 30         # Schedule length
  python -m auto_commit.main --seed 42         # Reproducible
"""

import argparse
import json
import os
import sys
import subprocess
from datetime import datetime, date, timedelta
from typing import Optional

from auto_commit import __version__
from auto_commit.config import load_config, Config, ConfigError
from auto_commit.generator import ActivityGenerator, Schedule
from auto_commit.realism import RealismValidator
from auto_commit.scheduler import make_decision, get_current_datetime
from auto_commit import activity as activity_mgr
from auto_commit import git as git_ops
from auto_commit.safety import SafetyValidator


# Ensure UTF-8 output on Windows
import io
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# --- Display helpers ---

def _header(text: str) -> str:
    return f"\n{text}\n{'-' * 40}\n"


def _format_date(d: date) -> str:
    return d.strftime("%b %d")


def _format_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


# ─── Preview Mode ────────────────────────────────────────

def cmd_preview(config: Config, args: argparse.Namespace) -> int:
    """Generate and display a schedule preview with statistics and grid."""
    days = args.days or 30
    seed = args.seed
    start_date = date.today()

    generator = ActivityGenerator(config, seed=seed)
    schedule = generator.generate(start_date=start_date, num_days=days)

    # Run realism validation
    validator = RealismValidator()
    report = validator.validate(schedule)

    # Regenerate if needed
    attempt = 1
    max_attempts = config.realism.max_regeneration_attempts
    while report.total_score < config.realism.min_score and attempt < max_attempts:
        attempt += 1
        new_seed = generator.seed + attempt
        generator = ActivityGenerator(config, seed=new_seed)
        schedule = generator.generate(start_date=start_date, num_days=days)
        schedule.generation_attempt = attempt
        report = validator.validate(schedule)

    # Display statistics
    print(_header("Auto Commit — Preview"))

    print(f"  Date range:              {_format_date(schedule.start_date)} → {_format_date(schedule.end_date)}")
    print(f"  Total days:              {schedule.total_days}")
    print(f"  Active days:             {schedule.active_days}")
    print(f"  Inactive days:           {schedule.inactive_days}")
    print(f"  Total commits:           {schedule.total_commits}")
    print(f"  Avg per active day:      {schedule.avg_commits_per_active_day:.2f}")

    highest = schedule.highest_activity_day
    if highest:
        print(f"  Highest activity day:    {_format_date(highest.date)} ({highest.commit_count} commits)")

    print(f"  Longest inactive streak: {schedule.longest_inactive_streak} days")
    print(f"  Longest active streak:   {schedule.longest_active_streak} days")
    print(f"  Weekend activity:        {schedule.weekend_activity_pct:.0f}%")
    print(f"  Random seed:             {schedule.seed}")
    if schedule.generation_attempt > 1:
        print(f"  Generation attempts:     {schedule.generation_attempt}")

    # Display contribution grid
    print(_header("Contribution Grid"))
    _print_contribution_grid(schedule)

    # Display realism report
    print(_header("Realism Validation"))
    print(report.format_report())

    return 0


def _print_contribution_grid(schedule: Schedule) -> None:
    """Print a GitHub-style contribution grid using Unicode characters."""
    # Intensity levels
    levels = [" ", "░", "▒", "▓", "█"]

    def intensity(count: int) -> str:
        if count == 0:
            return levels[0]
        elif count <= 2:
            return levels[1]
        elif count <= 4:
            return levels[2]
        elif count <= 6:
            return levels[3]
        else:
            return levels[4]

    # Group by weeks (columns) and days (rows, Mon=0 to Sun=6)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    # Build a grid: rows = day of week, columns = week number
    if not schedule.days:
        print("  (empty schedule)")
        return

    first_day = schedule.days[0].date
    grid = {}  # (week_offset, weekday) -> commit_count

    for day in schedule.days:
        week_offset = (day.date - first_day).days // 7
        weekday = day.date.weekday()
        grid[(week_offset, weekday)] = day.commit_count

    max_week = max(w for w, _ in grid.keys()) if grid else 0

    # Print month labels
    months_shown = set()
    month_header = "      "
    for w in range(max_week + 1):
        d = first_day + timedelta(weeks=w)
        month_label = d.strftime("%b")
        if month_label not in months_shown:
            month_header += month_label + " "
            months_shown.add(month_label)
        else:
            month_header += "  "
    print(month_header)

    # Print rows (one per day of week)
    for weekday in range(7):
        label = day_names[weekday]
        row = f"  {label} "
        for w in range(max_week + 1):
            count = grid.get((w, weekday), -1)
            if count == -1:
                row += "  "  # Outside schedule range
            else:
                row += intensity(count) + " "
        print(row)

    # Legend
    print(f"\n  Legend: {levels[0]}=0  {levels[1]}=1-2  {levels[2]}=3-4  {levels[3]}=5-6  {levels[4]}=7+")


# ─── Dry Run Mode ────────────────────────────────────────

def cmd_dry_run(config: Config, args: argparse.Namespace) -> int:
    """Generate the schedule and display it without making any git changes."""
    days = args.days or 30
    seed = args.seed
    start_date = date.today()

    generator = ActivityGenerator(config, seed=seed)
    schedule = generator.generate(start_date=start_date, num_days=days)

    # Run realism validation
    validator = RealismValidator()
    report = validator.validate(schedule)

    print(_header("Auto Commit — Dry Run"))
    print(f"  Seed: {schedule.seed}")
    print()

    # Table header
    print(f"  {'Date':<14} {'Commits':<10} {'Times'}")
    print(f"  {'-' * 14} {'-' * 10} {'-' * 30}")

    for day in schedule.days:
        date_str = _format_date(day.date)
        day_name = day.date.strftime("%a")
        label = f"{date_str} {day_name}"

        if day.is_active:
            times = ", ".join(_format_time(c.time) for c in day.commits)
            burst_marker = " 🔥" if day.is_burst_day else ""
            print(f"  {label:<14} {day.commit_count:<10} {times}{burst_marker}")
        else:
            print(f"  {label:<14} {'0':<10} -")

    # Summary
    print()
    print(f"  Total commits: {schedule.total_commits}")
    print(f"  Active days:   {schedule.active_days}/{schedule.total_days}")
    print(f"  Activity score: {report.total_score}/100")
    print()
    print("  No git changes were made (dry run).")

    return 0


# ─── Test Mode ────────────────────────────────────────────

def cmd_test(config: Config, args: argparse.Namespace) -> int:
    """Run internal diagnostics. Never pushes to GitHub."""
    print(_header("Auto Commit — Test Mode"))
    errors = []

    # Test 1: Config validation
    print("  Testing configuration... ", end="")
    try:
        from auto_commit.config import validate_config
        validate_config(config)
        print("✓")
    except Exception as e:
        print(f"✗ ({e})")
        errors.append(f"Config: {e}")

    # Test 2: Generator
    print("  Testing generator... ", end="")
    try:
        gen = ActivityGenerator(config, seed=12345)
        sched = gen.generate(start_date=date.today(), num_days=14)
        assert sched.total_days == 14
        print(f"✓ ({sched.total_commits} commits in 14 days)")
    except Exception as e:
        print(f"✗ ({e})")
        errors.append(f"Generator: {e}")

    # Test 3: Seed reproducibility
    print("  Testing seed reproducibility... ", end="")
    try:
        gen1 = ActivityGenerator(config, seed=99999)
        gen2 = ActivityGenerator(config, seed=99999)
        s1 = gen1.generate(start_date=date(2025, 1, 1), num_days=30)
        s2 = gen2.generate(start_date=date(2025, 1, 1), num_days=30)
        counts1 = [d.commit_count for d in s1.days]
        counts2 = [d.commit_count for d in s2.days]
        assert counts1 == counts2, "Schedules differ with same seed"
        print("✓")
    except Exception as e:
        print(f"✗ ({e})")
        errors.append(f"Seed: {e}")

    # Test 4: Realism validator
    print("  Testing realism validator... ", end="")
    try:
        validator = RealismValidator()
        gen = ActivityGenerator(config, seed=42)
        sched = gen.generate(start_date=date(2025, 6, 1), num_days=30)
        report = validator.validate(sched)
        print(f"✓ (score: {report.total_score}/100)")
    except Exception as e:
        print(f"✗ ({e})")
        errors.append(f"Realism: {e}")

    # Test 5: Message generation
    print("  Testing message generation... ", end="")
    try:
        from auto_commit.messages import MessageGenerator
        mg = MessageGenerator()
        msgs = mg.generate_batch(20)
        # No consecutive duplicates
        for i in range(1, len(msgs)):
            assert msgs[i] != msgs[i - 1], f"Consecutive duplicate: {msgs[i]}"
        unique = len(set(msgs))
        print(f"✓ ({unique}/20 unique)")
    except Exception as e:
        print(f"✗ ({e})")
        errors.append(f"Messages: {e}")

    # Test 6: Activity file management
    print("  Testing activity files... ", end="")
    try:
        activity_mgr.ensure_directory()
        activity = activity_mgr.load_activity()
        state = activity_mgr.load_state()
        history = activity_mgr.load_history()
        assert isinstance(activity, dict)
        assert isinstance(state, dict)
        assert isinstance(history, dict)
        assert "runs" in history
        print("✓")
    except Exception as e:
        print(f"✗ ({e})")
        errors.append(f"Activity: {e}")

    # Test 7: Safety validator (non-destructive)
    print("  Testing safety validator... ", end="")
    try:
        safety = SafetyValidator(config.safety, config.branch)
        # Just verify it can be instantiated and the method exists
        assert hasattr(safety, 'validate')
        print("✓")
    except Exception as e:
        print(f"✗ ({e})")
        errors.append(f"Safety: {e}")

    # Test 8: Duplicate protection
    print("  Testing duplicate protection... ", end="")
    try:
        from auto_commit.scheduler import check_duplicate
        mock_state = {"last_run": date.today().isoformat()}
        assert check_duplicate(mock_state, date.today()) is True
        assert check_duplicate(mock_state, date.today(), force=True) is False
        assert check_duplicate({"last_run": None}, date.today()) is False
        print("✓")
    except Exception as e:
        print(f"✗ ({e})")
        errors.append(f"Duplicate: {e}")

    # Summary
    print()
    if errors:
        print(f"  ✗ {len(errors)} test(s) failed:")
        for err in errors:
            print(f"    - {err}")
        return 1
    else:
        print("  ✓ All tests passed")
        print()
        print("  No git changes were made (test mode).")
        return 0


# ─── Summary Mode ─────────────────────────────────────────

def cmd_summary(config: Config, args: argparse.Namespace) -> int:
    """Generate a GitHub Actions summary."""
    state = activity_mgr.load_state()
    activity = activity_mgr.load_activity()

    print("## Auto Commit Bot — Run Summary")
    print()
    print(f"- **Last run**: {state.get('last_run', 'N/A')}")
    print(f"- **Total runs**: {state.get('total_runs', 0)}")
    print(f"- **Total commits**: {state.get('total_commits', 0)}")
    print(f"- **Last activity**: {activity.get('last_activity', 'N/A')}")
    print(f"- **Active days**: {activity.get('total_active_days', 0)}")

    return 0


# ─── Normal Execution ─────────────────────────────────────

def cmd_run(config: Config, args: argparse.Namespace) -> int:
    """
    Normal execution: decide, commit, push.

    1. Load config and state
    2. Make scheduling decision
    3. Run safety checks
    4. Update .auto-commit/ files
    5. Stage, commit, push
    """
    if not config.enabled:
        print("Auto Commit is disabled in config.json. Set 'enabled' to true.")
        return 0

    force = args.force
    print(_header("Auto Commit Bot"))

    # Sync with remote first
    git_ops.sync_with_remote(config.branch)

    # Make scheduling decision
    print("  Making scheduling decision...", end=" ")
    decision = make_decision(config, force=force)
    print(decision.reason)

    if not decision.should_commit:
        return 0

    # Safety checks
    print("  Running safety checks...", end=" ")
    safety = SafetyValidator(config.safety, config.branch)
    safety_result = safety.validate()
    if not safety_result.safe:
        print("FAILED")
        print()
        print(safety_result.format_report())
        print()
        print("  No commit was created.")
        return 1
    print("✓")

    # Execute commits
    now = get_current_datetime(config.timezone)
    total_state_commits = activity_mgr.get_total_commits()
    total_active_days = activity_mgr.get_total_active_days()

    commits_made = 0
    last_commit_hash = ""

    for i, (commit_time, message) in enumerate(zip(decision.times, decision.messages)):
        print(f"  Creating & pushing commit {i + 1}/{decision.commit_count}...", end=" ")

        commits_made += 1
        activity_mgr.update_activity(
            timestamp=now,
            total_commits=total_state_commits + commits_made,
            total_active_days=total_active_days + (1 if commits_made == 1 else 0),
        )

        activity_mgr.update_state(
            run_date=now.date(),
            success=True,
            commits_this_run=1,
            seed=decision.seed,
            burst_active=decision.is_burst,
        )

        try:
            git_ops.stage_files(activity_mgr.get_files_to_stage())
            commit_info = git_ops.create_commit(
                message=message,
                commit_date=commit_time,
            )
            last_commit_hash = commit_info.short_hash
            activity_mgr.append_history(
                timestamp=now,
                commit_hash=last_commit_hash,
                message=message,
            )
            git_ops.push(config.branch)
            print(f"✓ [{commit_info.short_hash}] {message}")
        except git_ops.GitError as e:
            print(f"✗ (failed: {e})")
            return 1

    print()
    print(f"  ✓ {commits_made} commit(s) created and pushed.")
    return 0


# ─── CLI ──────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="auto_commit",
        description="Auto Commit Bot — Realistic automated commit activity generator",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"Auto Commit Bot v{__version__}",
    )
    parser.add_argument(
        "--preview", action="store_true",
        help="Show schedule preview with statistics and contribution grid",
    )
    parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Generate and display schedule without making git changes",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Run internal diagnostics (no git changes)",
    )
    parser.add_argument(
        "--summary", action="store_true",
        help="Generate GitHub Actions summary",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass duplicate check for the current day",
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="Number of days for the schedule (default: 30)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducible schedules",
    )
    parser.add_argument(
        "--config", type=str, default="config.json",
        help="Path to config file (default: config.json)",
    )
    return parser


def main(argv=None) -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # Load configuration
    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1

    # Override seed from CLI if provided
    if args.seed is not None:
        # Create a new config with the CLI seed
        config = Config(
            enabled=config.enabled,
            branch=config.branch,
            timezone=config.timezone,
            activity=config.activity,
            development_hours_start=config.development_hours_start,
            development_hours_end=config.development_hours_end,
            time_periods=config.time_periods,
            burst=config.burst,
            session=config.session,
            seed=args.seed,
            commit_prefix=config.commit_prefix,
            realism=config.realism,
            safety=config.safety,
        )

    # Route to the appropriate command
    if args.preview:
        return cmd_preview(config, args)
    elif args.dry_run:
        return cmd_dry_run(config, args)
    elif args.test:
        return cmd_test(config, args)
    elif args.summary:
        return cmd_summary(config, args)
    else:
        return cmd_run(config, args)


if __name__ == "__main__":
    sys.exit(main())
