"""Tests for configuration loading and validation."""

import json
import os
import tempfile
import pytest

from auto_commit.config import (
    load_config, validate_config, Config, ConfigError,
    ActivityConfig, BurstConfig, SessionConfig, RealismConfig, SafetyConfig,
)


class TestConfigDefaults:
    """Test that default configuration values are valid."""

    def test_default_config_passes_validation(self):
        config = Config()
        validate_config(config)

    def test_default_activity_probabilities(self):
        config = Config()
        assert config.activity.weekday_probability == 0.88
        assert config.activity.saturday_probability == 0.78
        assert config.activity.sunday_probability == 0.68

    def test_default_distribution_sums_to_one(self):
        config = Config()
        total = sum(config.activity.commit_distribution.values())
        assert abs(total - 1.0) < 0.01

    def test_default_time_period_weights_sum_to_one(self):
        config = Config()
        total = sum(p.weight for p in config.time_periods)
        assert abs(total - 1.0) < 0.01


class TestConfigLoading:
    """Test loading config from JSON files."""

    def test_load_valid_config(self, tmp_path):
        config_data = {
            "enabled": True,
            "branch": "main",
            "timezone": "UTC",
            "activity": {
                "weekday_probability": 0.5,
                "saturday_probability": 0.3,
                "sunday_probability": 0.2,
                "commit_distribution": {
                    "0": 0.40, "1": 0.30, "2": 0.20, "3": 0.10
                }
            },
            "development_hours": {"start": 9, "end": 22},
            "burst": {"enabled": True, "probability": 0.1, "min_days": 2, "max_days": 4, "multiplier": 1.5},
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(str(config_file))
        assert config.enabled is True
        assert config.branch == "main"
        assert config.activity.weekday_probability == 0.5

    def test_missing_config_file_raises_error(self):
        with pytest.raises(ConfigError, match="not found"):
            load_config("/nonexistent/config.json")

    def test_invalid_json_raises_error(self, tmp_path):
        config_file = tmp_path / "bad.json"
        config_file.write_text("not valid json {{{")

        with pytest.raises(ConfigError, match="Invalid JSON"):
            load_config(str(config_file))

    def test_non_object_json_raises_error(self, tmp_path):
        config_file = tmp_path / "array.json"
        config_file.write_text("[1, 2, 3]")

        with pytest.raises(ConfigError, match="must be a JSON object"):
            load_config(str(config_file))


class TestConfigValidation:
    """Test config validation rules."""

    def test_probability_above_one_raises_error(self):
        config = Config(
            activity=ActivityConfig(weekday_probability=1.5)
        )
        with pytest.raises(ConfigError, match="weekday_probability"):
            validate_config(config)

    def test_negative_probability_raises_error(self):
        config = Config(
            activity=ActivityConfig(saturday_probability=-0.1)
        )
        with pytest.raises(ConfigError, match="saturday_probability"):
            validate_config(config)

    def test_distribution_not_summing_to_one_raises_error(self):
        config = Config(
            activity=ActivityConfig(commit_distribution={0: 0.5, 1: 0.1})
        )
        with pytest.raises(ConfigError, match="commit_distribution"):
            validate_config(config)

    def test_invalid_development_hours_raises_error(self):
        config = Config(development_hours_start=23, development_hours_end=8)
        with pytest.raises(ConfigError, match="development_hours"):
            validate_config(config)

    def test_burst_min_greater_than_max_raises_error(self):
        config = Config(
            burst=BurstConfig(min_days=6, max_days=3)
        )
        with pytest.raises(ConfigError, match="max_days"):
            validate_config(config)

    def test_burst_multiplier_below_one_raises_error(self):
        config = Config(
            burst=BurstConfig(multiplier=0.5)
        )
        with pytest.raises(ConfigError, match="multiplier"):
            validate_config(config)

    def test_session_min_gap_greater_than_max_raises_error(self):
        config = Config(
            session=SessionConfig(min_gap_minutes=60, max_gap_minutes=10)
        )
        with pytest.raises(ConfigError, match="max_gap_minutes"):
            validate_config(config)
