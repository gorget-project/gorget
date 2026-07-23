"""Re-publication detection: compare freshly-fetched artifacts against the
package's already-committed `sources` file (in /package, from Fedora dist-git),
failing closed if upstream silently republished a same-named file with
different content -- unless an accepted-checksums entry explicitly allows it.

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


def check_republication(
    ctx: RunContext, state: StageState, accepted_entries: list[AcceptedChecksumEntry]
) -> list[CheckResult]:
    sources_path = ctx.package_dir / "sources"
    if not sources_path.is_file():
        return []

    existing = parse_sources_manifest(sources_path.read_text())
    accepted = {(entry.file, entry.checksum) for entry in accepted_entries}

    results = []
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
                    f"{existing_digest}, but the freshly fetched copy has {existing_algo} "
                    f"{actual_digest} instead -- upstream may have silently republished "
                    f"this file. If this is a legitimate re-publication, add to "
                    f"accepted-checksums:\n"
                    f"{_suggest_accepted_checksums_block(artifact.output_name, artifact.checksum)}"
                ),
            )
        )
    return results
