"""`spec-update` fetch step: macro substitution and release reset, applied to the
spec's work-dir copy before any `spec-source` step resolves Source URLs.
"""

from __future__ import annotations

from gorget.config.schema import SpecUpdateStep
from gorget.fetch.base import FetchContext, FetchedArtifact


class SpecUpdateHandler:
    def run(self, step: SpecUpdateStep, ctx: FetchContext) -> list[FetchedArtifact]:
        if step.set_version:
            ctx.spec.set_version(ctx.vars.version)
        if step.reset_release is not None:
            ctx.spec.reset_release(step.reset_release)
        for sub in step.substitutions:
            ctx.spec.apply_substitution(sub, ctx.vars)
        return []
