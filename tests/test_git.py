"""Tests for the Git wrapper module."""

from unittest.mock import patch, MagicMock
import subprocess
import pytest

from auto_commit.git import (
    _run_git, is_git_repo, get_current_branch,
    stage_files, GitError,
)


class TestGitSafety:
    """Test that Git operations are safe."""

    def test_run_git_uses_shell_false(self):
        """Verify git commands never use shell=True."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="output", stderr=""
            )
            try:
                _run_git(["status"])
            except Exception:
                pass

            if mock_run.called:
                call_kwargs = mock_run.call_args
                # shell should be False
                assert call_kwargs.kwargs.get("shell", False) is False

    def test_stage_files_rejects_empty_list(self):
        """Staging an empty list of files should raise an error."""
        with pytest.raises(GitError, match="No files"):
            stage_files([])

    def test_git_not_installed_error(self):
        """Should give a clear error if git is not found."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(GitError, match="not installed"):
                _run_git(["status"])

    def test_git_timeout_error(self):
        """Should handle git command timeouts."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 60)):
            with pytest.raises(GitError, match="timed out"):
                _run_git(["status"])

    def test_credential_output_hidden(self):
        """Errors containing credential-like words should be masked."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="fatal: could not read password for token"
            )
            with pytest.raises(GitError, match="hidden"):
                _run_git(["push"])


class TestGitCommands:
    """Test git command construction."""

    def test_stage_files_calls_git_add(self):
        """stage_files should call 'git add --' for each file."""
        with patch("auto_commit.git._run_git") as mock:
            stage_files([".auto-commit/activity.json", ".auto-commit/state.json"])

            assert mock.call_count == 2
            mock.assert_any_call(["add", "--", ".auto-commit/activity.json"], cwd=None)
            mock.assert_any_call(["add", "--", ".auto-commit/state.json"], cwd=None)
