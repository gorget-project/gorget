"""`build-ui` transform step: build JavaScript/TypeScript UI assets from source."""

from __future__ import annotations

from gorget.config.schema import BuildUiStep
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.fetch.base import build_artifact
from gorget.pipeline.state import StageState
from gorget.toolchain import wrap_command
from gorget.transform.base import TransformContext, ensure_source_dir
from gorget.util.archive import repack_tar_gz
from gorget.util.subprocess_run import run


class BuildUiHandler:
    def run(self, step: BuildUiStep, ctx: TransformContext, state: StageState) -> None:
        archive_name = step.archive_name or f"{ctx.vars.package}-ui-assets.tar.gz"
        archive_path = ctx.work_dir / archive_name

        if not ctx.dry_run:
            source_dir = ensure_source_dir(ctx, state)
            project_dir = source_dir / step.path
            cmd = [step.ecosystem, "run", step.script]
            result = run(wrap_command(cmd, ctx.toolchain), cwd=project_dir)
            if result.returncode != 0:
                raise GorgetTransientError(
                    f"{step.ecosystem} run {step.script} failed in {project_dir}: "
                    f"{result.stderr.strip()}"
                )
            output_dir = project_dir / step.output_dir
            if not output_dir.is_dir():
                raise GorgetConfigError(
                    f"build-ui output directory not found after the build: {output_dir}"
                )
            repack_tar_gz(output_dir, archive_path)

        state.artifacts.append(
            build_artifact(archive_path, archive_name, f"build-ui:{step.ecosystem}", ctx.dry_run)
        )
