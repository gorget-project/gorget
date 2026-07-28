"""Shared git plumbing helpers."""

from __future__ import annotations

from pathlib import Path

from gorget.exceptions import GorgetTransientError
from gorget.util.subprocess_run import run


def commit_timestamp(repo_dir: Path, ref: str = "HEAD") -> int:
    """Return the commit timestamp (seconds since epoch) of `ref` in `repo_dir`,
    or a fixed epoch (0) if `repo_dir` isn't a git checkout at all.

    Used to stamp archive member mtimes with the commit's own timestamp instead
    of the checkout's live filesystem mtimes, so that re-fetching an unchanged
    ref produces byte-identical tarballs across runs. `repo_dir` isn't always a
    git clone, though -- a `vendor` step's source can come from a `url` fetch
    (extracted tarball) or a `run` step's generated directory (e.g. OCB's
    _build/, which is created fresh, not git-tracked). There's no commit
    history to derive a timestamp from in that case, but the same
    reproducibility goal holds: a fixed epoch is trivially reproducible too.
    """
    is_repo = run(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_dir)
    if is_repo.returncode != 0:
        return 0
    result = run(["git", "log", "-1", "--format=%ct", ref], cwd=repo_dir)
    if result.returncode != 0:
        raise GorgetTransientError(
            f"git log -1 --format=%ct {ref} failed: {result.stderr.strip()}"
        )
    return int(result.stdout.strip())
