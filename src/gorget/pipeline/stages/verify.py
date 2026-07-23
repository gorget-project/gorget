"""`VerifyStage`: validates integrity/authenticity of what Fetch/Transform
produced. Re-publication detection always runs when `/package/sources`
exists -- no `verify:` step opt-in needed, since it's the core supply-chain
safety net, not an optional check. Explicitly declared `verify:` steps
(`gpg-signature`, `checksum-file`) run in addition. All failures are
aggregated into a single `GorgetPolicyViolation`, so one run surfaces
everything wrong at once rather than stopping at the first failure.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from gorget.config.schema import ChecksumFileStep, GpgSignatureStep, PipelineSpec
from gorget.context import RunContext
from gorget.exceptions import GorgetPolicyViolation
from gorget.pipeline.result import StageResult
from gorget.pipeline.state import StageState
from gorget.verify.base import CheckResult
from gorget.verify.checksum_file import ChecksumFileHandler
from gorget.verify.gpg_signature import GpgSignatureHandler
from gorget.verify.republication import check_republication

# See `pipeline/stages/fetch.py` for why this dict is typed loosely rather
# than fighting Protocol contravariance for a dynamic dispatch table.
_HANDLERS: dict[type, Any] = {
    GpgSignatureStep: GpgSignatureHandler(),
    ChecksumFileStep: ChecksumFileHandler(),
}

logger = logging.getLogger("gorget.pipeline")


class VerifyStage:
    name: ClassVar[str] = "verify"

    def run(self, ctx: RunContext, spec: PipelineSpec, state: StageState) -> StageResult:
        if ctx.dry_run:
            # Nothing was actually fetched under dry-run (fetch handlers skip
            # real downloads, leaving placeholder artifacts with no bytes on
            # disk), so there's nothing real to verify.
            return StageResult(name=self.name, status="skipped", reason="dry-run")

        results = check_republication(ctx, state, spec.accepted_checksums.entries)
        for step in spec.verify.steps:
            handler = _HANDLERS[type(step)]
            logger.debug("verify step: %s", step)
            results.append(handler.run(step, ctx, state))

        has_sources_file = (ctx.package_dir / "sources").is_file()
        if not results and not has_sources_file:
            logger.warning("No verification configured for %s", ctx.vars.package)
            return StageResult(
                name=self.name, status="skipped", reason="no verification configured"
            )

        failures = [result for result in results if result.status == "failed"]
        if failures:
            raise GorgetPolicyViolation(_format_failures(failures))

        return StageResult(
            name=self.name, status="success", details=[result.to_dict() for result in results]
        )


def _format_failures(failures: list[CheckResult]) -> str:
    lines = [f"Verification failed ({len(failures)} check(s)):"]
    for failure in failures:
        lines.append(f"- [{failure.type}] {failure.target}: {failure.reason}")
    return "\n".join(lines)
