"""Shared interface for fetch step handlers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from gorget.config.schema import FetchStep, ToolchainEntry
from gorget.config.substitution import SubstitutionVars
from gorget.pipeline.artifact import Artifact
from gorget.pipeline.artifact import artifact_report_dict as artifact_report_dict
from gorget.pipeline.artifact import build_artifact as build_artifact
from gorget.specfile import SpecFile

# Compatibility for integrations importing the old implementation-level name.
FetchedArtifact = Artifact


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
    toolchain: list[ToolchainEntry] = field(default_factory=list)


class FetchStepHandler(Protocol):
    def run(self, step: FetchStep, ctx: FetchContext) -> list[Artifact]: ...
