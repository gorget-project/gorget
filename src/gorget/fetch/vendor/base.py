"""Shared interfaces for per-ecosystem vendor archive generation.

`VendorHandler`/`VendorEcosystem` are typed against `VendorRunContext` (a Protocol)
rather than the concrete `FetchContext` so the exact same vendor step/ecosystem code
can run from either the Fetch stage's `vendor` step or the Transform stage's `vendor`
step (reused there to let `vendor-pin` edit lockfiles before vendoring runs).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from gorget.config.schema import ToolchainEntry
from gorget.config.substitution import SubstitutionVars


class VendorRunContext(Protocol):
    work_dir: Path
    vars: SubstitutionVars
    dry_run: bool
    source_dir: Path | None
    toolchain: list[ToolchainEntry]


class VendorEcosystem(Protocol):
    def vendor(self, module_dir: Path, toolchain: Sequence[ToolchainEntry] = ()) -> Path:
        """Run the ecosystem's vendor command against `module_dir` and return the
        path to the produced vendor directory.
        """
        ...
