"""Apply dependency updates through the source workspace transaction."""

from pathlib import Path

from gorget.config.schema import VendorBumpStep
from gorget.dependencies.npm_bundle import update_npm_bundle
from gorget.dependencies.update import update_dependencies, update_source_files
from gorget.exceptions import GorgetConfigError
from gorget.pipeline.state import StageState
from gorget.transform.base import TransformContext, ensure_source_dir


class VendorBumpHandler:
    def run(self, step: VendorBumpStep, ctx: TransformContext, state: StageState) -> None:
        if step.bundled and step.ecosystem != "npm":
            raise GorgetConfigError("vendor-bump bundled is only supported for npm")
        if ctx.dry_run:
            return
        ensure_source_dir(ctx, state)
        if step.bundled:
            with state.source.edit_tree(ctx.work_dir) as tree:
                for module in step.modules:
                    module_dir = tree / module.path
                    if not module_dir.resolve().is_relative_to(tree.resolve()):
                        raise GorgetConfigError("Bundled module path escapes the source tree")
                    update_npm_bundle(module_dir, step.pins, ctx.toolchain)
            return
        paths = [
            Path(module.path) / filename
            for module in step.modules
            for filename in update_source_files(step.ecosystem)
        ]
        with state.source.edit_metadata(paths) as tree:
            for module in step.modules:
                update_dependencies(step.ecosystem, tree / module.path, step.pins, ctx.toolchain)
