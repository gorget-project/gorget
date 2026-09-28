"""Re-publication detection: compare current publication artifacts against the
package's already-committed `sources` file (in /package, from Fedora dist-git),
failing closed if a same-named file changed without an accepted-checksums entry.

Always runs when `/package/sources` exists, regardless of whether any
`verify:` steps are declared -- this is the core supply-chain safety net, not
an opt-in check.
"""

from __future__ import annotations

import re

from gorget.config.schema import AcceptedChecksumEntry
from gorget.context import RunContext
from gorget.exceptions import GorgetConfigError
from gorget.pipeline.state import StageState
from gorget.util.checksum import compute_digest
from gorget.verify.base import CheckResult

# Modern dist-git format (also what gorget's own Emit writes): "SHA512 (file) = digest"
_MODERN_RE = re.compile(r"^([A-Za-z0-9]+)\s*\(([^)]+)\)\s*=\s*([0-9a-fA-F]+)$")
# Legacy two-column format (implicitly md5): "<digest>  <file>"
_LEGACY_RE = re.compile(r"^([0-9a-fA-F]+)\s+\*?(.+)$")


def parse_sources_manifest(text: str) -> dict[str, tuple[str, str]]:
    """Returns {filename: (algorithm, digest)}."""
    entries: dict[str, tuple[str, str]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        modern = _MODERN_RE.match(line)
        if modern:
            algo, filename, digest = modern.groups()
            entries[filename.strip()] = (algo.lower(), digest.lower())
            continue
        legacy = _LEGACY_RE.match(line)
        if legacy:
            digest, filename = legacy.groups()
            entries[filename.strip()] = ("md5", digest.lower())
    return entries


def _suggest_accepted_checksums_block(output_name: str, checksum: str | None) -> str:
    return (
        "  - file: " + repr(output_name) + "\n"
        "    checksum: " + repr(checksum) + "\n"
        '    reason: "<why this re-publication is safe>"'
    )


def _version_change_hint(ctx: RunContext, artifact) -> str:
    if (
        artifact.version_change_eligible
        and not artifact.allow_version_change
        and ctx.vars.old_version is not None
        and ctx.vars.old_version != ctx.vars.version
    ):
        return (
            " If this stable-named artifact is intentionally regenerated from a Git ref "
            "as part of this version update, consider adding `allow-version-change: true` "
            "to that `type: git` fetch step. Do not use it for an unchanged source or "
            "for auxiliary artifacts that should remain byte-identical."
        )
    return ""


def check_republication(
    ctx: RunContext, state: StageState, accepted_entries: list[AcceptedChecksumEntry]
) -> list[CheckResult]:
    sources_path = ctx.package_dir / "sources"
    if not sources_path.is_file():
        return []

    existing = parse_sources_manifest(sources_path.read_text())
    accepted = {(entry.file, entry.checksum) for entry in accepted_entries}

    results = []
    inputs_by_name = {
        artifact.output_name: artifact for artifact in state.input_artifacts
    }
    for artifact in state.artifacts:
        if artifact.output_name not in existing:
            continue  # new file (e.g. a version bump) -- nothing to compare
        existing_algo, existing_digest = existing[artifact.output_name]
        try:
            actual_digest = compute_digest(artifact.path, existing_algo)
        except ValueError as exc:
            raise GorgetConfigError(
                f"Cannot verify {artifact.output_name!r}: unsupported checksum "
                f"algorithm {existing_algo!r} in {sources_path}"
            ) from exc

        if actual_digest.lower() == existing_digest:
            continue  # unchanged

        source = inputs_by_name.get(artifact.output_name, artifact)
        if (
            source.allow_version_change
            and ctx.vars.old_version is not None
            and ctx.vars.old_version != ctx.vars.version
        ):
            results.append(
                CheckResult(
                    type="republication",
                    target=artifact.output_name,
                    status="expected-version-change",
                    reason=(
                        f"Declared version-bound source changed from "
                        f"{ctx.vars.old_version} to {ctx.vars.version}"
                    ),
                )
            )
            continue

        if (artifact.output_name, artifact.checksum) in accepted:
            results.append(
                CheckResult(
                    type="republication",
                    target=artifact.output_name,
                    status="accepted",
                    reason="Matches an accepted-checksums entry",
                )
            )
            continue

        results.append(
            CheckResult(
                type="republication",
                target=artifact.output_name,
                status="failed",
                reason=(
                    f"{artifact.output_name} was already published with {existing_algo} "
                    f"{existing_digest}, but the current publication has {existing_algo} "
                    f"{actual_digest} instead. If this change is legitimate, add it to "
                    f"accepted-checksums:\n"
                    f"{_suggest_accepted_checksums_block(artifact.output_name, artifact.checksum)}"
                    f"{_version_change_hint(ctx, source)}"
                ),
            )
        )
    return results
