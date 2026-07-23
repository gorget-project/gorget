"""`checksum-file` verify step: compare a fetched artifact's digest against an
entry in a published checksums-listing file (e.g. SHASUMS256.txt).
"""

from __future__ import annotations

import re

from gorget.config.schema import ChecksumFileStep
from gorget.context import RunContext
from gorget.exceptions import GorgetConfigError
from gorget.pipeline.state import StageState
from gorget.util.checksum import compute_digest
from gorget.verify.base import CheckResult

# Standard sha256sum/sha512sum-style output: "<hex digest>  <filename>", with
# an optional "*" marker for binary mode.
_ENTRY_RE = re.compile(r"^([0-9a-fA-F]+)\s+\*?(.+)$")


def _find_checksum_entry(text: str, filename: str) -> str | None:
    for line in text.splitlines():
        match = _ENTRY_RE.match(line.strip())
        if match and match.group(2).strip() == filename:
            return match.group(1).lower()
    return None


class ChecksumFileHandler:
    def run(self, step: ChecksumFileStep, ctx: RunContext, state: StageState) -> CheckResult:
        target = state.find_artifact(step.target)
        checksums_artifact = state.find_artifact(step.checksums_file)

        expected = _find_checksum_entry(checksums_artifact.path.read_text(), target.output_name)
        if expected is None:
            raise GorgetConfigError(
                f"No checksum entry for {target.output_name!r} found in "
                f"{step.checksums_file!r}"
            )

        actual = compute_digest(target.path, step.algorithm)
        if actual.lower() != expected:
            return CheckResult(
                type="checksum-file",
                target=step.target,
                status="failed",
                reason=f"expected {step.algorithm} {expected}, got {actual}",
            )
        return CheckResult(type="checksum-file", target=step.target, status="passed")
