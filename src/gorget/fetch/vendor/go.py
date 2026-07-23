from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from gorget.config.schema import ToolchainEntry
from gorget.exceptions import GorgetTransientError
from gorget.toolchain import wrap_command
from gorget.util.subprocess_run import run


class GoVendor:
    def vendor(self, module_dir: Path, toolchain: Sequence[ToolchainEntry] = ()) -> Path:
        result = run(wrap_command(["go", "mod", "vendor"], toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"go mod vendor failed in {module_dir}: {result.stderr.strip()}"
            )
        return module_dir / "vendor"
