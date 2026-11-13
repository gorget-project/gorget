"""Generate a project-local Maven dependency repository."""

from __future__ import annotations

import shutil
import tempfile
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

        # Build goals can audit every source file (e.g. Apache RAT). Keep the
        # dependency repository outside that tree so it is not audited as source.
        vendor_dir = (module_dir / "vendor" if task == "build" else
                      Path(tempfile.mkdtemp(prefix="gorget-maven-repository-")))
        goal = "dependency:go-offline" if task == "build" else task
        cmd = ["mvn", goal, f"-Dmaven.repo.local={vendor_dir}"]
        if task == "build":
            cmd.append("-DskipTests")
        result = PackageManager(module_dir, toolchain, runner=run).run(cmd)
        if result.returncode != 0:
            self.cleanup(vendor_dir)
            raise GorgetTransientError(
                f"mvn {goal} failed in {module_dir}: {result.stderr.strip()}"
            )
        for filename in ("*.lastUpdated", "_remote.repositories", "resolver-status.properties"):
            for bookkeeping in vendor_dir.rglob(filename):
                bookkeeping.unlink()
        return vendor_dir

    def cleanup(self, vendor_dir: Path) -> None:
        if vendor_dir.name.startswith("gorget-maven-repository-"):
            shutil.rmtree(vendor_dir, ignore_errors=True)

    def archive_root_files(self, module_dir: Path) -> list[Path]:
        return []
