from __future__ import annotations

from pathlib import Path

from gorget.exceptions import GorgetTransientError
from gorget.util.subprocess_run import run


class ComposerVendor:
    def vendor(self, module_dir: Path) -> Path:
        result = run(
            ["composer", "install", "--no-dev", "--no-scripts", "--no-interaction"],
            cwd=module_dir,
        )
        if result.returncode != 0:
            raise GorgetTransientError(
                f"composer install failed in {module_dir}: {result.stderr.strip()}"
            )
        return module_dir / "vendor"
