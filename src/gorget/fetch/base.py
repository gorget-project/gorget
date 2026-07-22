"""Shared interface for fetch step handlers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from gorget.config.schema import FetchStep
from gorget.config.substitution import SubstitutionVars
from gorget.constants import CHECKSUM_ALGO
from gorget.specfile import SpecFile
from gorget.util.checksum import compute_digest


@dataclass(frozen=True, kw_only=True)
class FetchedArtifact:
    path: Path
    output_name: str
    source_description: str
    checksum: str | None  # None under --dry-run, when no bytes were actually fetched


@dataclass(kw_only=True)
class FetchContext:
    work_dir: Path
    package_dir: Path
    spec: SpecFile
    vars: SubstitutionVars
    dry_run: bool
    # Set by a `git` step after cloning, so a later `vendor` step in the same
    # fetch list knows which checkout to vendor against (e.g. the etcd
    # multi-submodule case: git-fetch the repo, then vendor several subdirs of it).
    source_dir: Path | None = None


class FetchStepHandler(Protocol):
    def run(self, step: FetchStep, ctx: FetchContext) -> list[FetchedArtifact]: ...


def build_artifact(
    path: Path, output_name: str, source_description: str, dry_run: bool
) -> FetchedArtifact:
    checksum = None if dry_run else compute_digest(path, CHECKSUM_ALGO)
    return FetchedArtifact(
        path=path, output_name=output_name, source_description=source_description, checksum=checksum
    )


def artifact_report_dict(artifact: FetchedArtifact) -> dict:
    return {
        "output_name": artifact.output_name,
        "source_description": artifact.source_description,
        "checksum": artifact.checksum,
    }
