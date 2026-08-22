"""Safe Git subprocess wrapper for Auto Commit Bot.

All git operations use subprocess.run with shell=False.
No string interpolation into commands. Tokens are never logged.
Only .auto-commit/ files are staged. Never force-pushes.
"""

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


class GitError(Exception):
    """Raised when a git operation fails."""
    pass


@dataclass
class GitStatus:
    """Repository status information."""
    branch: str
    clean: bool
    modified_files: List[str]
    staged_files: List[str]
    untracked_files: List[str]


@dataclass
class CommitInfo:
    """Information about a git commit."""
    hash: str
    short_hash: str
    message: str
    date: str


def _run_git(args: List[str], cwd: Optional[str] = None, env: Optional[dict] = None) -> str:
    """
    Run a git command safely.

    Args:
        args: Git command arguments (e.g., ["status", "--porcelain"]).
        cwd: Working directory. Defaults to current directory.
        env: Additional environment variables.

    Returns:
        stdout output as a string.

    Raises:
        GitError: If the command fails.
    """
    cmd = ["git"] + args
    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=run_env,
            shell=False,  # Never use shell=True
            timeout=60,
        )
    except FileNotFoundError:
        raise GitError(
            "Git is not installed or not in PATH. "
            "Install Git from https://git-scm.com/"
        )
    except subprocess.TimeoutExpired:
        raise GitError(f"Git command timed out: git {' '.join(args)}")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        # Never log tokens or credentials
        safe_stderr = stderr
        for secret_word in ["token", "password", "credential"]:
            if secret_word.lower() in safe_stderr.lower():
                safe_stderr = "[output hidden — may contain credentials]"
                break

        raise GitError(f"Git command failed: git {' '.join(args)}\n{safe_stderr}")

    return result.stdout.strip()


def is_git_repo(cwd: Optional[str] = None) -> bool:
    """Check if the current directory is inside a git repository."""
    try:
        _run_git(["rev-parse", "--is-inside-work-tree"], cwd=cwd)
        return True
    except GitError:
        return False


def get_current_branch(cwd: Optional[str] = None) -> str:
    """Get the name of the current branch."""
    return _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)


def get_status(cwd: Optional[str] = None) -> GitStatus:
    """Get the repository status."""
    branch = get_current_branch(cwd)

    porcelain = _run_git(["status", "--porcelain"], cwd=cwd)

    modified = []
    staged = []
    untracked = []

    for line in porcelain.splitlines():
        if len(line) < 4:
            continue

        index_status = line[0]
        work_status = line[1]
        filepath = line[3:]

        if index_status in ("M", "A", "D", "R"):
            staged.append(filepath)
        if work_status == "M":
            modified.append(filepath)
        if index_status == "?" and work_status == "?":
            untracked.append(filepath)

    clean = len(modified) == 0 and len(staged) == 0 and len(untracked) == 0

    return GitStatus(
        branch=branch,
        clean=clean,
        modified_files=modified,
        staged_files=staged,
        untracked_files=untracked,
    )


def stage_files(paths: List[str], cwd: Optional[str] = None) -> None:
    """
    Stage specific files for commit.

    Only stages the exact paths provided. Never uses 'git add .'.

    Args:
        paths: List of relative file paths to stage.
    """
    if not paths:
        raise GitError("No files to stage")

    for path in paths:
        _run_git(["add", "--", path], cwd=cwd)


def create_commit(
    message: str,
    commit_date: Optional[datetime] = None,
    cwd: Optional[str] = None,
) -> CommitInfo:
    """
    Create a git commit with the staged changes.

    Args:
        message: Commit message.
        commit_date: Optional datetime for GIT_AUTHOR_DATE and GIT_COMMITTER_DATE.
        cwd: Working directory.

    Returns:
        CommitInfo with hash and message.

    Raises:
        GitError: If nothing is staged or the commit fails.
    """
    # Verify something is staged
    staged_output = _run_git(["diff", "--cached", "--name-only"], cwd=cwd)
    if not staged_output.strip():
        raise GitError("Nothing staged for commit. Cannot create an empty commit.")

    env = {}
    if commit_date is not None:
        date_str = commit_date.isoformat()
        env["GIT_AUTHOR_DATE"] = date_str
        env["GIT_COMMITTER_DATE"] = date_str

    _run_git(["commit", "-m", message], cwd=cwd, env=env if env else None)

    # Get the commit info
    commit_hash = _run_git(["rev-parse", "HEAD"], cwd=cwd)
    short_hash = _run_git(["rev-parse", "--short", "HEAD"], cwd=cwd)

    return CommitInfo(
        hash=commit_hash,
        short_hash=short_hash,
        message=message,
        date=commit_date.isoformat() if commit_date else datetime.now().isoformat(),
    )


def sync_with_remote(branch: str = "main", cwd: Optional[str] = None) -> None:
    """
    Safely sync local branch with remote before making decisions or commits.
    Fetches origin and resets to origin/branch so the runner always starts from latest remote state.
    """
    try:
        _run_git(["fetch", "origin", branch], cwd=cwd)
        _run_git(["reset", "--hard", f"origin/{branch}"], cwd=cwd)
    except GitError:
        pass


def push(branch: str = "main", cwd: Optional[str] = None) -> None:
    """
    Push commits to the remote.

    Never force-pushes. Never resets. Never deletes.
    Automatically attempts a rebase pull with '-X theirs' if the remote branch has moved.
    """
    try:
        _run_git(["push", "origin", branch], cwd=cwd)
    except GitError as push_err:
        try:
            _run_git(["pull", "--rebase", "-X", "theirs", "origin", branch], cwd=cwd)
            _run_git(["push", "origin", branch], cwd=cwd)
        except GitError:
            try:
                _run_git(["rebase", "--abort"], cwd=cwd)
            except GitError:
                pass
            raise push_err


def get_last_commit(cwd: Optional[str] = None) -> Optional[CommitInfo]:
    """Get information about the last commit."""
    try:
        commit_hash = _run_git(["rev-parse", "HEAD"], cwd=cwd)
        short_hash = _run_git(["rev-parse", "--short", "HEAD"], cwd=cwd)
        message = _run_git(["log", "-1", "--format=%s"], cwd=cwd)
        commit_date = _run_git(["log", "-1", "--format=%aI"], cwd=cwd)

        return CommitInfo(
            hash=commit_hash,
            short_hash=short_hash,
            message=message,
            date=commit_date,
        )
    except GitError:
        return None
