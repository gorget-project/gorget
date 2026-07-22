"""`VerifyStage`: no-op stub. Real behavior lands in HUM-4866."""

from __future__ import annotations

from typing import ClassVar

from gorget.config.schema import PipelineSpec
from gorget.context import RunContext
from gorget.pipeline.result import StageResult
from gorget.pipeline.state import StageState


class VerifyStage:
    name: ClassVar[str] = "verify"

    def run(self, ctx: RunContext, spec: PipelineSpec, state: StageState) -> StageResult:
        return StageResult(
            name=self.name, status="skipped", reason="not implemented (future story)"
        )
