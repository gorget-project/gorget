"""Generate dependency vendor archives for supported ecosystems.

Reused by both the Fetch stage's `vendor` step and the Transform stage's `vendor`
step (see `fetch/vendor/base.py`'s `VendorRunContext` for why this isn't typed
against the concrete `FetchContext`).
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from gorget.config.schema import ToolchainEntry, VendorPlatform, VendorStep
from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import FetchedArtifact, build_artifact
from gorget.fetch.vendor.base import VendorEcosystem, VendorRunContext
from gorget.fetch.vendor.cargo import CargoVendor
from gorget.fetch.vendor.combine import combine_vendor_archives
from gorget.fetch.vendor.composer import ComposerVendor
from gorget.fetch.vendor.go import GoVendor
from gorget.fetch.vendor.maven import MavenVendor
from gorget.fetch.vendor.npm import NpmVendor
from gorget.fetch.vendor.pnpm import PnpmVendor
from gorget.fetch.vendor.yarn import YarnVendor
from gorget.util.git import commit_timestamp

_ECOSYSTEMS: dict[str, VendorEcosystem] = {
    "go": GoVendor(),
    "npm": NpmVendor(),
    "pnpm": PnpmVendor(),
    "yarn": YarnVendor(),
    "cargo": CargoVendor(),
    "composer": ComposerVendor(),
    "maven": MavenVendor(),
}


class VendorHandler:
    def run(self, step: VendorStep, ctx: VendorRunContext) -> list[FetchedArtifact]:
        ecosystem = _ECOSYSTEMS[step.ecosystem]
        archive_name = step.archive_name or f"{ctx.vars.package}-vendor.tar.gz"
        archive_path = ctx.work_dir / archive_name

        if not ctx.dry_run:
            if ctx.source_dir is None:
                raise GorgetConfigError(
                    "A 'vendor' step requires a preceding 'git' step in the same "
                    "pipeline to establish a source checkout to vendor against"
                )
            source_dir = ctx.source_dir
            vendor_source_dir = source_dir
            if step.sync_go_modules:
                if step.ecosystem != "go":
                    raise GorgetConfigError(
                        "sync-go-modules is only supported for ecosystem: go"
                    )
                ctx.work_dir.mkdir(parents=True, exist_ok=True)
                vendor_source_dir = Path(
                    tempfile.mkdtemp(prefix="_vendor_source-", dir=ctx.work_dir)
                ) / "source"
                shutil.copytree(
                    source_dir,
                    vendor_source_dir,
                    symlinks=True,
                    ignore=shutil.ignore_patterns(".git"),
                )
            module_outputs = [
                (
                    module,
                    self._vendor_module(
                        ecosystem,
                        vendor_source_dir / module.path,
                        ctx.toolchain,
                        ctx.package_dir,
                        module.use_workspace,
                        step.platforms or (),
                        sync_go_modules=step.sync_go_modules,
                    ),
                )
                for module in step.modules
            ]
            if step.sync_go_modules:
                self._sync_go_module_files(source_dir, vendor_source_dir, step)
            mtime = commit_timestamp(source_dir)
            # Only the single-unnamed-module ("bare vendor/") case needs
            # root_files -- combine_vendor_archives ignores them otherwise
            # anyway, but there's nothing to gain from an archive_root_files
            # filesystem check that's guaranteed to be discarded.
            root_files = (
                ecosystem.archive_root_files(module_outputs[0][1].parent)
                if len(module_outputs) == 1 and module_outputs[0][0].name is None
                else None
            )
            combine_vendor_archives(
                module_outputs, archive_path, mtime=mtime, root_files=root_files
            )

        return [build_artifact(archive_path, archive_name, f"vendor:{step.ecosystem}", ctx.dry_run)]

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
    ) -> Path:
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
