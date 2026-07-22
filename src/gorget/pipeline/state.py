"""Mutable state threaded through the stage pipeline (fetch's artifacts feed emit)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from gorget.fetch.base import FetchedArtifact
from gorget.pipeline.result import PipelineReport
from gorget.specfile import SpecFile


@dataclass(kw_only=True)
class StageState:
    work_dir: Path
    spec: SpecFile
    report: PipelineReport
    artifacts: list[FetchedArtifact] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Same list object, not a copy: as FetchStage extends `artifacts`,
        # `report.artifacts` (and report.to_dict()) reflect it automatically --
        # no separate "collect artifacts into the report" step needed anywhere.
        self.report.artifacts = self.artifacts
