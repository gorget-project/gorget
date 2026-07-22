from __future__ import annotations

from pathlib import Path

from gorget.exceptions import GorgetTransientError
from gorget.util.subprocess_run import run


class CargoVendor:
    def vendor(self, module_dir: Path) -> Path:
        vendor_dir = module_dir / "vendor"
        result = run(["cargo", "vendor", str(vendor_dir)], cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"cargo vendor failed in {module_dir}: {result.stderr.strip()}"
            )
        return vendor_dir
