"""`git` fetch step: clone a repo at a ref and archive the checkout (or a subdir).

Shallow (`--depth 1`) clones work cleanly for tag/branch refs. Most git servers
reject shallow-fetching an arbitrary commit SHA, so a SHA-like ref falls back to a
best-effort partial clone (`--filter=blob:none`) instead of promising true
`--depth 1` semantics.
"""

from __future__ import annotations

import re
from pathlib import Path

from gorget.config.schema import GitStep
from gorget.exceptions import GorgetTransientError
from gorget.fetch.base import FetchContext, FetchedArtifact, build_artifact
from gorget.util.archive import make_tar_gz, strip_archive_suffix
from gorget.util.git import commit_timestamp
from gorget.util.subprocess_run import run

_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_SLUG_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _looks_like_sha(ref: str) -> bool:
    return bool(_SHA_RE.match(ref))


def _slug(repo_url: str) -> str:
    return _SLUG_RE.sub("_", repo_url).strip("_")


class GitHandler:
    def run(self, step: GitStep, ctx: FetchContext) -> list[FetchedArtifact]:
        archive_name = step.archive_name or f"{ctx.vars.package}-{ctx.vars.version}.tar.gz"
        archive_path = ctx.work_dir / archive_name

        if not ctx.dry_run:
            clone_dir = ctx.work_dir / "_git" / _slug(step.repo)
            self._clone(step, clone_dir)
            ctx.source_dir = clone_dir
            src = (clone_dir / step.subdir) if step.subdir else clone_dir
            mtime = commit_timestamp(clone_dir)
            # The archive's internal directory is what %setup/%autosetup
            # extracts into, so it must match the archive's own filename, not
            # `ctx.vars.package` (the spec's filename stem, which can legally
            # differ from the archive's actual basename -- e.g. helm4's spec
            # is named helm.spec, or kubernetes1.35's archives are just
            # "kubernetes-*" since that's the upstream repo name, not the
            # RPM's own versioned package name).
            arcname = strip_archive_suffix(archive_name)
            make_tar_gz(src, archive_path, arcname=arcname, mtime=mtime)

        return [build_artifact(archive_path, archive_name, step.repo, ctx.dry_run)]

    def _clone(self, step: GitStep, dest: Path) -> None:
        if step.shallow and not _looks_like_sha(step.ref):
            self._run_git(
                [
                    "git", "clone",
                    "--branch", step.ref,
                    "--single-branch",
                    "--depth", "1",
                    step.repo, str(dest),
                ],
                f"git clone --branch {step.ref} failed for {step.repo}",
            )
            return

        clone_args = (
            ["git", "clone", "--filter=blob:none", step.repo, str(dest)]
            if step.shallow
            else ["git", "clone", step.repo, str(dest)]
        )
        self._run_git(clone_args, f"git clone failed for {step.repo}")
        self._run_git(["git", "checkout", step.ref], f"git checkout {step.ref} failed", cwd=dest)

    def _run_git(self, args: list[str], error_prefix: str, *, cwd: Path | None = None) -> None:
        result = run(args, cwd=cwd)
        if result.returncode != 0:
            raise GorgetTransientError(f"{error_prefix}: {result.stderr.strip()}")
