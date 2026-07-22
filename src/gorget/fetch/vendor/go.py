from __future__ import annotations

from pathlib import Path

from gorget.exceptions import GorgetTransientError
from gorget.util.subprocess_run import run


class GoVendor:
    def vendor(self, module_dir: Path) -> Path:
        result = run(["go", "mod", "vendor"], cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"go mod vendor failed in {module_dir}: {result.stderr.strip()}"
            )
        return module_dir / "vendor"
