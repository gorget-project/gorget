"""RPM-native toolchain activation and validation.

Gorget never fetches toolchains. When a distribution provides a requested
version through distinctly named executables, Gorget temporarily places aliases
for those executables at the front of ``PATH`` for the duration of the pipeline.
It then validates the active versions before any stage runs. Tools without an
RPM-native versioned-executable convention continue to use and validate the
ambient executable.

A previous design shelled out to `mise` (https://mise.jdx.dev/) to actually
*activate* a specific version. That was rejected (see HUM-4990): mise's job is
downloading toolchain binaries directly from their own upstream release
channels at runtime, exactly the kind of untrusted-source problem Gorget
exists to eliminate for source tarballs, just one layer up. A real
multi-version mechanism must be RPM-native with zero mid-pipeline network
dependency. This module implements that mechanism for Node.js (``node-24``)
and Python (``python3.12``), whose RPMs support parallel installation.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path

from gorget.config.schema import ToolchainEntry
from gorget.exceptions import GorgetConfigError
from gorget.util.subprocess_run import run

logger = logging.getLogger("gorget.toolchain")

# name -> (version-check argv, regex whose group(1) captures the version).
_VERSION_CHECKS: dict[str, tuple[list[str], re.Pattern[str]]] = {
    "go": (["go", "version"], re.compile(r"go(\d+\.\d+(?:\.\d+)?)")),
    "node": (["node", "--version"], re.compile(r"v?(\d+\.\d+\.\d+)")),
    "npm": (["npm", "--version"], re.compile(r"(\d+\.\d+\.\d+)")),
    "cargo": (["cargo", "--version"], re.compile(r"cargo (\d+\.\d+\.\d+)")),
    "rustc": (["rustc", "--version"], re.compile(r"rustc (\d+\.\d+\.\d+)")),
    "python": (["python3", "--version"], re.compile(r"Python (\d+\.\d+\.\d+)")),
    "maven": (["mvn", "--version"], re.compile(r"Apache Maven (\d+\.\d+\.\d+)")),
    "gradle": (["gradle", "--version"], re.compile(r"Gradle (\d+\.\d+(?:\.\d+)?)")),
}
_DECLARED_VERSION = re.compile(r"\d+(?:\.\d+)*")
_RPM_BINDIR = Path("/usr/bin")


def _parse_declared_version(entry: ToolchainEntry, value: object, field: str) -> list[str]:
    if not isinstance(value, str) or _DECLARED_VERSION.fullmatch(value) is None:
        raise GorgetConfigError(
            f"Invalid {field} for toolchain {entry.name!r}: {value!r} "
            "(expected dot-separated numeric components)"
        )
    return value.split(".")


def _version_parts(entry: ToolchainEntry) -> list[str]:
    version_parts = _parse_declared_version(entry, entry.version, "version")
    if entry.minimum_version is not None:
        _parse_declared_version(entry, entry.minimum_version, "minimum-version")
    return version_parts


def _rpm_owned(path: Path) -> bool:
    try:
        result = run([str(_RPM_BINDIR / "rpm"), "-qf", str(path)])
    except FileNotFoundError:
        return False
    return result.returncode == 0


def _installed_rpm_binary(name: str) -> str | None:
    path = _RPM_BINDIR / name
    if not path.is_file() or not os.access(path, os.X_OK):
        return None
    if not _rpm_owned(path):
        logger.debug("ignoring non-RPM toolchain executable: %s", path)
        return None
    return str(path)


def _versioned_aliases(entry: ToolchainEntry) -> dict[str, str]:
    """Return PATH aliases backed by installed, distinctly named RPM binaries."""
    version_parts = _version_parts(entry)

    if entry.name == "node":
        suffix = version_parts[0]
        node = _installed_rpm_binary(f"node-{suffix}")
        if node is None:
            return {}

        targets = {"node": node}
        for alias in ("npm", "npx"):
            target = _installed_rpm_binary(f"{alias}-{suffix}")
            if target is None:
                raise GorgetConfigError(
                    f"node-{suffix} is installed but {alias}-{suffix} is missing"
                )
            targets[alias] = target
        return targets

    if entry.name == "python" and len(version_parts) >= 2:
        executable = _installed_rpm_binary(f"python{version_parts[0]}.{version_parts[1]}")
        if executable is not None:
            return {"python": executable, "python3": executable}

    return {}


@contextlib.contextmanager
def activate(entries: Sequence[ToolchainEntry]) -> Iterator[None]:
    """Activate installed RPM-native toolchain versions for one pipeline run.

    The process-wide PATH change is safe because Gorget runs pipelines
    synchronously. Child processes, including scripts that use ``env node``,
    inherit the selected toolchain. The original PATH and temporary aliases are
    restored when the pipeline finishes or fails.
    """
    original_path = os.environ.get("PATH")
    search_path = original_path if original_path is not None else os.defpath
    targets: dict[str, str] = {}

    for entry in entries:
        for alias, target in _versioned_aliases(entry).items():
            previous = targets.get(alias)
            if previous is not None and previous != target:
                raise GorgetConfigError(
                    f"Conflicting toolchain requirements select different {alias!r} "
                    f"executables: {previous!r} and {target!r}"
                )
            targets[alias] = target

    if not targets:
        yield
        return

    with tempfile.TemporaryDirectory(prefix="gorget-toolchain-") as tmp_dir:
        shim_dir = Path(tmp_dir)
        for alias, target in targets.items():
            (shim_dir / alias).symlink_to(target)
            logger.debug("toolchain alias: %s -> %s", alias, target)

        os.environ["PATH"] = f"{shim_dir}{os.pathsep}{search_path}"
        try:
            yield
        finally:
            if original_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = original_path


def _version_matches(declared: str, active: str) -> bool:
    """Component-wise prefix match: "1.22" matches "1.22.3" but not "1.223"
    or "1.2". Plain string prefixing would incorrectly match the latter two.
    """
    declared_parts = declared.split(".")
    active_parts = active.split(".")
    return declared_parts == active_parts[: len(declared_parts)]


def _version_at_least(minimum: str, active: str) -> bool:
    minimum_parts = tuple(int(part) for part in minimum.split("."))
    active_parts = tuple(int(part) for part in active.split("."))
    width = max(len(minimum_parts), len(active_parts))
    return minimum_parts + (0,) * (width - len(minimum_parts)) <= active_parts + (0,) * (
        width - len(active_parts)
    )


def verify_installed(entries: Sequence[ToolchainEntry]) -> None:
    for entry in entries:
        _version_parts(entry)
        check = _VERSION_CHECKS.get(entry.name)
        if check is None:
            raise GorgetConfigError(
                f"Unknown toolchain name: {entry.name!r} (supported: "
                f"{sorted(_VERSION_CHECKS)}). gorget only uses already-installed "
                f"toolchains and never downloads them."
            )
        cmd, pattern = check
        try:
            result = run(cmd)
        except FileNotFoundError as exc:
            raise GorgetConfigError(
                f"Required toolchain {entry.name}@{entry.version} is not available "
                f"(command not found: {cmd[0]!r})"
            ) from exc
        if result.returncode != 0:
            raise GorgetConfigError(
                f"Required toolchain {entry.name}@{entry.version} is not available "
                f"({' '.join(cmd)} failed: {(result.stderr or result.stdout).strip()})"
            )

        output = result.stdout + result.stderr
        match = pattern.search(output)
        if not match:
            raise GorgetConfigError(
                f"Could not parse a version for {entry.name!r} from `{' '.join(cmd)}` "
                f"output: {output.strip()!r}"
            )

        active_version = match.group(1)
        if not _version_matches(entry.version, active_version):
            raise GorgetConfigError(
                f"Required toolchain {entry.name}@{entry.version} does not match the "
                f"active version ({active_version}). No matching installed RPM "
                f"toolchain could be activated; gorget never downloads toolchains."
            )
        if entry.minimum_version is not None and not _version_at_least(
            entry.minimum_version, active_version
        ):
            raise GorgetConfigError(
                f"Required toolchain {entry.name}@{entry.version} needs at least "
                f"version {entry.minimum_version}, but the active version is "
                f"{active_version}."
            )


def wrap_command(cmd: list[str], entries: Sequence[ToolchainEntry]) -> list[str]:
    # Activation is pipeline-scoped so child processes also inherit it. Keep
    # this compatibility seam for handlers that already route commands through
    # it; direct command rewriting would not affect scripts using `env node`.
    return cmd
