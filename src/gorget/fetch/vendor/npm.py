from __future__ import annotations

from pathlib import Path

from gorget.exceptions import GorgetTransientError
from gorget.util.subprocess_run import run


class NpmVendor:
    def vendor(self, module_dir: Path) -> Path:
        result = run(
            ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=module_dir
        )
        if result.returncode != 0:
            raise GorgetTransientError(
                f"npm install failed in {module_dir}: {result.stderr.strip()}"
            )
        return module_dir / "node_modules"
