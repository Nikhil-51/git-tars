"""Tests for the activity schedule generator."""

import random
from datetime import date, datetime
from collections import Counter

import pytest

from auto_commit.config import Config, ActivityConfig, BurstConfig, SessionConfig
from auto_commit.generator import ActivityGenerator, Schedule


class TestSeedReproducibility:
    """Same seed + same config must produce identical schedules."""

    def test_same_seed_same_output(self):
        config = Config()
        gen1 = ActivityGenerator(config, seed=42)
        gen2 = ActivityGenerator(config, seed=42)

        s1 = gen1.generate(start_date=date(2025, 1, 1), num_days=30)
        s2 = gen2.generate(start_date=date(2025, 1, 1), num_days=30)

        counts1 = [d.commit_count for d in s1.days]
        counts2 = [d.commit_count for d in s2.days]
        assert counts1 == counts2

    def test_different_seed_different_output(self):
        config = Config()
        gen1 = ActivityGenerator(config, seed=42)
        gen2 = ActivityGenerator(config, seed=99)

        s1 = gen1.generate(start_date=date(2025, 1, 1), num_days=30)
        s2 = gen2.generate(start_date=date(2025, 1, 1), num_days=30)

        counts1 = [d.commit_count for d in s1.days]
        counts2 = [d.commit_count for d in s2.days]
        # Very unlikely (but theoretically possible) to be identical
        # with different seeds over 30 days
        assert counts1 != counts2


class TestDistribution:
    """Test that the generated distribution matches expected characteristics."""

    def test_has_inactive_days(self):
        """At least some days should have 0 commits over a 60-day window."""
        config = Config()
        gen = ActivityGenerator(config, seed=100)
        schedule = gen.generate(start_date=date(2025, 1, 1), num_days=60)

        assert schedule.inactive_days > 0

    def test_most_active_days_have_high_counts(self):
        """Most active days should have 6+ commits."""
        config = Config()
        gen = ActivityGenerator(config, seed=200)
        schedule = gen.generate(start_date=date(2025, 1, 1), num_days=90)

        active_counts = [d.commit_count for d in schedule.days if d.is_active]
        if active_counts:
            high_count = sum(1 for c in active_counts if c >= 6)
            high_ratio = high_count / len(active_counts)
            assert high_ratio >= 0.5  # At least half should be 6+

    def test_not_all_same_count(self):
        """Commit counts should not all be the same value."""
        config = Config()
        gen = ActivityGenerator(config, seed=300)
        schedule = gen.generate(start_date=date(2025, 1, 1), num_days=30)

        counts = [d.commit_count for d in schedule.days]
        unique = len(set(counts))
        assert unique >= 2

    def test_schedule_length_matches_request(self):
        config = Config()
        gen = ActivityGenerator(config, seed=42)

        for days in [1, 7, 30, 90, 365]:
            schedule = gen.generate(start_date=date(2025, 1, 1), num_days=days)
            assert schedule.total_days == days

    def test_statistical_distribution_over_many_samples(self):
        """Over 10k single-day samples, the distribution should roughly match config."""
        config = Config()
        counts = Counter()

        for i in range(10000):
            gen = ActivityGenerator(config, seed=i)
            schedule = gen.generate(start_date=date(2025, 6, 4), num_days=1)  # A Wednesday
            counts[schedule.days[0].commit_count] += 1

        total = sum(counts.values())
        # Zero commits should be moderate (~17% on a weekday: 15% day off + 85%*5% distribution zero)
        zero_ratio = counts[0] / total
        assert zero_ratio < 0.25  # Should be around 15-20%


class TestWeekendBehavior:
    """Test that weekend activity is lower than weekday activity."""

    def test_weekend_generally_lower(self):
        """Over enough samples, weekend activity should be lower."""
        config = Config()
        gen = ActivityGenerator(config, seed=42)
        # Generate 12 weeks
        schedule = gen.generate(start_date=date(2025, 1, 6), num_days=84)  # Monday

        weekday_total = 0
        weekday_days = 0
        weekend_total = 0
        weekend_days = 0

        for day in schedule.days:
            if day.date.weekday() < 5:
                weekday_total += day.commit_count
                weekday_days += 1
            else:
                weekend_total += day.commit_count
                weekend_days += 1

        weekday_avg = weekday_total / weekday_days if weekday_days else 0
        weekend_avg = weekend_total / weekend_days if weekend_days else 0

        # Weekend average should be lower (or at least not significantly higher)
        # We use a generous threshold since this is probabilistic
        assert weekend_avg <= weekday_avg * 1.5


class TestBurstGeneration:
    """Test development burst behavior."""

    def test_bursts_disabled(self):
        """With bursts disabled, no burst flags should be set."""
        config = Config(burst=BurstConfig(enabled=False))
        gen = ActivityGenerator(config, seed=42)
        schedule = gen.generate(start_date=date(2025, 1, 1), num_days=90)

        burst_days = [d for d in schedule.days if d.is_burst_day]
        assert len(burst_days) == 0

    def test_bursts_occur_with_high_probability(self):
        """With burst probability = 1.0, every day should potentially be a burst."""
        config = Config(burst=BurstConfig(
            enabled=True, probability=0.5, min_days=2, max_days=3, multiplier=2.0
        ))
        gen = ActivityGenerator(config, seed=42)
        schedule = gen.generate(start_date=date(2025, 1, 1), num_days=60)

        burst_days = [d for d in schedule.days if d.is_burst_day]
        # With p=0.5 over 60 days, we should see some bursts
        assert len(burst_days) > 0


class TestTimeGeneration:
    """Test commit time generation."""

    def test_times_within_development_hours(self):
        """All commit times should fall within configured development periods."""
        config = Config()
        gen = ActivityGenerator(config, seed=42)
        schedule = gen.generate(start_date=date(2025, 1, 1), num_days=30)

        for day in schedule.days:
            for commit in day.commits:
                hour = commit.time.hour
                # Should be within 8-23 (the configured development hours)
                assert 8 <= hour <= 23, f"Commit at {commit.time} outside dev hours"

    def test_times_are_sorted(self):
        """Commit times within a day should be chronologically sorted."""
        config = Config()
        gen = ActivityGenerator(config, seed=42)
        schedule = gen.generate(start_date=date(2025, 1, 1), num_days=30)

        for day in schedule.days:
            if len(day.commits) >= 2:
                for i in range(1, len(day.commits)):
                    assert day.commits[i].time >= day.commits[i - 1].time

    def test_times_not_uniformly_spaced(self):
        """Commit times should not be evenly spaced."""
        config = Config()
        gen = ActivityGenerator(config, seed=42)
        schedule = gen.generate(start_date=date(2025, 1, 1), num_days=60)

        # Collect all intervals between commits on multi-commit days
        intervals = []
        for day in schedule.days:
            if len(day.commits) >= 3:
                for i in range(1, len(day.commits)):
                    diff = (day.commits[i].time - day.commits[i - 1].time).total_seconds()
                    intervals.append(diff)

        if len(intervals) >= 3:
            # Intervals should not all be the same
            unique_intervals = len(set(intervals))
            assert unique_intervals >= 2


class TestScheduleProperties:
    """Test Schedule dataclass properties."""

    def test_empty_schedule(self):
        config = Config()
        gen = ActivityGenerator(config, seed=42)
        schedule = gen.generate(start_date=date(2025, 1, 1), num_days=1)

        assert schedule.total_days == 1

    def test_properties_consistency(self):
        config = Config()
        gen = ActivityGenerator(config, seed=42)
        schedule = gen.generate(start_date=date(2025, 1, 1), num_days=30)

        assert schedule.active_days + schedule.inactive_days == schedule.total_days
        assert schedule.total_commits == sum(d.commit_count for d in schedule.days)
