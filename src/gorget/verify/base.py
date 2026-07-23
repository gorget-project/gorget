"""Shared types for verify step handlers.

Unlike Fetch/Transform, there's no dedicated Context class here: handlers take
`(step, ctx: RunContext, state: StageState)` directly, since `RunContext`
already carries everything a verify step needs (`gpg_keys_dir`, `package_dir`)
and there's no dry-run branching inside handlers -- `VerifyStage` skips
entirely under `--dry-run`, before any handler runs, since the files being
verified don't exist yet under dry-run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from gorget.config.schema import VerifyStep
from gorget.context import RunContext
from gorget.pipeline.state import StageState


@dataclass(frozen=True, kw_only=True)
class CheckResult:
    type: str
    target: str
    status: str  # "passed" | "failed" | "accepted"
    reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "target": self.target,
            "status": self.status,
            "reason": self.reason,
        }


class VerifyStepHandler(Protocol):
    def run(self, step: VerifyStep, ctx: RunContext, state: StageState) -> CheckResult: ...
