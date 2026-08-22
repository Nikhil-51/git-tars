"""Tests for the realism validator."""

from datetime import date, datetime
import pytest

from auto_commit.config import Config
from auto_commit.generator import ActivityGenerator, Schedule, DaySchedule, CommitEntry
from auto_commit.realism import RealismValidator, RealismReport


class TestRealismScoring:
    """Test that the validator correctly scores schedules."""

    def test_realistic_schedule_scores_high(self):
        """A naturally generated schedule should score well."""
        config = Config()
        gen = ActivityGenerator(config, seed=42)
        schedule = gen.generate(start_date=date(2025, 1, 1), num_days=30)

        validator = RealismValidator()
        report = validator.validate(schedule)

        assert report.total_score >= 50  # Should be reasonably realistic

    def test_uniform_schedule_scores_low(self):
        """A schedule with the same count every day should score poorly."""
        days = []
        for i in range(30):
            d = date(2025, 1, 1 + i) if i < 28 else date(2025, 2, i - 27)
            day = DaySchedule(
                date=d,
                commit_count=2,
                is_burst_day=False,
                commits=[
                    CommitEntry(time=datetime(d.year, d.month, d.day, 10, 0), message="chore: update"),
                    CommitEntry(time=datetime(d.year, d.month, d.day, 14, 0), message="chore: update"),
                ]
            )
            days.append(day)

        schedule = Schedule(
            days=days,
            seed=0,
            start_date=days[0].date,
            end_date=days[-1].date,
        )

        validator = RealismValidator()
        report = validator.validate(schedule)

        # Should detect the uniformity
        assert report.total_score < 70

    def test_short_schedule_passes(self):
        """Very short schedules should not fail validation."""
        config = Config()
        gen = ActivityGenerator(config, seed=42)
        schedule = gen.generate(start_date=date(2025, 1, 1), num_days=2)

        validator = RealismValidator()
        report = validator.validate(schedule)

        # Short schedules get a pass
        assert report.total_score >= 50

    def test_report_format(self):
        """The report format method should return a non-empty string."""
        config = Config()
        gen = ActivityGenerator(config, seed=42)
        schedule = gen.generate(start_date=date(2025, 1, 1), num_days=30)

        validator = RealismValidator()
        report = validator.validate(schedule)
        formatted = report.format_report()

        assert len(formatted) > 0
        assert "Activity" in formatted


class TestIndividualChecks:
    """Test individual realism checks."""

    def test_all_inactive_days_detected(self):
        """A schedule with all inactive days should have low inactive ratio score."""
        days = []
        for i in range(14):
            d = date(2025, 1, 1 + i)
            days.append(DaySchedule(date=d, commit_count=0, is_burst_day=False))

        schedule = Schedule(days=days, seed=0, start_date=days[0].date, end_date=days[-1].date)

        validator = RealismValidator()
        report = validator.validate(schedule)

        # Find the inactive ratio check
        inactive_check = next(c for c in report.checks if "gap" in c.name.lower())
        # All inactive should score lower than ideal
        assert inactive_check.score < 1.0

    def test_no_inactive_days_detected(self):
        """A schedule with no inactive days should be flagged."""
        days = []
        for i in range(30):
            d = date(2025, 1, 1 + i) if i < 28 else date(2025, 2, i - 27)
            day = DaySchedule(
                date=d,
                commit_count=1,
                is_burst_day=False,
                commits=[CommitEntry(
                    time=datetime(d.year, d.month, d.day, 10, i % 60),
                    message=f"chore: update {i}"
                )]
            )
            days.append(day)

        schedule = Schedule(days=days, seed=0, start_date=days[0].date, end_date=days[-1].date)

        validator = RealismValidator()
        report = validator.validate(schedule)

        inactive_check = next(c for c in report.checks if "gap" in c.name.lower())
        assert inactive_check.score < 1.0  # 0% inactive is not ideal

    def test_message_diversity_with_identical_messages(self):
        """Repeated identical messages should lower the diversity score."""
        days = []
        for i in range(20):
            d = date(2025, 1, 1 + i)
            day = DaySchedule(
                date=d,
                commit_count=1,
                is_burst_day=False,
                commits=[CommitEntry(
                    time=datetime(d.year, d.month, d.day, 10, 0),
                    message="chore: update"  # Always the same
                )]
            )
            days.append(day)

        schedule = Schedule(days=days, seed=0, start_date=days[0].date, end_date=days[-1].date)

        validator = RealismValidator()
        report = validator.validate(schedule)

        msg_check = next(c for c in report.checks if "message" in c.name.lower())
        assert msg_check.score < 0.8
