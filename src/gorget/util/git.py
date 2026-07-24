"""Shared git plumbing helpers."""

from __future__ import annotations

from pathlib import Path

from gorget.exceptions import GorgetTransientError
from gorget.util.subprocess_run import run


def commit_timestamp(repo_dir: Path, ref: str = "HEAD") -> int:
    """Return the commit timestamp (seconds since epoch) of `ref` in `repo_dir`.

    Used to stamp archive member mtimes with the commit's own timestamp instead
    of the checkout's live filesystem mtimes, so that re-fetching an unchanged
    ref produces byte-identical tarballs across runs.
    """
    result = run(["git", "log", "-1", "--format=%ct", ref], cwd=repo_dir)
    if result.returncode != 0:
        raise GorgetTransientError(
            f"git log -1 --format=%ct {ref} failed: {result.stderr.strip()}"
        )
    return int(result.stdout.strip())
