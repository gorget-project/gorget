"""`EmitStage`: writes fetched artifacts, a dist-git `sources` manifest, and
`report.json` to `/output`.

Zero fetched artifacts is non-fatal here (empty manifest, still emits) --
enforcing "a package must produce sources" belongs to the future Policy stage.
"""

from __future__ import annotations

import shutil
from typing import ClassVar

from gorget.config.schema import PipelineSpec
from gorget.constants import CHECKSUM_ALGO, SOURCES_MANIFEST_FILENAME
from gorget.context import RunContext
from gorget.exceptions import GorgetTransientError
from gorget.pipeline.result import StageResult, write_report_json
from gorget.pipeline.state import StageState
from gorget.util.checksum import format_sources_manifest


class EmitStage:
    name: ClassVar[str] = "emit"

    def run(self, ctx: RunContext, spec: PipelineSpec, state: StageState) -> StageResult:
        fetched = [artifact for artifact in state.artifacts if artifact.checksum is not None]

        own_result = StageResult(name=self.name, status="success")
        # state.report.stages doesn't include our own result yet (the runner
        # appends it after this method returns) -- include it in the on-disk
        # report without mutating state.report, so the runner's append doesn't
        # end up duplicating it.
        report_dict = state.report.to_dict()
        report_dict["stages"].append(own_result.to_dict())

        try:
            ctx.output_dir.mkdir(parents=True, exist_ok=True)
            for artifact in fetched:
                shutil.copyfile(artifact.path, ctx.output_dir / artifact.output_name)

            manifest_entries = [
                (a.output_name, a.checksum) for a in fetched if a.checksum is not None
            ]
            manifest_text = format_sources_manifest(manifest_entries, CHECKSUM_ALGO)
            (ctx.output_dir / SOURCES_MANIFEST_FILENAME).write_text(manifest_text)

            write_report_json(ctx.output_dir, report_dict)
        except OSError as exc:
            raise GorgetTransientError(
                f"Failed to write output to {ctx.output_dir}: {exc}"
            ) from exc

        return own_result
