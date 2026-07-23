"""`run` transform step: escape hatch for an arbitrary declared command, with
declared output paths collected as new artifacts afterward.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from gorget.config.schema import RunStep
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.fetch.base import build_artifact
from gorget.pipeline.state import StageState
from gorget.toolchain import wrap_command
from gorget.transform.base import TransformContext, ensure_source_dir
from gorget.util.archive import repack_tar_gz
from gorget.util.subprocess_run import run


class RunHandler:
    def run(self, step: RunStep, ctx: TransformContext, state: StageState) -> None:
        # Unlike build-ui/vendor (one fixed, known-ahead-of-time archive name), a
        # `run:` step's declared outputs could each be a file or a directory --
        # which one isn't knowable without actually running the command. So,
        # unlike those steps, dry-run here produces no placeholder artifacts at
        # all rather than guessing.
        if ctx.dry_run:
            return

        source_dir = ensure_source_dir(ctx, state)
        cwd = source_dir / step.path
        result = run(wrap_command(step.command, ctx.toolchain), cwd=cwd)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"run step ({' '.join(step.command)}) failed in {cwd}: {result.stderr.strip()}"
            )

        for output in step.outputs:
            output_path = cwd / output
            if not output_path.exists():
                raise GorgetConfigError(f"Declared run: output not found: {output_path}")

            name = Path(output).name
            if output_path.is_dir():
                archive_name = f"{name}.tar.gz"
                dest = ctx.work_dir / archive_name
                repack_tar_gz(output_path, dest)
            else:
                archive_name = name
                dest = ctx.work_dir / archive_name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(output_path, dest)

            description = f"run:{' '.join(step.command)}"
            state.artifacts.append(build_artifact(dest, archive_name, description, ctx.dry_run))
