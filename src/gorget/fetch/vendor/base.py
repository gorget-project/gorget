"""Shared interface for per-ecosystem vendor archive generation."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class VendorEcosystem(Protocol):
    def vendor(self, module_dir: Path) -> Path:
        """Run the ecosystem's vendor command against `module_dir` and return the
        path to the produced vendor directory.
        """
        ...
