"""Resolve and install the project-selected pnpm CLI for bumps and offline caches."""

import re
from collections.abc import Callable, Sequence
from pathlib import Path

from gorget.config.schema import ToolchainEntry
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.package_manager import PackageManager
from gorget.util.subprocess_run import run

_PACKAGE_MANAGER_RE = re.compile(r"^pnpm@(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)(?:\+.*)?$")
_PNPM_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def resolve_pnpm_version(
    manifest: dict[str, object],
    manifest_path: Path,
    module_dir: Path,
    toolchain: Sequence[ToolchainEntry],
    *, runner: Callable = run, fallback: str | None = None,
) -> str:
    if fallback is not None and not _PNPM_VERSION_RE.fullmatch(fallback):
        raise GorgetConfigError(f"Expected an exact pnpm fallback version, got {fallback!r}")
    declared_manager = manifest.get("packageManager")
    if declared_manager is not None:
        match = _PACKAGE_MANAGER_RE.fullmatch(str(declared_manager))
        if not match:
            raise GorgetConfigError(
                f"Invalid pnpm packageManager declaration in {manifest_path}: {declared_manager!r}"
            )
        return match.group("version")

    dev_engines = manifest.get("devEngines")
    dev_manager = dev_engines.get("packageManager") if isinstance(dev_engines, dict) else None
    dev_version = (
        dev_manager.get("version")
        if isinstance(dev_manager, dict) and dev_manager.get("name") == "pnpm"
        else None
    )
    if isinstance(dev_version, str) and _PNPM_VERSION_RE.fullmatch(dev_version):
        return dev_version

    if fallback is not None:
        return fallback
    result = PackageManager(module_dir, toolchain, runner=runner).run(["pnpm", "--version"])
    version = result.stdout.strip()
    if result.returncode != 0 or not _PNPM_VERSION_RE.fullmatch(version):
        raise GorgetConfigError(
            f"Could not determine pnpm version for {manifest_path}: "
            f"{(result.stdout + result.stderr).strip()}"
        )
    return version


def install_pnpm_cli(
    pnpm_root: Path, scratch_module: Path, pnpm_version: str,
    toolchain: Sequence[ToolchainEntry], *, runner: Callable = run,
) -> list[str]:
    major = int(pnpm_version.split(".", 1)[0])
    pnpm_root.mkdir()
    install_packages = [f"pnpm@{pnpm_version}"]
    if major >= 12:
        # npm filters pnpm's optional native executable to the host
        # architecture. Bundle both default RPM build architectures.
        install_packages += [
            f"@pnpm/exe.linux-x64@{pnpm_version}",
            f"@pnpm/exe.linux-arm64@{pnpm_version}",
        ]
    npm_result = PackageManager(scratch_module, toolchain, runner=runner).run(
        [
            "npm",
            "install",
            "--prefix",
            str(pnpm_root),
            "--ignore-scripts",
            "--force",
            *install_packages,
        ],
        env={"CI": "true"},
    )
    if npm_result.returncode != 0:
        raise GorgetTransientError(
            f"Could not install pnpm@{pnpm_version}: {npm_result.stderr.strip()}"
        )

    pnpm_mjs = pnpm_root / "node_modules/pnpm/bin/pnpm.mjs"
    pnpm_wrapper = pnpm_root / "node_modules/.bin/pnpm"
    if pnpm_mjs.is_file():
        # The pnpm package's install hook normally repairs this npm
        # shim. Install pnpm with scripts disabled, then create a
        # working shim for project scripts that invoke pnpm again.
        pnpm_wrapper.unlink(missing_ok=True)
        pnpm_wrapper.write_text(
            '#!/bin/sh\nexec node "$(dirname "$0")/../pnpm/bin/pnpm.mjs" "$@"\n'
        )
        pnpm_wrapper.chmod(0o755)
        pnpm_command = ["node", str(pnpm_mjs)]
    elif pnpm_wrapper.is_file():
        pnpm_command = [str(pnpm_wrapper)]
    else:
        raise GorgetConfigError(f"pnpm entry point not found: {pnpm_mjs} or {pnpm_wrapper}")

    version_result = PackageManager(None, toolchain, runner=runner).run(
        [*pnpm_command, "--version"]
    )
    active_version = version_result.stdout.strip().removeprefix("v")
    if version_result.returncode != 0 or active_version != pnpm_version:
        raise GorgetConfigError(
            f"Bundled pnpm version does not match {pnpm_version}: "
            f"{(version_result.stdout + version_result.stderr).strip()}"
        )

    return pnpm_command
