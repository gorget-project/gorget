"""Artifacts carried through acquisition, derivation, checks, and publication."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gorget.constants import CHECKSUM_ALGO
from gorget.util.checksum import compute_digest


@dataclass(frozen=True, kw_only=True)
class Artifact:
    path: Path
    output_name: str
    source_description: str
    checksum: str | None
    version_change_eligible: bool = False
    allow_version_change: bool = False


def build_artifact(
    path: Path,
    output_name: str,
    source_description: str,
    dry_run: bool,
    *,
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
    )


def artifact_report_dict(artifact: Artifact) -> dict:
    return {
        "output_name": artifact.output_name,
        "source_description": artifact.source_description,
        "checksum": artifact.checksum,
    }
