"""Transform execution settings and access to the shared source workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from gorget.config.schema import ToolchainEntry, TransformStep
from gorget.config.substitution import SubstitutionVars
from gorget.pipeline.source import SourceWorkspace
from gorget.pipeline.state import StageState


@dataclass(kw_only=True)
class TransformContext:
    work_dir: Path
    source: SourceWorkspace
    vars: SubstitutionVars
    toolchain: list[ToolchainEntry]
    dry_run: bool
    package_dir: Path

    @property
    def source_dir(self) -> Path | None:
        """Read-only view for handlers that require a materialized source."""
        return self.source.path


class TransformStepHandler(Protocol):
    def run(self, step: TransformStep, ctx: TransformContext, state: StageState) -> None: ...


def ensure_source_dir(ctx: TransformContext, state: StageState, target: str | None = None) -> Path:
    """Resolve source access through the workspace owner."""
    if state.source.path is None and ctx.source.path is not None:
        state.source = ctx.source
    ctx.source = state.source
    return state.source.select(ctx.work_dir, state.artifacts, target, detached=target is not None)
