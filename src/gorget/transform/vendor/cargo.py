"""Generate Cargo vendor trees."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from gorget.config.schema import ToolchainEntry, VendorPlatform
from gorget.exceptions import GorgetTransientError
from gorget.package_manager import PackageManager
from gorget.util.subprocess_run import run


class CargoVendor:
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
        vendor_dir = module_dir / "vendor"
        # A relative path keeps Cargo's source configuration valid after extraction.
        cmd = ["cargo", "vendor", "vendor"]
        result = PackageManager(module_dir, toolchain, runner=run).run(cmd)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"cargo vendor failed in {module_dir}: {result.stderr.strip()}"
            )
        (module_dir / "vendor-config.toml").write_text(result.stdout)
        return vendor_dir

    def archive_root_files(self, module_dir: Path) -> list[Path]:
        return [module_dir / "vendor-config.toml"]
