"""`license-compliance`: flag vendored dependencies with a disallowed license.

npm (`package.json`'s `license` field) and Cargo (`Cargo.toml`'s `license` field)
have machine-readable per-package license metadata; Go doesn't -- there's no
standard field, and real detection needs a heuristic scanner (e.g.
google/go-licenses) reading LICENSE files, which is meaningfully less reliable
than a declared field. Go modules get a single summary warning instead of a
fabricated check.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Iterator
from pathlib import Path

from gorget.config.schema import LicenseComplianceSection
from gorget.policy.base import CheckResult, VendoredModule


def _npm_packages(node_modules: Path) -> Iterator[tuple[str, Path]]:
    if not node_modules.is_dir():
        return
    for entry in sorted(node_modules.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.name.startswith("@"):
            for scoped in sorted(entry.iterdir()):
                yield f"{entry.name}/{scoped.name}", scoped / "package.json"
        else:
            yield entry.name, entry / "package.json"


def _npm_license(package_json: Path) -> str | None:
    data = json.loads(package_json.read_text())
    license_id = data.get("license")
    if isinstance(license_id, dict):  # legacy {"type": "..."} form
        license_id = license_id.get("type")
    return license_id if isinstance(license_id, str) else None


def _check_npm(module: VendoredModule, disallowed: set[str]) -> list[CheckResult]:
    results = []
    for name, package_json in _npm_packages(module.path / "node_modules"):
        if not package_json.is_file():
            continue
        license_id = _npm_license(package_json)
        if license_id in disallowed:
            results.append(
                CheckResult(
                    type="license-compliance",
                    target=name,
                    status="failed",
                    reason=f"disallowed license {license_id!r}",
                )
            )
    return results


def _cargo_crates(vendor_dir: Path) -> Iterator[tuple[str, Path]]:
    if not vendor_dir.is_dir():
        return
    for entry in sorted(vendor_dir.iterdir()):
        toml_path = entry / "Cargo.toml"
        if toml_path.is_file():
            yield entry.name, toml_path


def _check_cargo(module: VendoredModule, disallowed: set[str]) -> list[CheckResult]:
    results = []
    for name, toml_path in _cargo_crates(module.path / "vendor"):
        data = tomllib.loads(toml_path.read_text())
        license_id = data.get("package", {}).get("license")
        if license_id in disallowed:
            results.append(
                CheckResult(
                    type="license-compliance",
                    target=name,
                    status="failed",
                    reason=f"disallowed license {license_id!r}",
                )
            )
    return results


def check_license_compliance(
    section: LicenseComplianceSection, modules: list[VendoredModule]
) -> list[CheckResult]:
    disallowed = set(section.disallowed)
    results = []

    if any(module.ecosystem == "go" for module in modules):
        results.append(
            CheckResult(
                type="license-compliance",
                target="go",
                status="warning",
                reason="unsupported: no machine-readable license metadata for Go modules",
            )
        )

    for module in modules:
        if module.ecosystem == "npm":
            results.extend(_check_npm(module, disallowed))
        elif module.ecosystem == "cargo":
            results.extend(_check_cargo(module, disallowed))

    return results
