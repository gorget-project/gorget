"""Generate dependency vendor archives from the source workspace."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from gorget.config.schema import ToolchainEntry, VendorModule, VendorPlatform, VendorStep
from gorget.exceptions import GorgetConfigError
from gorget.pipeline.artifact import build_derived_artifact, derived_artifact_path
from gorget.transform.vendor.base import (
    VendorEcosystem,
    VendorResult,
    VendorRunContext,
    resolve_vendored_modules,
)
from gorget.transform.vendor.cargo import CargoVendor
from gorget.transform.vendor.combine import combine_vendor_archives
from gorget.transform.vendor.composer import ComposerVendor
from gorget.transform.vendor.go import GoVendor
from gorget.transform.vendor.gradle import GradleVendor
from gorget.transform.vendor.maven import MavenVendor
from gorget.transform.vendor.npm import NpmVendor
from gorget.transform.vendor.pnpm import PnpmVendor
from gorget.transform.vendor.yarn import YarnVendor
from gorget.util.git import commit_timestamp

_ECOSYSTEMS: dict[str, VendorEcosystem] = {
    "go": GoVendor(),
    "npm": NpmVendor(),
    "pnpm": PnpmVendor(),
    "yarn": YarnVendor(),
    "cargo": CargoVendor(),
    "composer": ComposerVendor(),
    "maven": MavenVendor(),
    "gradle": GradleVendor(),
}


class VendorHandler:
    def run(self, step: VendorStep, ctx: VendorRunContext) -> VendorResult:
        ecosystem = _ECOSYSTEMS[step.ecosystem]
        archive_name = step.archive_name or f"{ctx.vars.package}-vendor.tar.gz"
        archive_path = derived_artifact_path(ctx.work_dir, "vendor", archive_name)

        use_offline_cache = (
            step.ecosystem == "pnpm"
            if step.offline_cache is None
            else step.offline_cache
        )
        if use_offline_cache:
            if step.ecosystem != "pnpm":
                raise GorgetConfigError("offline-cache is only supported for ecosystem: pnpm")
            if step.sync_go_modules:
                raise GorgetConfigError("offline-cache cannot be combined with sync-go-modules")
            if len(step.modules) != 1:
                raise GorgetConfigError(
                    "pnpm offline-cache requires exactly one module; set "
                    "offline-cache: false for store-only multi-module vendoring"
                )
            if not ctx.dry_run:
                if ctx.source_dir is None:
                    raise GorgetConfigError(
                        "A pnpm offline-cache step requires a preceding 'git' step"
                    )
                module_dir = ctx.source_dir / step.modules[0].path
                cast(PnpmVendor, ecosystem).offline_cache(
                    module_dir,
                    archive_path,
                    ctx.toolchain,
                    step.platforms or (),
                    step.metadata_packages,
                )
            artifact = build_derived_artifact(
                archive_path, archive_name, "vendor:pnpm offline-cache", ctx.dry_run
            )
            modules = (
                resolve_vendored_modules(step, ctx.source_dir)
                if not ctx.dry_run and ctx.source_dir is not None
                else ()
            )
            return VendorResult(artifacts=(artifact,), modules=modules)
        if step.metadata_packages:
            raise GorgetConfigError(
                "metadata-packages requires pnpm offline-cache; "
                "remove it or set offline-cache: true"
            )

        vendor_source_dir: Path | None = None

        if not ctx.dry_run:
            if ctx.source_dir is None:
                raise GorgetConfigError(
                    "A 'vendor' step requires a preceding 'git' step in the same "
                    "pipeline to establish a source checkout to vendor against"
                )
            if step.sync_go_modules and step.ecosystem != "go":
                raise GorgetConfigError(
                    "sync-go-modules is only supported for ecosystem: go"
                )

            source_dir = ctx.source_dir
            ctx.work_dir.mkdir(parents=True, exist_ok=True)
            temporary_source_root = Path(
                tempfile.mkdtemp(prefix="_vendor_source-", dir=ctx.work_dir)
            )
            vendor_source_dir = temporary_source_root / "source"
            shutil.copytree(
                source_dir,
                vendor_source_dir,
                symlinks=True,
                ignore=shutil.ignore_patterns(".git"),
            )
            module_outputs: list[tuple[VendorModule, Path]] = []
            cleanup = getattr(type(ecosystem), "cleanup", None)
            try:
                for module in step.modules:
                    module_dir = vendor_source_dir / module.path
                    output = self._vendor_module(
                        ecosystem,
                        module_dir,
                        ctx.toolchain,
                        ctx.package_dir,
                        module.use_workspace,
                        step.platforms or (),
                        sync_go_modules=step.sync_go_modules,
                        gradle_task=step.task if step.ecosystem == "gradle" else None,
                    )
                    module_outputs.append((module, output))
                if step.sync_go_modules:
                    self._sync_go_module_files(source_dir, vendor_source_dir, step)
                mtime = commit_timestamp(source_dir)
                root_files = (
                    ecosystem.archive_root_files(module_outputs[0][1].parent)
                    if len(module_outputs) == 1 and module_outputs[0][0].name is None
                    else None
                )
                combine_vendor_archives(
                    module_outputs, archive_path, mtime=mtime, root_files=root_files
                )
            except BaseException:
                shutil.rmtree(temporary_source_root, ignore_errors=True)
                raise
            finally:
                for _module, output in module_outputs:
                    if cleanup is not None:
                        cleanup(ecosystem, output)

        artifact = build_derived_artifact(
            archive_path, archive_name, f"vendor:{step.ecosystem}", ctx.dry_run
        )
        modules = (
            resolve_vendored_modules(step, vendor_source_dir)
            if vendor_source_dir is not None
            else ()
        )
        return VendorResult(artifacts=(artifact,), modules=modules)

    @staticmethod
    def _vendor_module(
        ecosystem: VendorEcosystem,
        module_dir: Path,
        toolchain: Sequence[ToolchainEntry],
        package_dir: Path,
        use_workspace: bool,
        platforms: Sequence[VendorPlatform],
        *,
        sync_go_modules: bool,
        gradle_task: str | None,
    ) -> Path:
        if gradle_task is not None:
            return ecosystem.vendor(
                module_dir,
                toolchain,
                package_dir,
                use_workspace,
                platforms,
                task=gradle_task,
            )
        if sync_go_modules:
            go_vendor = cast(GoVendor, ecosystem)
            return go_vendor.vendor(
                module_dir,
                toolchain,
                package_dir,
                use_workspace,
                platforms,
                sync_go_modules=True,
            )
        return ecosystem.vendor(module_dir, toolchain, package_dir, use_workspace, platforms)

    @staticmethod
    def _sync_go_module_files(
        source_dir: Path, vendor_source_dir: Path, step: VendorStep
    ) -> None:
        """Copy module metadata, but never the generated vendor tree, to Source0."""
        for module in step.modules:
            source_module = source_dir / module.path
            vendor_module = vendor_source_dir / module.path
            for filename in ("go.mod", "go.sum", "go.work", "go.work.sum"):
                generated = vendor_module / filename
                destination = source_module / filename
                if generated.is_file():
                    shutil.copyfile(generated, destination)
                elif destination.is_file():
                    destination.unlink()
