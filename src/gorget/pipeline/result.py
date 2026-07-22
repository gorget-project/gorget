"""Dataclasses backing `report.json`."""

from __future__ import annotations

from dataclasses import dataclass, field

from gorget.fetch.base import FetchedArtifact, artifact_report_dict


@dataclass(frozen=True, kw_only=True)
class StageResult:
    name: str
    status: str  # "success" | "skipped"
    reason: str | None = None

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "reason": self.reason}


@dataclass(kw_only=True)
class PipelineReport:
    package: str
    version: str
    old_version: str | None
    dry_run: bool
    stages: list[StageResult] = field(default_factory=list)
    artifacts: list[FetchedArtifact] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "package": self.package,
            "version": self.version,
            "old_version": self.old_version,
            "dry_run": self.dry_run,
            "stages": [stage.to_dict() for stage in self.stages],
            "artifacts": [artifact_report_dict(artifact) for artifact in self.artifacts],
        }
