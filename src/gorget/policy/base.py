"""Shared types for policy checks.

Unlike Verify's handlers (one type per declared `verify:` step), Policy's three
capabilities (vendor-constraints, audit, license-compliance) all operate against
the same thing: whatever got vendored during Fetch/Transform. `discover_vendored_modules`
is the one place that knowledge lives, reused by all three rather than each
re-deriving it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gorget.config.schema import PipelineSpec, VendorStep


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


def discover_vendored_modules(spec: PipelineSpec, source_dir: Path) -> list[VendoredModule]:
    """Every module a `vendor` transform actually vendored, resolved against the
    source workspace. Reuses the pipeline's typed vendor declarations rather than
    re-deriving them from the filesystem.
    """
    vendor_steps = [step for step in spec.transform.steps if isinstance(step, VendorStep)]

    modules = []
    for step in vendor_steps:
        for module in step.modules:
            modules.append(VendoredModule(ecosystem=step.ecosystem, path=source_dir / module.path))
    return modules
