"""Shared types for policy checks.

Unlike Verify's handlers (one type per declared `verify:` step), Policy's three
capabilities (vendor-constraints, audit, license-compliance) all operate against
the same thing: the module workspaces retained by vendor steps. Pipeline state
records those workspaces so policy checks do not infer them from the source tree.
"""

from __future__ import annotations

from dataclasses import dataclass

from gorget.fetch.vendor.base import VendoredModule as VendoredModule


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
