"""Configuration loader and validator for Auto Commit Bot."""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class TimePeriod:
    """A development time period (e.g., morning, afternoon, evening)."""
    name: str
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    weight: float

    @property
    def start_minutes(self) -> int:
        """Total minutes from midnight for period start."""
        return self.start_hour * 60 + self.start_minute

    @property
    def end_minutes(self) -> int:
        """Total minutes from midnight for period end."""
        return self.end_hour * 60 + self.end_minute

    @property
    def duration_minutes(self) -> int:
        """Duration of the period in minutes."""
        return self.end_minutes - self.start_minutes


@dataclass(frozen=True)
class BurstConfig:
    """Development burst configuration."""
    enabled: bool = True
    probability: float = 0.12
    min_days: int = 2
    max_days: int = 4
    multiplier: float = 1.5


@dataclass(frozen=True)
class SessionConfig:
    """Session clustering configuration."""
    cluster_probability: float = 0.30
    min_gap_minutes: int = 5
    max_gap_minutes: int = 45


@dataclass(frozen=True)
class ActivityConfig:
    """Activity probability configuration."""
    weekday_probability: float = 0.88
    saturday_probability: float = 0.78
    sunday_probability: float = 0.68
    commit_distribution: Dict[int, float] = field(default_factory=lambda: {
        0: 0.04, 1: 0.05, 2: 0.07, 4: 0.10, 6: 0.14, 8: 0.16, 11: 0.16, 15: 0.14, 18: 0.09, 21: 0.05
    })


@dataclass(frozen=True)
class RealismConfig:
    """Realism validation configuration."""
    min_score: int = 60
    max_regeneration_attempts: int = 5


@dataclass(frozen=True)
class SafetyConfig:
    """Safety check configuration."""
    allowed_paths: List[str] = field(default_factory=lambda: [".auto-commit/"])
    max_file_size_kb: int = 100
    forbidden_patterns: List[str] = field(default_factory=lambda: [
        ".env", "credentials", "secret", "token", "password", "key.pem", "id_rsa"
    ])


@dataclass(frozen=True)
class Config:
    """Complete bot configuration."""
    enabled: bool = True
    branch: str = "main"
    timezone: str = "Asia/Kolkata"
    activity: ActivityConfig = field(default_factory=ActivityConfig)
    development_hours_start: int = 8
    development_hours_end: int = 23
    time_periods: List[TimePeriod] = field(default_factory=lambda: [
        TimePeriod("morning", 8, 0, 11, 30, 0.25),
        TimePeriod("afternoon", 13, 0, 17, 30, 0.35),
        TimePeriod("evening", 19, 0, 23, 0, 0.40),
    ])
    burst: BurstConfig = field(default_factory=BurstConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    seed: Optional[int] = None
    commit_prefix: str = "chore"
    realism: RealismConfig = field(default_factory=RealismConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)


class ConfigError(Exception):
    """Raised when configuration is invalid."""
    pass


def _parse_time(time_str: str) -> tuple:
    """Parse 'HH:MM' string into (hour, minute) tuple."""
    try:
        parts = time_str.split(":")
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return hour, minute
    except (ValueError, IndexError):
        raise ConfigError(f"Invalid time format: '{time_str}'. Expected 'HH:MM'.")


def _validate_probabilities(config: Config) -> None:
    """Validate that all probability values are within valid range."""
    for name, value in [
        ("weekday_probability", config.activity.weekday_probability),
        ("saturday_probability", config.activity.saturday_probability),
        ("sunday_probability", config.activity.sunday_probability),
    ]:
        if not 0.0 <= value <= 1.0:
            raise ConfigError(f"{name} must be between 0.0 and 1.0, got {value}")

    # Validate commit distribution sums to ~1.0
    total = sum(config.activity.commit_distribution.values())
    if not (0.95 <= total <= 1.05):
        raise ConfigError(
            f"commit_distribution probabilities sum to {total:.4f}, "
            f"expected approximately 1.0"
        )

    # All distribution values non-negative
    for count, prob in config.activity.commit_distribution.items():
        if prob < 0:
            raise ConfigError(
                f"commit_distribution[{count}] = {prob} is negative"
            )


def _validate_hours(config: Config) -> None:
    """Validate development hours and time periods."""
    if not (0 <= config.development_hours_start <= 23):
        raise ConfigError(
            f"development_hours.start must be 0-23, got {config.development_hours_start}"
        )
    if not (0 <= config.development_hours_end <= 23):
        raise ConfigError(
            f"development_hours.end must be 0-23, got {config.development_hours_end}"
        )
    if config.development_hours_start >= config.development_hours_end:
        raise ConfigError(
            f"development_hours.start ({config.development_hours_start}) "
            f"must be less than end ({config.development_hours_end})"
        )

    # Validate time periods
    if not config.time_periods:
        raise ConfigError("At least one development time period is required")

    weight_sum = sum(p.weight for p in config.time_periods)
    if not (0.95 <= weight_sum <= 1.05):
        raise ConfigError(
            f"Time period weights sum to {weight_sum:.4f}, expected approximately 1.0"
        )

    for period in config.time_periods:
        if period.weight < 0:
            raise ConfigError(f"Time period '{period.name}' has negative weight")
        if period.start_minutes >= period.end_minutes:
            raise ConfigError(
                f"Time period '{period.name}' start must be before end"
            )


def _validate_burst(config: Config) -> None:
    """Validate burst configuration."""
    burst = config.burst
    if not 0.0 <= burst.probability <= 1.0:
        raise ConfigError(
            f"burst.probability must be between 0.0 and 1.0, got {burst.probability}"
        )
    if burst.min_days < 1:
        raise ConfigError(f"burst.min_days must be >= 1, got {burst.min_days}")
    if burst.max_days < burst.min_days:
        raise ConfigError(
            f"burst.max_days ({burst.max_days}) must be >= min_days ({burst.min_days})"
        )
    if burst.multiplier < 1.0:
        raise ConfigError(
            f"burst.multiplier must be >= 1.0, got {burst.multiplier}"
        )


def _validate_session(config: Config) -> None:
    """Validate session clustering configuration."""
    session = config.session
    if not 0.0 <= session.cluster_probability <= 1.0:
        raise ConfigError(
            f"session.cluster_probability must be between 0.0 and 1.0, "
            f"got {session.cluster_probability}"
        )
    if session.min_gap_minutes < 1:
        raise ConfigError(
            f"session.min_gap_minutes must be >= 1, got {session.min_gap_minutes}"
        )
    if session.max_gap_minutes < session.min_gap_minutes:
        raise ConfigError(
            f"session.max_gap_minutes ({session.max_gap_minutes}) must be >= "
            f"min_gap_minutes ({session.min_gap_minutes})"
        )


def validate_config(config: Config) -> None:
    """Run all validation checks on a Config object. Raises ConfigError on failure."""
    _validate_probabilities(config)
    _validate_hours(config)
    _validate_burst(config)
    _validate_session(config)


def load_config(config_path: str = "config.json") -> Config:
    """
    Load configuration from a JSON file and return a validated Config object.

    Falls back to defaults for any missing fields.
    Raises ConfigError for invalid values or malformed JSON.
    """
    if not os.path.exists(config_path):
        raise ConfigError(f"Configuration file not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in {config_path}: {e}")

    if not isinstance(raw, dict):
        raise ConfigError(f"Configuration must be a JSON object, got {type(raw).__name__}")

    return _build_config(raw)


def _build_config(raw: Dict[str, Any]) -> Config:
    """Build a Config from a raw JSON dict, applying defaults for missing fields."""
    # Activity config
    activity_raw = raw.get("activity", {})
    commit_dist_raw = activity_raw.get("commit_distribution", {})
    commit_distribution = {int(k): float(v) for k, v in commit_dist_raw.items()} if commit_dist_raw else {
        0: 0.35, 1: 0.30, 2: 0.20, 3: 0.10, 4: 0.03, 5: 0.01, 6: 0.01
    }

    activity = ActivityConfig(
        weekday_probability=float(activity_raw.get("weekday_probability", 0.65)),
        saturday_probability=float(activity_raw.get("saturday_probability", 0.45)),
        sunday_probability=float(activity_raw.get("sunday_probability", 0.35)),
        commit_distribution=commit_distribution,
    )

    # Development hours + time periods
    dev_hours_raw = raw.get("development_hours", {})
    periods_raw = dev_hours_raw.get("periods", [])

    if periods_raw:
        time_periods = []
        for p in periods_raw:
            s_h, s_m = _parse_time(p["start"])
            e_h, e_m = _parse_time(p["end"])
            time_periods.append(TimePeriod(
                name=p.get("name", "period"),
                start_hour=s_h,
                start_minute=s_m,
                end_hour=e_h,
                end_minute=e_m,
                weight=float(p.get("weight", 1.0)),
            ))
    else:
        time_periods = [
            TimePeriod("morning", 8, 0, 11, 30, 0.25),
            TimePeriod("afternoon", 13, 0, 17, 30, 0.35),
            TimePeriod("evening", 19, 0, 23, 0, 0.40),
        ]

    # Burst config
    burst_raw = raw.get("burst", {})
    burst = BurstConfig(
        enabled=bool(burst_raw.get("enabled", True)),
        probability=float(burst_raw.get("probability", 0.12)),
        min_days=int(burst_raw.get("min_days", 2)),
        max_days=int(burst_raw.get("max_days", 5)),
        multiplier=float(burst_raw.get("multiplier", 1.8)),
    )

    # Session config
    session_raw = raw.get("session", {})
    session = SessionConfig(
        cluster_probability=float(session_raw.get("cluster_probability", 0.30)),
        min_gap_minutes=int(session_raw.get("min_gap_minutes", 5)),
        max_gap_minutes=int(session_raw.get("max_gap_minutes", 45)),
    )

    # Realism config
    realism_raw = raw.get("realism", {})
    realism = RealismConfig(
        min_score=int(realism_raw.get("min_score", 60)),
        max_regeneration_attempts=int(realism_raw.get("max_regeneration_attempts", 5)),
    )

    # Safety config
    safety_raw = raw.get("safety", {})
    safety = SafetyConfig(
        allowed_paths=list(safety_raw.get("allowed_paths", [".auto-commit/"])),
        max_file_size_kb=int(safety_raw.get("max_file_size_kb", 100)),
        forbidden_patterns=list(safety_raw.get("forbidden_patterns", [
            ".env", "credentials", "secret", "token", "password", "key.pem", "id_rsa"
        ])),
    )

    # Seed
    rand_raw = raw.get("randomization", {})
    seed = rand_raw.get("seed", None)
    if seed is not None:
        seed = int(seed)

    config = Config(
        enabled=bool(raw.get("enabled", True)),
        branch=str(raw.get("branch", "main")),
        timezone=str(raw.get("timezone", "Asia/Kolkata")),
        activity=activity,
        development_hours_start=int(dev_hours_raw.get("start", 8)),
        development_hours_end=int(dev_hours_raw.get("end", 23)),
        time_periods=time_periods,
        burst=burst,
        session=session,
        seed=seed,
        commit_prefix=str(raw.get("commit", {}).get("prefix", "chore")),
        realism=realism,
        safety=safety,
    )

    validate_config(config)
    return config
