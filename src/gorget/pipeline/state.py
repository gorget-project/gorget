"""Mutable state threaded through the pipeline.

Acquired inputs remain available for verification. ``artifacts`` is the current
publication set and can contain replacements derived from those inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from gorget.exceptions import GorgetConfigError
from gorget.pipeline.artifact import Artifact
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.source import SourceWorkspace
from gorget.specfile import SpecFile


@dataclass(kw_only=True)
class StageState:
    work_dir: Path
    spec: SpecFile
    report: PipelineReport
    input_artifacts: list[Artifact] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    source: SourceWorkspace = field(default_factory=SourceWorkspace)

    def __post_init__(self) -> None:
        # Same list object, not a copy: as FetchStage extends `artifacts`,
        # `report.artifacts` (and report.to_dict()) reflect it automatically --
        # no separate "collect artifacts into the report" step needed anywhere.
        self.report.artifacts = self.artifacts

    def find_artifact(self, output_name: str) -> Artifact:
        for artifact in self.artifacts:
            if artifact.output_name == output_name:
                return artifact
        raise GorgetConfigError(f"No publication artifact named {output_name!r}")

    def find_input_artifact(self, output_name: str) -> Artifact:
        for artifact in self.input_artifacts:
            if artifact.output_name == output_name:
                return artifact
        raise GorgetConfigError(f"No acquired input artifact named {output_name!r}")

    def add_input_artifacts(self, artifacts: list[Artifact]) -> None:
        self.input_artifacts.extend(artifacts)
        self.artifacts.extend(artifacts)

    def replace_artifact(self, replacement: Artifact) -> None:
        for index, artifact in enumerate(self.artifacts):
            if artifact.output_name == replacement.output_name:
                self.artifacts[index] = replacement
                return
        raise GorgetConfigError(
            f"Cannot replace missing artifact {replacement.output_name!r}"
        )
