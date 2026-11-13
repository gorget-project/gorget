"""Apply dependency updates through the source workspace transaction."""

import json
from pathlib import Path

from gorget.config.schema import VendorBumpStep
from gorget.dependencies.update import update_dependencies, update_source_files
from gorget.exceptions import GorgetConfigError
from gorget.pipeline.state import StageState
from gorget.pnpm import resolve_pnpm_version
from gorget.transform.base import TransformContext, ensure_source_dir


class VendorBumpHandler:
    def run(self, step: VendorBumpStep, ctx: TransformContext, state: StageState) -> None:
        if ctx.dry_run:
            return
        ensure_source_dir(ctx, state)
        assert state.source.path is not None
        paths = [
            Path(module.path) / filename
            for module in step.modules
            for filename in update_source_files(
                step.ecosystem, state.source.path / module.path,
            )
        ]
        with state.source.edit_metadata(paths) as tree:
            for module in step.modules:
                if step.package_manager_version is not None:
                    if step.ecosystem != "pnpm":
                        raise GorgetConfigError(
                            "package-manager-version is only supported for pnpm"
                        )
                    manifest_path = tree / module.path / "package.json"
                    manifest = json.loads(manifest_path.read_text())
                    version = resolve_pnpm_version(
                        manifest, manifest_path, tree / module.path, ctx.toolchain,
                        fallback=step.package_manager_version,
                    )
                    manifest["packageManager"] = f"pnpm@{version}"
                    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
                update_dependencies(step.ecosystem, tree / module.path, step.pins, ctx.toolchain)
