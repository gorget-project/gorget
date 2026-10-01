"""Derive source revisions and additional artifacts in declared order."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from gorget.config.schema import (
    PackStep,
    PipelineSpec,
    RunStep,
    StripTarballStep,
    VendorBumpStep,
    VendorStep,
)
from gorget.context import RunContext
from gorget.exceptions import GorgetConfigError
from gorget.pipeline.result import StageResult
from gorget.pipeline.source import SourceWorkspace
from gorget.pipeline.state import StageState
from gorget.transform.base import TransformContext, ensure_source_dir
from gorget.transform.pack import PackHandler
from gorget.transform.run_step import RunHandler
from gorget.transform.strip_tarball import StripTarballHandler
from gorget.transform.vendor import VendorHandler
from gorget.transform.vendor.base import VendorResult
from gorget.transform.vendor_bump import VendorBumpHandler

_vendor_handler = VendorHandler()


class _VendorStepAdapter:
    """Add vendor artifacts and policy workspaces to pipeline state."""

    def run(self, step: VendorStep, ctx: TransformContext, state: StageState) -> None:
        if not ctx.dry_run:
            if step.source is not None:
                artifact = state.find_artifact(step.source)
                if state.source.path is not None and state.source.artifact is not artifact:
                    if state.source.dirty:
                        raise GorgetConfigError(
                            "Cannot switch vendor sources while the active workspace "
                            "has uncommitted changes"
                        )
                    state.source = SourceWorkspace()
                    ctx.source_dir = None
                state.source.materialize(ctx.work_dir, [artifact])
            ensure_source_dir(ctx, state)
        result: VendorResult = _vendor_handler.run(step, ctx)
        state.add_derived_artifacts(result.artifacts)
        state.vendored_modules.extend(result.modules)
        if result.source_changed or step.sync_go_modules:
            state.source.mark_dirty()


# See `fetch/stages/fetch.py` for why this dict is typed loosely rather than
# fighting Protocol contravariance for a dynamic, type-based dispatch table.
_HANDLERS: dict[type, Any] = {
    StripTarballStep: StripTarballHandler(),
    VendorBumpStep: VendorBumpHandler(),
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
