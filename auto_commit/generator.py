"""Activity schedule generator for Auto Commit Bot.

Generates realistic, irregular commit schedules using a probabilistic
model with configurable distributions, development bursts, session
clustering, and natural gaps.
"""

import math
import random as _random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple

from auto_commit.config import Config, TimePeriod
from auto_commit.messages import MessageGenerator


@dataclass
class CommitEntry:
    """A single planned commit."""
    time: datetime
    message: str


@dataclass
class DaySchedule:
    """Schedule for a single day."""
    date: date
    commit_count: int
    is_burst_day: bool
    commits: List[CommitEntry] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.commit_count > 0


@dataclass
class Schedule:
    """Complete generated schedule."""
    days: List[DaySchedule]
    seed: int
    start_date: date
    end_date: date
    generation_attempt: int = 1

    @property
    def total_days(self) -> int:
        return len(self.days)

    @property
    def active_days(self) -> int:
        return sum(1 for d in self.days if d.is_active)

    @property
    def inactive_days(self) -> int:
        return self.total_days - self.active_days

    @property
    def total_commits(self) -> int:
        return sum(d.commit_count for d in self.days)

    @property
    def avg_commits_per_active_day(self) -> float:
        active = self.active_days
        if active == 0:
            return 0.0
        return self.total_commits / active

    @property
    def highest_activity_day(self) -> Optional[DaySchedule]:
        active = [d for d in self.days if d.is_active]
        if not active:
            return None
        return max(active, key=lambda d: d.commit_count)

    @property
    def longest_inactive_streak(self) -> int:
        max_streak = 0
        current = 0
        for d in self.days:
            if not d.is_active:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    @property
    def longest_active_streak(self) -> int:
        max_streak = 0
        current = 0
        for d in self.days:
            if d.is_active:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    @property
    def weekend_activity_pct(self) -> float:
        weekend_days = [d for d in self.days if d.date.weekday() >= 5]
        if not weekend_days:
            return 0.0
        active_weekend = sum(1 for d in weekend_days if d.is_active)
        return (active_weekend / len(weekend_days)) * 100


class ActivityGenerator:
    """
    Generates realistic commit activity schedules.

    Uses a probabilistic model with:
    - Configurable daily commit distribution
    - Day-of-week activity multipliers
    - Optional development bursts
    - Session-clustered commit times
    - Natural gaps and irregular patterns
    """

    def __init__(self, config: Config, seed: Optional[int] = None):
        self._config = config
        self._seed = seed if seed is not None else config.seed
        if self._seed is None:
            self._seed = _random.randint(0, 2**31 - 1)
        self._rng = _random.Random(self._seed)
        self._msg_gen = MessageGenerator(
            rng=_random.Random(self._seed + 1),
            prefix_override=config.commit_prefix if config.commit_prefix != "chore" else None,
        )

    @property
    def seed(self) -> int:
        return self._seed

    def generate(
        self,
        start_date: date,
        num_days: int = 30,
        end_date: Optional[date] = None,
    ) -> Schedule:
        """
        Generate a complete activity schedule.

        Args:
            start_date: First day of the schedule.
            num_days: Number of days (used if end_date is not provided).
            end_date: Last day of the schedule (inclusive). Overrides num_days.

        Returns:
            A Schedule object with all days, commits, times, and messages.
        """
        if end_date is not None:
            num_days = (end_date - start_date).days + 1

        if num_days < 1:
            raise ValueError("Schedule must span at least 1 day")

        # Phase 1: Generate daily commit counts
        daily_counts = self._generate_daily_counts(start_date, num_days)

        # Phase 2: Apply development bursts
        burst_flags = self._apply_bursts(daily_counts, start_date, num_days)

        # Phase 3: Build day schedules with times and messages
        days = []
        for i in range(num_days):
            current_date = start_date + timedelta(days=i)
            count = daily_counts[i]
            is_burst = burst_flags[i]

            day_schedule = DaySchedule(
                date=current_date,
                commit_count=count,
                is_burst_day=is_burst,
            )

            if count > 0:
                times = self._generate_times(current_date, count)
                messages = self._msg_gen.generate_batch(count)
                for t, m in zip(times, messages):
                    day_schedule.commits.append(CommitEntry(time=t, message=m))

            days.append(day_schedule)

        return Schedule(
            days=days,
            seed=self._seed,
            start_date=start_date,
            end_date=start_date + timedelta(days=num_days - 1),
        )

    def _get_day_probability(self, d: date) -> float:
        """Get the activity probability for a given day based on day-of-week."""
        weekday = d.weekday()  # 0=Monday, 6=Sunday
        if weekday == 5:  # Saturday
            return self._config.activity.saturday_probability
        elif weekday == 6:  # Sunday
            return self._config.activity.sunday_probability
        else:
            return self._config.activity.weekday_probability

    def _sample_commit_count(self) -> int:
        """
        Sample a commit count from the configured distribution.

        Returns the number of commits (0+).
        """
        dist = self._config.activity.commit_distribution
        counts = list(dist.keys())
        weights = list(dist.values())

        chosen = self._rng.choices(counts, weights=weights, k=1)[0]
        return chosen

    def _generate_daily_counts(self, start_date: date, num_days: int) -> List[int]:
        """Generate raw daily commit counts with day-of-week weighting."""
        counts = []
        for i in range(num_days):
            current = start_date + timedelta(days=i)
            prob = self._get_day_probability(current)

            # Bernoulli trial: is this day active?
            if self._rng.random() > prob:
                counts.append(0)
            else:
                count = self._sample_commit_count()
                # If we sampled 0 from the distribution on an "active" day,
                # that's fine — it means the day ends up inactive
                counts.append(count)

        return counts

    def _apply_bursts(
        self, counts: List[int], start_date: date, num_days: int
    ) -> List[bool]:
        """
        Apply development bursts to the schedule.

        Randomly selects burst periods and multiplies commit counts.
        Returns a list of burst flags per day.
        """
        burst_flags = [False] * num_days
        burst_cfg = self._config.burst

        if not burst_cfg.enabled:
            return burst_flags

        i = 0
        while i < num_days:
            # Check if a burst starts on this day
            if self._rng.random() < burst_cfg.probability:
                burst_len = self._rng.randint(burst_cfg.min_days, burst_cfg.max_days)
                burst_end = min(i + burst_len, num_days)

                for j in range(i, burst_end):
                    burst_flags[j] = True
                    if counts[j] == 0:
                        # During a burst, inactive days become active
                        # with a moderate count
                        counts[j] = self._rng.randint(1, 3)
                    else:
                        # Multiply with jitter (±20%)
                        jitter = self._rng.uniform(0.8, 1.2)
                        multiplied = counts[j] * burst_cfg.multiplier * jitter
                        counts[j] = min(24, max(1, round(multiplied)))

                # Skip past the burst
                i = burst_end
            else:
                i += 1

        return burst_flags

    def _generate_times(self, day: date, count: int) -> List[datetime]:
        """
        Generate commit times for a given day.

        Uses period selection with Gaussian sampling and optional
        session clustering for realistic timing.
        """
        periods = self._config.time_periods
        session_cfg = self._config.session

        # Decide if this day uses session clustering
        use_clustering = (
            count >= 2
            and self._rng.random() < session_cfg.cluster_probability
        )

        if use_clustering:
            times = self._generate_clustered_times(day, count, periods, session_cfg)
        else:
            times = self._generate_spread_times(day, count, periods)

        times.sort()
        return times

    def _generate_spread_times(
        self, day: date, count: int, periods: list
    ) -> List[datetime]:
        """Generate times spread across different development periods."""
        times = []
        period_weights = [p.weight for p in periods]

        for _ in range(count):
            # Pick a period
            period = self._rng.choices(periods, weights=period_weights, k=1)[0]
            t = self._sample_time_in_period(day, period)
            times.append(t)

        return times

    def _generate_clustered_times(
        self, day: date, count: int, periods: list, session_cfg
    ) -> List[datetime]:
        """
        Generate session-clustered times.

        Picks a starting period and time, then spaces subsequent commits
        closely together (5–45 min gaps) to simulate a focused coding session.
        """
        period_weights = [p.weight for p in periods]

        # How many commits in the cluster vs spread out
        cluster_size = self._rng.randint(2, min(count, 5))
        spread_count = count - cluster_size

        # Generate the cluster
        period = self._rng.choices(periods, weights=period_weights, k=1)[0]
        base_time = self._sample_time_in_period(day, period)
        cluster_times = [base_time]

        for _ in range(cluster_size - 1):
            gap = self._rng.randint(
                session_cfg.min_gap_minutes,
                session_cfg.max_gap_minutes,
            )
            next_time = cluster_times[-1] + timedelta(minutes=gap)
            # Clamp to the period's end time
            period_end = day_with_time(day, period.end_hour, period.end_minute)
            if next_time > period_end:
                # Shift back into the period
                next_time = period_end - timedelta(
                    minutes=self._rng.randint(1, 30)
                )
            cluster_times.append(next_time)

        # Generate remaining spread times
        spread_times = self._generate_spread_times(day, spread_count, periods) if spread_count > 0 else []

        return cluster_times + spread_times

    def _sample_time_in_period(self, day: date, period: TimePeriod) -> datetime:
        """
        Sample a random time within a period using a Gaussian distribution
        centered at the midpoint.
        """
        mid_minutes = (period.start_minutes + period.end_minutes) / 2
        sigma = period.duration_minutes / 4

        # Sample with truncation to stay within the period
        for _ in range(20):
            sampled = self._rng.gauss(mid_minutes, sigma)
            if period.start_minutes <= sampled <= period.end_minutes:
                total_min = int(sampled)
                hour = min(23, total_min // 60)
                minute = total_min % 60 if hour < 23 else min(59, total_min % 60)
                second = self._rng.randint(0, 59)
                return datetime(day.year, day.month, day.day, hour, minute, second)

        # Fallback: uniform within the period
        total_min = self._rng.randint(period.start_minutes, min(1439, period.end_minutes))
        hour = min(23, total_min // 60)
        minute = total_min % 60
        second = self._rng.randint(0, 59)
        return datetime(day.year, day.month, day.day, hour, minute, second)


def day_with_time(d: date, hour: int, minute: int) -> datetime:
    """Combine a date with a time."""
    safe_hour = min(23, max(0, hour))
    safe_minute = min(59, max(0, minute))
    return datetime(d.year, d.month, d.day, safe_hour, safe_minute, 0)
