"""Realism validator for Auto Commit Bot.

Analyzes generated schedules for suspicious patterns and scores
realism on a 0–100 scale. Reusable as a standalone module.
"""

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional

from auto_commit.generator import Schedule


@dataclass
class CheckResult:
    """Result of a single realism check."""
    name: str
    passed: bool
    score: float  # 0.0–1.0 within this check
    weight: int
    detail: str = ""

    @property
    def weighted_score(self) -> float:
        return self.score * self.weight


@dataclass
class RealismReport:
    """Complete realism validation report."""
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def total_score(self) -> int:
        """Weighted total score 0–100."""
        if not self.checks:
            return 0
        max_possible = sum(c.weight for c in self.checks)
        actual = sum(c.weighted_score for c in self.checks)
        return round((actual / max_possible) * 100) if max_possible > 0 else 0

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def format_report(self) -> str:
        """Format a human-readable report."""
        lines = [
            "Activity Analysis",
            "-" * 40,
            "",
        ]

        for check in self.checks:
            marker = "✓" if check.passed else "✗"
            lines.append(f"  {marker} {check.name} ({check.score:.0%})")
            if check.detail:
                lines.append(f"    {check.detail}")

        lines.append("")
        lines.append(f"Activity score: {self.total_score}/100")
        return "\n".join(lines)


class RealismValidator:
    """
    Validates a generated schedule for realism.

    Runs multiple independent checks, each producing a sub-score.
    The weighted sum gives the final realism score (0–100).
    """

    def validate(self, schedule: Schedule) -> RealismReport:
        """Run all realism checks and return a report."""
        report = RealismReport()

        if schedule.total_days < 3:
            # Too few days for meaningful analysis
            report.checks.append(CheckResult(
                name="Insufficient data",
                passed=True,
                score=1.0,
                weight=100,
                detail=f"Only {schedule.total_days} day(s) — skipping detailed analysis"
            ))
            return report

        report.checks.append(self._check_count_variance(schedule))
        report.checks.append(self._check_inactive_ratio(schedule))
        report.checks.append(self._check_distribution_shape(schedule))
        report.checks.append(self._check_time_variance(schedule))
        report.checks.append(self._check_interval_regularity(schedule))
        report.checks.append(self._check_weekend_differentiation(schedule))
        report.checks.append(self._check_pattern_repetition(schedule))
        report.checks.append(self._check_message_diversity(schedule))
        report.checks.append(self._check_high_activity_frequency(schedule))

        return report

    def _check_count_variance(self, schedule: Schedule) -> CheckResult:
        """Check that daily commit counts are not identical every day."""
        counts = [d.commit_count for d in schedule.days]
        unique_counts = len(set(counts))
        total = len(counts)

        if total == 0:
            return CheckResult("Variable activity", True, 1.0, 15)

        # Ratio of unique counts to total days
        variety_ratio = unique_counts / min(total, 7)  # cap at 7 distinct values
        variety_ratio = min(variety_ratio, 1.0)

        # Check if one value dominates (>80% of days)
        counter = Counter(counts)
        most_common_pct = counter.most_common(1)[0][1] / total
        dominance_penalty = max(0, most_common_pct - 0.5) * 2  # penalty starts at 50%

        score = max(0, variety_ratio - dominance_penalty)
        passed = score >= 0.4

        return CheckResult(
            name="Variable activity",
            passed=passed,
            score=score,
            weight=15,
            detail=f"{unique_counts} distinct count values across {total} days"
        )

    def _check_inactive_ratio(self, schedule: Schedule) -> CheckResult:
        """Check that there are natural inactive periods (not all active, not all inactive)."""
        total = schedule.total_days
        inactive = schedule.inactive_days

        if total == 0:
            return CheckResult("Natural gaps", True, 1.0, 15)

        ratio = inactive / total

        # Ideal range: 20–60% inactive
        if 0.20 <= ratio <= 0.60:
            score = 1.0
        elif ratio < 0.20:
            # Too few inactive days
            score = ratio / 0.20
        elif ratio > 0.60:
            # Too many inactive days (but still okay-ish up to 80%)
            score = max(0, 1.0 - (ratio - 0.60) / 0.30)
        else:
            score = 0.0

        passed = score >= 0.4

        return CheckResult(
            name="Natural gaps",
            passed=passed,
            score=score,
            weight=15,
            detail=f"{inactive}/{total} days inactive ({ratio:.0%})"
        )

    def _check_distribution_shape(self, schedule: Schedule) -> CheckResult:
        """Check that commit counts follow configured distribution."""
        counts = [d.commit_count for d in schedule.days if d.is_active]

        if len(counts) < 2:
            return CheckResult("Natural distribution", True, 1.0, 15)

        # Ratio of active days with high activity (6+ commits)
        high_count = sum(1 for c in counts if c >= 6)
        high_ratio = high_count / len(counts)

        score = min(1.0, max(0.5, high_ratio))
        passed = score >= 0.4

        return CheckResult(
            name="Natural distribution",
            passed=passed,
            score=score,
            weight=15,
            detail=f"{high_ratio:.0%} of active days have 6+ commits"
        )

    def _check_time_variance(self, schedule: Schedule) -> CheckResult:
        """Check that commit times vary across days (not the same time every day)."""
        all_minutes = []
        for day in schedule.days:
            for commit in day.commits:
                all_minutes.append(commit.time.hour * 60 + commit.time.minute)

        if len(all_minutes) < 3:
            return CheckResult("Variable timestamps", True, 1.0, 10)

        # Check standard deviation of commit times
        mean = sum(all_minutes) / len(all_minutes)
        variance = sum((m - mean) ** 2 for m in all_minutes) / len(all_minutes)
        std_dev = math.sqrt(variance)

        # A std_dev < 15 minutes means times are suspiciously similar
        if std_dev > 120:
            score = 1.0
        elif std_dev > 60:
            score = 0.8
        elif std_dev > 30:
            score = 0.5
        elif std_dev > 15:
            score = 0.3
        else:
            score = 0.1

        passed = score >= 0.4

        return CheckResult(
            name="Variable timestamps",
            passed=passed,
            score=score,
            weight=10,
            detail=f"Time std dev: {std_dev:.0f} minutes"
        )

    def _check_interval_regularity(self, schedule: Schedule) -> CheckResult:
        """Check that intervals between commits are not evenly spaced."""
        all_times = []
        for day in schedule.days:
            for commit in day.commits:
                all_times.append(commit.time)

        all_times.sort()

        if len(all_times) < 3:
            return CheckResult("Irregular intervals", True, 1.0, 10)

        # Calculate intervals in minutes
        intervals = []
        for i in range(1, len(all_times)):
            diff = (all_times[i] - all_times[i - 1]).total_seconds() / 60
            intervals.append(diff)

        if not intervals:
            return CheckResult("Irregular intervals", True, 1.0, 10)

        # Check coefficient of variation (std/mean)
        mean_int = sum(intervals) / len(intervals)
        if mean_int == 0:
            return CheckResult("Irregular intervals", False, 0.0, 10,
                               "All commits at the same time")

        variance = sum((i - mean_int) ** 2 for i in intervals) / len(intervals)
        std_int = math.sqrt(variance)
        cv = std_int / mean_int

        # Higher CV = more irregular = more realistic
        if cv > 1.0:
            score = 1.0
        elif cv > 0.5:
            score = 0.7
        elif cv > 0.2:
            score = 0.4
        else:
            score = 0.1

        passed = score >= 0.4

        return CheckResult(
            name="Irregular intervals",
            passed=passed,
            score=score,
            weight=10,
            detail=f"Interval CV: {cv:.2f}"
        )

    def _check_weekend_differentiation(self, schedule: Schedule) -> CheckResult:
        """Check that weekend activity differs from weekday activity."""
        weekday_counts = []
        weekend_counts = []

        for day in schedule.days:
            if day.date.weekday() >= 5:
                weekend_counts.append(day.commit_count)
            else:
                weekday_counts.append(day.commit_count)

        if not weekday_counts or not weekend_counts:
            return CheckResult("Weekend variation", True, 1.0, 10,
                               "Schedule does not span both weekdays and weekends")

        weekday_avg = sum(weekday_counts) / len(weekday_counts)
        weekend_avg = sum(weekend_counts) / len(weekend_counts)

        # Weekend should generally be lower
        if weekday_avg == 0:
            score = 0.5  # No activity at all — neutral
        else:
            ratio = weekend_avg / weekday_avg
            if 0.3 <= ratio <= 0.85:
                score = 1.0  # Nicely differentiated
            elif ratio < 0.3:
                score = 0.6  # Weekend very low, still okay
            elif ratio <= 1.0:
                score = 0.4  # Close to equal
            else:
                score = 0.2  # Weekend higher than weekday — unusual

        passed = score >= 0.3

        return CheckResult(
            name="Weekend variation",
            passed=passed,
            score=score,
            weight=10,
            detail=f"Weekday avg: {weekday_avg:.2f}, Weekend avg: {weekend_avg:.2f}"
        )

    def _check_pattern_repetition(self, schedule: Schedule) -> CheckResult:
        """Check for obviously repeating patterns in daily commit counts."""
        counts = [d.commit_count for d in schedule.days]

        if len(counts) < 6:
            return CheckResult("No repeating patterns", True, 1.0, 10)

        # Check for period-2 repetition: a, b, a, b, a, b...
        # Check for period-3 repetition: a, b, c, a, b, c...
        worst_repetition_score = 1.0

        for period in range(2, min(8, len(counts) // 2)):
            matches = 0
            comparisons = 0
            for i in range(period, len(counts)):
                comparisons += 1
                if counts[i] == counts[i - period]:
                    matches += 1

            if comparisons > 0:
                match_ratio = matches / comparisons
                # High match ratio = suspicious pattern
                rep_score = 1.0 - max(0, (match_ratio - 0.5)) * 2
                worst_repetition_score = min(worst_repetition_score, rep_score)

        score = max(0.0, worst_repetition_score)
        passed = score >= 0.4

        return CheckResult(
            name="No repeating patterns",
            passed=passed,
            score=score,
            weight=10,
            detail=f"Pattern regularity score: {score:.2f}"
        )

    def _check_message_diversity(self, schedule: Schedule) -> CheckResult:
        """Check that commit messages are varied (no excessive repetition)."""
        messages = []
        for day in schedule.days:
            for commit in day.commits:
                messages.append(commit.message)

        if len(messages) < 3:
            return CheckResult("Message diversity", True, 1.0, 10)

        unique = len(set(messages))
        total = len(messages)
        diversity_ratio = unique / total

        # Check for consecutive duplicates
        consecutive_dupes = 0
        for i in range(1, len(messages)):
            if messages[i] == messages[i - 1]:
                consecutive_dupes += 1

        dupe_penalty = consecutive_dupes / max(1, total - 1)

        score = min(1.0, diversity_ratio + 0.3) - dupe_penalty
        score = max(0.0, score)
        passed = score >= 0.4

        return CheckResult(
            name="Message diversity",
            passed=passed,
            score=score,
            weight=10,
            detail=f"{unique}/{total} unique messages"
        )

    def _check_high_activity_frequency(self, schedule: Schedule) -> CheckResult:
        """Check that high-activity days are rare (not too many, ideally not zero for long schedules)."""
        counts = [d.commit_count for d in schedule.days]
        total = len(counts)

        if total == 0:
            return CheckResult("Burst frequency", True, 1.0, 5)

        high_days = sum(1 for c in counts if c >= 4)
        high_ratio = high_days / total

        if total < 14:
            # Short schedule — just check it's not all high
            score = 1.0 if high_ratio < 0.5 else 0.3
        else:
            # Ideal: 3–15% of days are high activity
            if 0.03 <= high_ratio <= 0.15:
                score = 1.0
            elif high_ratio < 0.03:
                score = 0.7  # No bursts — acceptable
            elif high_ratio <= 0.25:
                score = 0.5
            else:
                score = 0.2  # Too many high days

        passed = score >= 0.3

        return CheckResult(
            name="Burst frequency",
            passed=passed,
            score=score,
            weight=5,
            detail=f"{high_days}/{total} days with 4+ commits ({high_ratio:.0%})"
        )
