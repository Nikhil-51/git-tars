"""Tests for the safety validator."""

import os
import pytest

from auto_commit.config import SafetyConfig
from auto_commit.safety import SafetyValidator, SafetyResult


class TestPathValidation:
    """Test allowed/forbidden path logic."""

    def test_allowed_path(self):
        validator = SafetyValidator(SafetyConfig(), expected_branch="main")
        assert validator._is_allowed_path(".auto-commit/activity.json") is True
        assert validator._is_allowed_path(".auto-commit/state.json") is True
        assert validator._is_allowed_path(".auto-commit/history.json") is True

    def test_disallowed_path(self):
        validator = SafetyValidator(SafetyConfig(), expected_branch="main")
        assert validator._is_allowed_path("src/main.py") is False
        assert validator._is_allowed_path("README.md") is False
        assert validator._is_allowed_path("package.json") is False

    def test_forbidden_files(self):
        validator = SafetyValidator(SafetyConfig(), expected_branch="main")
        assert validator._is_forbidden_file(".env") is True
        assert validator._is_forbidden_file(".env.local") is True
        assert validator._is_forbidden_file("credentials.json") is True
        assert validator._is_forbidden_file("my_secret.txt") is True
        assert validator._is_forbidden_file("server.key.pem") is True
        assert validator._is_forbidden_file("id_rsa") is True

    def test_safe_files_not_forbidden(self):
        validator = SafetyValidator(SafetyConfig(), expected_branch="main")
        assert validator._is_forbidden_file("activity.json") is False
        assert validator._is_forbidden_file("state.json") is False
        assert validator._is_forbidden_file("config.json") is False

    def test_custom_allowed_paths(self):
        config = SafetyConfig(allowed_paths=[".auto-commit/", "data/"])
        validator = SafetyValidator(config, expected_branch="main")
        assert validator._is_allowed_path("data/output.json") is True
        assert validator._is_allowed_path("src/main.py") is False

    def test_custom_forbidden_patterns(self):
        config = SafetyConfig(forbidden_patterns=["api_key", "database_url"])
        validator = SafetyValidator(config, expected_branch="main")
        assert validator._is_forbidden_file("api_key.txt") is True
        assert validator._is_forbidden_file("database_url.env") is True
        assert validator._is_forbidden_file("normal_file.txt") is False


class TestSafetyResult:
    """Test SafetyResult formatting."""

    def test_safe_result_format(self):
        result = SafetyResult(safe=True)
        assert "passed" in result.format_report().lower()

    def test_unsafe_result_format(self):
        result = SafetyResult(
            safe=False,
            errors=["Unexpected file: src/main.py"]
        )
        report = result.format_report()
        assert "FAILED" in report
        assert "src/main.py" in report
