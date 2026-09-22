"""Derive source revisions and additional artifacts in declared order."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from gorget.config.schema import (
    BuildUiStep,
    PackStep,
    PipelineSpec,
    RunStep,
    StripTarballStep,
    VendorBumpStep,
    VendorStep,
)
from gorget.context import RunContext
from gorget.fetch.vendor import VendorHandler
from gorget.pipeline.artifact import Artifact
from gorget.pipeline.result import StageResult
from gorget.pipeline.state import StageState
from gorget.transform.base import TransformContext
from gorget.transform.build_ui import BuildUiHandler
from gorget.transform.pack import PackHandler
from gorget.transform.run_step import RunHandler
from gorget.transform.strip_tarball import StripTarballHandler
from gorget.transform.vendor_bump import VendorBumpHandler

_vendor_handler = VendorHandler()


class _VendorStepAdapter:
    """Add `VendorHandler`'s returned artifacts to pipeline state."""

    def run(self, step: VendorStep, ctx: TransformContext, state: StageState) -> None:
        artifacts: list[Artifact] = _vendor_handler.run(step, ctx)
        state.artifacts.extend(artifacts)
        if step.sync_go_modules:
            state.source.mark_dirty()


# See `fetch/stages/fetch.py` for why this dict is typed loosely rather than
# fighting Protocol contravariance for a dynamic, type-based dispatch table.
_HANDLERS: dict[type, Any] = {
    StripTarballStep: StripTarballHandler(),
    VendorBumpStep: VendorBumpHandler(),
    BuildUiStep: BuildUiHandler(),
    RunStep: RunHandler(),
    VendorStep: _VendorStepAdapter(),
    PackStep: PackHandler(),
}

logger = logging.getLogger("gorget.pipeline")


class TransformStage:
    name: ClassVar[str] = "transform"

    def run(self, ctx: RunContext, spec: PipelineSpec, state: StageState) -> StageResult:
        if not spec.transform.steps:
            return StageResult(
                name=self.name, status="skipped", reason="no transform steps declared"
            )

        transform_ctx = TransformContext(
            work_dir=state.work_dir,
            source_dir=state.source.path,
            vars=ctx.vars,
            toolchain=spec.toolchain.entries,
            dry_run=ctx.dry_run,
            package_dir=ctx.package_dir,
        )
        for step in spec.transform.steps:
            handler = _HANDLERS[type(step)]
            logger.debug("transform step: %s", step)
            handler.run(step, transform_ctx, state)

        revision = state.source.commit(state.work_dir, dry_run=ctx.dry_run)
        if revision is not None:
            state.replace_artifact(revision)
        return StageResult(name=self.name, status="success")
