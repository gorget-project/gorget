"""Real, non-mocked regression test asserting git-fetched archives are
reproducible.

Confirms the fix for a bug where `GitHandler.run()` -> `make_tar_gz()`
preserved each file's live filesystem mtime as set by the git clone/checkout
operation (checkout wall-clock time) instead of the underlying commit's own
timestamp -- and where the archive's gzip container header separately embedded
its own wall-clock compression time. Either alone was enough to make two runs
of the exact same pipeline (same repo, same ref) produce byte-different
archives -- and thus different checksums -- every time, defeating the Verify
stage's republication check for any git-fetched source.

Requires `git` on PATH -- skipped automatically if missing. No subprocess
mocking: this clones a real local repo twice, exactly as production does.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from gorget.config.schema import GitStep
from gorget.config.substitution import SubstitutionVars
from gorget.fetch.base import FetchContext
from gorget.fetch.git import GitHandler

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="requires git on PATH")


def _run_git(args: list[str], cwd: Path) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def demo_repo(tmp_path: Path) -> Path:
    """A tiny local git repo, committed once, that later gets checked out
    (cloned) more than once -- each checkout happening at a different
    wall-clock moment, the exact condition that used to produce different
    archive checksums.
    """
    repo_dir = tmp_path / "demo-repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("hello\n")
    (repo_dir / "sub").mkdir()
    (repo_dir / "sub" / "inner.txt").write_text("world\n")
    _run_git(["init", "-b", "main"], repo_dir)
    _run_git(["config", "user.email", "test@example.com"], repo_dir)
    _run_git(["config", "user.name", "Test"], repo_dir)
    _run_git(["add", "."], repo_dir)
    _run_git(["commit", "-m", "initial"], repo_dir)
    return repo_dir


def make_ctx(work_dir: Path) -> FetchContext:
    work_dir.mkdir(parents=True, exist_ok=True)
    return FetchContext(
        work_dir=work_dir,
        package_dir=work_dir,
        spec=Mock(),
        vars=SubstitutionVars(
            version="1.0.0", old_version=None, package="demo", spec_file="demo.spec"
        ),
        dry_run=False,
    )


@pytest.mark.integration
@requires_git
def test_repeated_git_fetch_of_unchanged_ref_produces_identical_checksum(tmp_path, demo_repo):
    step = GitStep(repo=str(demo_repo), ref="main", shallow=True)

    checksums = []
    for i in range(2):
        # A real, measurable gap between clones -- the checkout mtime and the
        # gzip container's own wall-clock timestamp would both differ across
        # this gap if either were left unpinned.
        if i:
            time.sleep(1.1)
        artifacts = GitHandler().run(step, make_ctx(tmp_path / f"run{i}"))
        assert artifacts[0].checksum is not None
        checksums.append(artifacts[0].checksum)

    assert checksums[0] == checksums[1]


@pytest.mark.integration
@requires_git
def test_cloning_same_ref_into_separate_directories_produces_identical_checksum(
    tmp_path, demo_repo
):
    """Same assertion, but via two independent clones side by side (as the bug
    report's own repro used) rather than two sequential runs of one step.
    """
    step = GitStep(repo=str(demo_repo), ref="main", shallow=True)

    artifacts_a = GitHandler().run(step, make_ctx(tmp_path / "a"))
    time.sleep(1.1)
    artifacts_b = GitHandler().run(step, make_ctx(tmp_path / "b"))

    assert artifacts_a[0].checksum == artifacts_b[0].checksum
