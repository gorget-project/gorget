"""Real, non-mocked tests for commit_timestamp().

Requires `git` on PATH -- skipped automatically if missing.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from gorget.util.git import commit_timestamp

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="requires git on PATH")


def _run_git(args: list[str], cwd: Path) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@requires_git
def test_returns_commit_timestamp_for_a_real_repo(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _run_git(["init", "-b", "main"], repo_dir)
    _run_git(["config", "user.email", "test@example.com"], repo_dir)
    _run_git(["config", "user.name", "Test"], repo_dir)
    (repo_dir / "f.txt").write_text("x")
    _run_git(["add", "."], repo_dir)
    _run_git(["commit", "--date=2024-01-01T00:00:00", "-m", "initial"], repo_dir)

    assert commit_timestamp(repo_dir) > 0


def test_returns_zero_for_a_non_git_directory(tmp_path):
    """Regression test: a vendor step's source isn't always a git clone -- a
    `url` fetch (extracted tarball) or a `run` step's generated directory
    (e.g. OCB's _build/, freshly created and never git-tracked) has no commit
    history to derive a timestamp from. Must fall back to a fixed epoch
    instead of raising, since the underlying goal (reproducible mtimes) holds
    just as well for a constant.
    """
    plain_dir = tmp_path / "not-a-repo"
    plain_dir.mkdir()
    (plain_dir / "f.txt").write_text("x")

    assert commit_timestamp(plain_dir) == 0


@requires_git
def test_returns_zero_for_a_directory_outside_any_git_repo(tmp_path):
    """Even if the machine running gorget happens to have an ancestor
    directory under git (e.g. a CI checkout), a plain extracted-tarball
    directory with no .git of its own must still fall back to 0, not
    accidentally pick up an unrelated ancestor repo's commit history.
    """
    assert commit_timestamp(tmp_path) == 0
