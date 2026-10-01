"""Apply dependency updates through the source workspace transaction."""

from pathlib import Path

from gorget.config.schema import VendorBumpStep
from gorget.dependencies.update import update_dependencies, update_source_files
from gorget.pipeline.state import StageState
from gorget.transform.base import TransformContext, ensure_source_dir


class VendorBumpHandler:
    def run(self, step: VendorBumpStep, ctx: TransformContext, state: StageState) -> None:
        if ctx.dry_run:
            return
        ensure_source_dir(ctx, state)
        paths = [
            Path(module.path) / filename
            for module in step.modules
            for filename in update_source_files(step.ecosystem)
        ]
        with state.source.edit_metadata(paths) as tree:
            for module in step.modules:
                update_dependencies(step.ecosystem, tree / module.path, step.pins, ctx.toolchain)
