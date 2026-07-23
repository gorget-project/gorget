"""Orchestrates fetch -> transform -> verify -> policy -> emit.

`--dry-run` runs every stage for real except `EmitStage`, which is skipped
entirely (no `/output` writes) -- each fetch-step handler already knows how to
resolve/validate without touching the network or filesystem under dry-run
(see `fetch/base.py`'s `build_artifact`).
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from gorget import toolchain
from gorget.config.schema import PipelineSpec
from gorget.context import RunContext
from gorget.pipeline.result import PipelineReport, StageResult
from gorget.pipeline.stages.base import Stage
from gorget.pipeline.stages.emit import EmitStage
from gorget.pipeline.stages.fetch import FetchStage
from gorget.pipeline.stages.policy import PolicyStage
from gorget.pipeline.stages.transform import TransformStage
from gorget.pipeline.stages.verify import VerifyStage
from gorget.pipeline.state import StageState
from gorget.specfile import SpecFile

STAGE_ORDER: list[type[Stage]] = [FetchStage, TransformStage, VerifyStage, PolicyStage, EmitStage]

logger = logging.getLogger("gorget.pipeline")


class PipelineRunner:
    def __init__(self, ctx: RunContext, spec: PipelineSpec):
        self.ctx = ctx
        self.spec = spec

    def run(self) -> PipelineReport:
        # Checked once, up front -- including under --dry-run, since it's a cheap,
        # side-effect-free check consistent with "dry-run validates everything it
        # can for free" (see fetch step handlers' own dry-run behavior).
        toolchain.verify_installed(self.spec.toolchain.entries)

        report = PipelineReport(
            package=self.ctx.vars.package,
            version=self.ctx.vars.version,
            old_version=self.ctx.vars.old_version,
            dry_run=self.ctx.dry_run,
        )

        with tempfile.TemporaryDirectory(prefix="gorget-") as tmp_dir:
            state = self._build_initial_state(Path(tmp_dir), report)

            for stage_cls in STAGE_ORDER:
                if stage_cls is EmitStage and self.ctx.dry_run:
                    logger.debug("stage emit: skipped (dry-run)")
                    report.stages.append(
                        StageResult(name="emit", status="skipped", reason="dry-run")
                    )
                    continue
                logger.debug("stage %s: starting", getattr(stage_cls, "name", stage_cls))
                result = stage_cls().run(self.ctx, self.spec, state)
                logger.debug("stage %s: %s", result.name, result.status)
                report.stages.append(result)

        return report

    def _build_initial_state(self, work_dir: Path, report: PipelineReport) -> StageState:
        # /package is mounted read-only, so spec mutation (spec-update) always
        # happens on a writable copy under the scratch work dir, never in place.
        work_spec_path = work_dir / self.ctx.spec_path.name
        work_spec_path.write_text(self.ctx.spec_path.read_text())
        return StageState(work_dir=work_dir, spec=SpecFile(work_spec_path), report=report)
