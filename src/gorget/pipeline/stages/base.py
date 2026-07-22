"""Common `Stage` interface implemented by fetch/transform/verify/policy/emit."""

from __future__ import annotations

from typing import ClassVar, Protocol

from gorget.config.schema import PipelineSpec
from gorget.context import RunContext
from gorget.pipeline.result import StageResult
from gorget.pipeline.state import StageState


class Stage(Protocol):
    name: ClassVar[str]

    def run(self, ctx: RunContext, spec: PipelineSpec, state: StageState) -> StageResult: ...
