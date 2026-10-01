"""Generate Composer vendor trees."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from gorget.config.schema import ToolchainEntry, VendorPlatform
from gorget.exceptions import GorgetTransientError
from gorget.package_manager import PackageManager
from gorget.util.subprocess_run import run


class ComposerVendor:
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
        # --optimize-autoloader dumps a flattened classmap covering the root
        # package's own PSR-4 classes as well as vendored ones (composer's
        # own documented recommendation for production/packaged installs).
        # Without it, autoload_classmap.php/autoload_static.php only cover
        # classmap-declared and vendor autoload rules, silently diverging
        # from what a real install would produce.
        cmd = [
            "composer", "install", "--no-dev", "--no-scripts", "--no-interaction",
            "--optimize-autoloader",
        ]
        result = PackageManager(module_dir, toolchain, runner=run).run(cmd)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"composer install failed in {module_dir}: {result.stderr.strip()}"
            )
        return module_dir / "vendor"

    def archive_root_files(self, module_dir: Path) -> list[Path]:
        return []
