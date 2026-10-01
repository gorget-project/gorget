"""Validate every resolved dependency copy against its required version."""

from __future__ import annotations

import re
from pathlib import Path

from gorget.config.schema import VendorConstraintEntry
from gorget.dependencies import read_inventory
from gorget.exceptions import GorgetConfigError
from gorget.policy.base import CheckResult, VendoredModule
from gorget.util.subprocess_run import run


def _resolve_version(ecosystem: str, module_dir: Path, package: str) -> str | None:
    copies = read_inventory(ecosystem, module_dir, [package], runner=run).find(package)
    return min(
        (copy.version for copy in copies),
        key=lambda version: tuple(int(p) for p in re.findall(r"\d+", version)[:3]),
        default=None,
    )


def _resolve_go_version(module_dir: Path, package: str) -> str | None:
    return _resolve_version("go", module_dir, package)


def _resolve_npm_version(module_dir: Path, package: str) -> str | None:
    return _resolve_version("npm", module_dir, package)


def _resolve_pnpm_version(module_dir: Path, package: str) -> str | None:
    return _resolve_version("pnpm", module_dir, package)


def _resolve_yarn_version(module_dir: Path, package: str) -> str | None:
    return _resolve_version("yarn", module_dir, package)


def _resolve_cargo_version(module_dir: Path, package: str) -> str | None:
    return _resolve_version("cargo", module_dir, package)


def _resolve_maven_version(module_dir: Path, package: str) -> str | None:
    return _resolve_version("maven", module_dir, package)


def check_vendor_constraints(
    entries: list[VendorConstraintEntry], modules: list[VendoredModule]
) -> list[CheckResult]:
    results = []
    for entry in entries:
        matching = [m for m in modules if m.ecosystem == entry.ecosystem]
        if not matching:
            raise GorgetConfigError(
                f"policy vendor-constraints references ecosystem {entry.ecosystem!r} for "
                f"package {entry.package!r}, but no {entry.ecosystem!r} vendor step was "
                f"found in fetch:/transform:"
            )

        for module in matching:
            inventory = read_inventory(
                entry.ecosystem,
                module.path,
                [entry.package],
                runner=run,
                toolchain=module.toolchain,
                use_workspace=module.use_workspace,
            )
            copies = inventory.find(entry.package)
            failures = inventory.violations(entry.package, entry.version)
            actual = copies[0].version if copies else None
            if actual is None:
                results.append(
                    CheckResult(
                        type="vendor-constraints",
                        target=entry.package,
                        status="failed",
                        reason=(
                            f"{entry.package} not found in vendored {entry.ecosystem} "
                            f"module at {module.path}"
                        ),
                    )
                )
            elif not failures:
                results.append(
                    CheckResult(type="vendor-constraints", target=entry.package, status="passed")
                )
            else:
                results.append(
                    CheckResult(
                        type="vendor-constraints",
                        target=entry.package,
                        status="failed",
                        reason=(
                            f"{entry.package} is {failures[0].version}, need >= {entry.version} "
                            f"({entry.reason}); offending copies: "
                            + ", ".join(f"{copy.location}={copy.version}" for copy in failures)
                        ),
                    )
                )
    return results
