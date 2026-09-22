"""Artifacts carried through acquisition, derivation, checks, and publication."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from gorget.constants import CHECKSUM_ALGO
from gorget.util.checksum import compute_digest

ArtifactKind = Literal["input", "derived"]


@dataclass(frozen=True, kw_only=True)
class ArtifactRef:
    output_name: str
    checksum: str | None


@dataclass(frozen=True, kw_only=True)
class Artifact:
    path: Path
    output_name: str
    source_description: str
    checksum: str | None
    version_change_eligible: bool = False
    allow_version_change: bool = False
    kind: ArtifactKind = "input"
    parents: tuple[ArtifactRef, ...] = ()

    def ref(self) -> ArtifactRef:
        return ArtifactRef(output_name=self.output_name, checksum=self.checksum)


def _build_artifact(
    path: Path,
    output_name: str,
    source_description: str,
    dry_run: bool,
    *,
    kind: ArtifactKind,
    parents: Iterable[Artifact] = (),
    version_change_eligible: bool = False,
    allow_version_change: bool = False,
) -> Artifact:
    checksum = None if dry_run else compute_digest(path, CHECKSUM_ALGO)
    return Artifact(
        path=path,
        output_name=output_name,
        source_description=source_description,
        checksum=checksum,
        version_change_eligible=version_change_eligible,
        allow_version_change=allow_version_change,
        kind=kind,
        parents=tuple(parent.ref() for parent in parents),
    )


def build_input_artifact(
    path: Path,
    output_name: str,
    source_description: str,
    dry_run: bool,
    *,
    version_change_eligible: bool = False,
    allow_version_change: bool = False,
) -> Artifact:
    return _build_artifact(
        path,
        output_name,
        source_description,
        dry_run,
        kind="input",
        version_change_eligible=version_change_eligible,
        allow_version_change=allow_version_change,
    )


def build_derived_artifact(
    path: Path,
    output_name: str,
    source_description: str,
    dry_run: bool,
    *,
    parents: Iterable[Artifact] = (),
) -> Artifact:
    return _build_artifact(
        path,
        output_name,
        source_description,
        dry_run,
        kind="derived",
        parents=parents,
    )


def build_artifact(
    path: Path,
    output_name: str,
    source_description: str,
    dry_run: bool,
    *,
    version_change_eligible: bool = False,
    allow_version_change: bool = False,
) -> Artifact:
    """Build an input artifact using the pre-artifact-model interface."""
    return build_input_artifact(
        path,
        output_name,
        source_description,
        dry_run,
        version_change_eligible=version_change_eligible,
        allow_version_change=allow_version_change,
    )


def artifact_report_dict(artifact: Artifact) -> dict:
    return {
        "output_name": artifact.output_name,
        "source_description": artifact.source_description,
        "checksum": artifact.checksum,
    }
