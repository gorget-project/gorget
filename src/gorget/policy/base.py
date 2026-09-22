"""Shared types for policy checks.

Unlike Verify's handlers (one type per declared `verify:` step), Policy's three
capabilities (vendor-constraints, audit, license-compliance) all operate against
the same thing: the module workspaces retained by vendor steps. Pipeline state
records those workspaces so policy checks do not infer them from the source tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gorget.config.schema import VendorStep


@dataclass(frozen=True, kw_only=True)
class CheckResult:
    type: str
    target: str
    status: str  # "passed" | "failed" | "warning"
    reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "target": self.target,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True, kw_only=True)
class VendoredModule:
    ecosystem: str
    path: Path


def resolve_vendored_modules(step: VendorStep, source_dir: Path) -> list[VendoredModule]:
    """Resolve one vendor step's modules against the workspace it used."""
    return [
        VendoredModule(ecosystem=step.ecosystem, path=source_dir / module.path)
        for module in step.modules
    ]
