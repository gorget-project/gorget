"""Generate a project-local Maven dependency repository."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from gorget.config.schema import ToolchainEntry, VendorPlatform
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.package_manager import PackageManager
from gorget.util.subprocess_run import run


class MavenVendor:
    def source_files(self, *, sync_go_modules: bool = False) -> tuple[str, ...]:
        return ()

    def vendor(
        self,
        module_dir: Path,
        toolchain: Sequence[ToolchainEntry] = (),
        package_dir: Path | None = None,
        use_workspace: bool = True,
        platforms: Sequence[VendorPlatform] = (),
        task: str = "build",
    ) -> Path:
        if not (module_dir / "pom.xml").is_file():
            raise GorgetConfigError(f"maven vendor: no pom.xml found in {module_dir}")

        vendor_dir = module_dir / "vendor"
        cmd = [
            "mvn",
            "dependency:go-offline",
            f"-Dmaven.repo.local={vendor_dir}",
            "-DskipTests",
        ]
        result = PackageManager(module_dir, toolchain, runner=run).run(cmd)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"mvn dependency:go-offline failed in {module_dir}: {result.stderr.strip()}"
            )
        return vendor_dir

    def archive_root_files(self, module_dir: Path) -> list[Path]:
        return []
