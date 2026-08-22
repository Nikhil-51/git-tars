"""Pre-commit safety checks for Auto Commit Bot.

Validates repository state before allowing a commit.
Ensures only .auto-commit/ files are modified, rejects dangerous files,
and verifies branch and repository integrity.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional

from auto_commit.config import SafetyConfig
from auto_commit import git as git_ops


@dataclass
class SafetyResult:
    """Result of safety validation."""
    safe: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def format_report(self) -> str:
        """Format a human-readable safety report."""
        if self.safe:
            return "✓ Safety checks passed"

        lines = ["✗ Safety checks FAILED", ""]
        for error in self.errors:
            lines.append(f"  ERROR: {error}")
        for warning in self.warnings:
            lines.append(f"  WARNING: {warning}")
        return "\n".join(lines)


class SafetyValidator:
    """
    Validates repository state before committing.

    Checks:
    - Current branch matches configuration
    - Only allowed paths are modified
    - No forbidden files (secrets, credentials, .env)
    - No oversized files
    - Repository is not in a broken state (detached HEAD, rebase, merge)
    """

    def __init__(self, config: SafetyConfig, expected_branch: str = "main"):
        self._config = config
        self._expected_branch = expected_branch

    def validate(self, cwd: Optional[str] = None) -> SafetyResult:
        """Run all safety checks."""
        errors = []
        warnings = []

        # Check 1: Is this a git repo?
        if not git_ops.is_git_repo(cwd):
            return SafetyResult(
                safe=False,
                errors=["Not a git repository. Cannot proceed."]
            )

        # Check 2: Correct branch
        try:
            branch = git_ops.get_current_branch(cwd)
            if branch == "HEAD":
                errors.append("Repository is in detached HEAD state.")
            elif branch != self._expected_branch:
                errors.append(
                    f"Expected branch '{self._expected_branch}', "
                    f"but currently on '{branch}'."
                )
        except git_ops.GitError as e:
            errors.append(f"Could not determine branch: {e}")

        # Check 3: Check staged files
        try:
            status = git_ops.get_status(cwd)
            all_changed = status.staged_files + status.modified_files

            for filepath in all_changed:
                if not self._is_allowed_path(filepath):
                    errors.append(
                        f"Unexpected modified file: {filepath}. "
                        f"Only files in {self._config.allowed_paths} may be changed."
                    )

                if self._is_forbidden_file(filepath):
                    errors.append(
                        f"Forbidden file detected: {filepath}. "
                        f"This file must not be committed."
                    )

        except git_ops.GitError as e:
            errors.append(f"Could not check repository status: {e}")

        # Check 4: Check for oversized files
        for allowed_path in self._config.allowed_paths:
            if os.path.isdir(allowed_path):
                for root, dirs, files in os.walk(allowed_path):
                    for filename in files:
                        filepath = os.path.join(root, filename)
                        try:
                            size_kb = os.path.getsize(filepath) / 1024
                            if size_kb > self._config.max_file_size_kb:
                                errors.append(
                                    f"File too large: {filepath} "
                                    f"({size_kb:.1f} KB > {self._config.max_file_size_kb} KB)"
                                )
                        except OSError:
                            warnings.append(f"Could not check file size: {filepath}")

        # Check 5: Repository integrity
        try:
            # Check for ongoing rebase
            git_dir = self._find_git_dir(cwd)
            if git_dir:
                rebase_path = os.path.join(git_dir, "rebase-merge")
                rebase_apply_path = os.path.join(git_dir, "rebase-apply")
                merge_head_path = os.path.join(git_dir, "MERGE_HEAD")

                if os.path.exists(rebase_path) or os.path.exists(rebase_apply_path):
                    errors.append("Repository has an ongoing rebase. Resolve it first.")
                if os.path.exists(merge_head_path):
                    errors.append("Repository has an ongoing merge. Resolve it first.")
        except Exception:
            warnings.append("Could not check repository integrity.")

        return SafetyResult(
            safe=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _is_allowed_path(self, filepath: str) -> bool:
        """Check if a file path is within the allowed paths."""
        normalized = filepath.replace("\\", "/")
        for allowed in self._config.allowed_paths:
            allowed_norm = allowed.replace("\\", "/").rstrip("/")
            if normalized == allowed_norm or normalized.startswith(allowed_norm + "/"):
                return True
        return False

    def _is_forbidden_file(self, filepath: str) -> bool:
        """Check if a file matches any forbidden pattern."""
        normalized = filepath.replace("\\", "/").lower()
        basename = os.path.basename(normalized)

        for pattern in self._config.forbidden_patterns:
            pattern_lower = pattern.lower()
            if pattern_lower in basename or pattern_lower in normalized:
                return True

        return False

    def _find_git_dir(self, cwd: Optional[str] = None) -> Optional[str]:
        """Find the .git directory."""
        search_dir = cwd or os.getcwd()
        git_dir = os.path.join(search_dir, ".git")
        if os.path.isdir(git_dir):
            return git_dir
        return None
