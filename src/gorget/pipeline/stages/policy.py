"""`PolicyStage`: no-op stub. Real behavior lands in HUM-4867.

A future policy check that fails should raise `GorgetPolicyViolation` from within
this stage's `run()` -- that's the seam `pipeline.runner.PipelineRunner` is built
to propagate (uncaught, up through `cli.main()`'s exception boundary) as exit
code 2.
"""

from __future__ import annotations

from typing import ClassVar

from gorget.config.schema import PipelineSpec
from gorget.context import RunContext
from gorget.pipeline.result import StageResult
from gorget.pipeline.state import StageState


class PolicyStage:
    name: ClassVar[str] = "policy"

    def run(self, ctx: RunContext, spec: PipelineSpec, state: StageState) -> StageResult:
        return StageResult(
            name=self.name, status="skipped", reason="not implemented (future story)"
        )
