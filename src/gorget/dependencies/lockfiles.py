"""Parse npm/pnpm/yarn lockfiles for bundled dependency provides.

These are pure parsers over a lockfile on disk -- no vendoring, no network.
The `bundled-provides` post step reads them from the generated vendor archive
tree (each module's `package-lock.json`/`pnpm-lock.yaml`/`yarn.lock`) to
generate the RPM `Provides: bundled(npm(...))` block, so the provides reflect
whatever the tree actually locks (including any `vendor-bump` edits made
earlier in the pipeline).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from gorget.exceptions import GorgetConfigError

PACKAGE_NAME_RE = re.compile(r"^(?:@[^/@]+/)?[^/@]+$")


def pnpm_provides(lockfile: Path) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Returns (production, all) sets from pnpm-lock.yaml."""
    import yaml

    data = yaml.safe_load(lockfile.read_text())
    if not data:  # empty or whitespace-only lockfile -> nothing bundled
        return set(), set()
    snapshots = data.get("snapshots", {})

    # BFS from importers' non-dev dependencies for production
    prod_queue: list[str] = []
    all_queue: list[str] = []
    for importer in data.get("importers", {}).values():
        for section in ("dependencies", "optionalDependencies"):
            for name, dep in importer.get(section, {}).items():
                ref = _pnpm_reference(name, dep)
                if ref:
                    prod_queue.append(ref)
                    all_queue.append(ref)
        for name, dep in importer.get("devDependencies", {}).items():
            ref = _pnpm_reference(name, dep)
            if ref:
                all_queue.append(ref)

    production = _pnpm_walk(prod_queue, snapshots)
    all_deps = _pnpm_walk(all_queue, snapshots)
    return production, all_deps


def _pnpm_walk(queue: list[str], snapshots: dict) -> set[tuple[str, str]]:
    visited: set[str] = set()
    provides: set[tuple[str, str]] = set()
    while queue:
        key = queue.pop()
        if key in visited:
            continue
        visited.add(key)
        package_key = key.split("(", 1)[0]
        name, _, version = package_key.rpartition("@")
        if name and PACKAGE_NAME_RE.fullmatch(name) and version:
            provides.add((name, version))
        snapshot = snapshots.get(key)
        if snapshot:
            for section in ("dependencies", "optionalDependencies"):
                for dep_name, dep in snapshot.get(section, {}).items():
                    ref = _pnpm_reference(dep_name, dep)
                    if ref:
                        queue.append(ref)
    return provides


def _pnpm_reference(name: str, dependency: object) -> str | None:
    reference = dependency.get("version") if isinstance(dependency, dict) else dependency
    if not isinstance(reference, str) or reference.startswith(("link:", "workspace:", "file:")):
        return None
    if reference.startswith("npm:"):
        alias, _, version = reference[4:].rpartition("@")
        return f"{alias}@{version}" if _ else None
    return f"{name}@{reference}"


def _yarn_dependencies(package: dict) -> Any:
    for section in ("dependencies", "optionalDependencies"):
        yield from package.get(section, {}).items()


def _yarn_descriptor_name(descriptor: str) -> str:
    for protocol in ("@npm:", "@patch:", "@portal:", "@file:"):
        if protocol in descriptor:
            return descriptor.partition(protocol)[0]
    return ""


def _yarn_production_packages(
    lock: str, root_package: dict, workspaces: dict
) -> set[tuple[str, str]]:
    data = yaml.safe_load(lock)
    descriptors = {}
    packages_by_name: dict[str, list[dict]] = {}
    for key, package in data.items():
        if key == "__metadata":
            continue
        for descriptor in key.split(", "):
            descriptors[descriptor] = package
            package_name = _yarn_descriptor_name(descriptor)
            if package_name:
                packages_by_name.setdefault(package_name, []).append(package)

    provides = set()
    queue = [
        (root_package.get("name", ""), name, reference)
        for name, reference in _yarn_dependencies(root_package)
    ]
    visited_descriptors = set()
    visited_workspaces = set()
    resolutions = root_package.get("resolutions", {})
    while queue:
        parent, name, reference = queue.pop()
        bare_reference = reference.removeprefix("npm:")
        overrides = [
            value
            for pattern, value in resolutions.items()
            if pattern
            in (
                name,
                f"{name}@{reference}",
                f"{name}@{bare_reference}",
                f"{name}@npm:{bare_reference}",
                f"{parent}/{name}",
            )
        ]
        if len(set(overrides)) == 1:
            reference = overrides[0]

        if reference.startswith("workspace:"):
            if name in visited_workspaces:
                continue
            visited_workspaces.add(name)
            workspace = workspaces.get(name)
            if workspace is None:
                raise GorgetConfigError(f"Yarn workspace not found: {name}")
            queue.extend(
                (name, child, child_reference)
                for child, child_reference in _yarn_dependencies(workspace)
            )
            continue

        descriptor = f"{name}@{reference}"
        package = descriptors.get(descriptor)
        if package is None and not reference.startswith(("npm:", "patch:", "portal:", "file:")):
            descriptor = f"{name}@npm:{reference}"
            package = descriptors.get(descriptor)
        if package is None:
            locator_matches = [
                candidate for candidate in descriptors if candidate.startswith(f"{descriptor}::")
            ]
            if len(locator_matches) == 1:
                package = descriptors[locator_matches[0]]
        if package is None:
            candidates = packages_by_name.get(name, [])
            resolutions_for_name = {candidate.get("resolution") for candidate in candidates}
            if len(resolutions_for_name) == 1:
                package = candidates[0]
        if package is None:
            raise GorgetConfigError(f"Yarn descriptor not found: {descriptor}")
        if descriptor in visited_descriptors:
            continue
        visited_descriptors.add(descriptor)

        resolution = package.get("resolution", "")
        resolved_name = _yarn_descriptor_name(resolution) or name
        version = package.get("version")
        if version:
            provides.add((resolved_name, str(version)))
        queue.extend(
            (resolved_name, child, child_reference)
            for child, child_reference in _yarn_dependencies(package)
        )
    return provides


def yarn_provides(lockfile: Path) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Returns (production, all) from yarn.lock.

    Berry production dependencies are traversed from package.json and workspace manifests.
    Classic lockfiles return all dependencies for both scopes.
    """
    text = lockfile.read_text()
    if re.search(r"^__metadata:", text, re.MULTILINE):
        data = yaml.safe_load(text)
        all_deps = set()
        for key, entry in data.items():
            if key == "__metadata":
                continue
            name = _yarn_descriptor_name(entry.get("resolution", ""))
            if name and PACKAGE_NAME_RE.fullmatch(name) and entry.get("version"):
                all_deps.add((name, str(entry["version"])))
        manifest = lockfile.parent / "package.json"
        if not manifest.is_file():
            return all_deps, all_deps
        root_package = json.loads(manifest.read_text())
        patterns = root_package.get("workspaces", [])
        if isinstance(patterns, dict):
            patterns = patterns.get("packages", [])
        workspaces = {}
        for pattern in patterns:
            for package_json in lockfile.parent.glob(f"{pattern}/package.json"):
                package = json.loads(package_json.read_text())
                if package.get("name"):
                    workspaces[package["name"]] = package
        return _yarn_production_packages(text, root_package, workspaces), all_deps
    provides: set[tuple[str, str]] = set()
    current_name: str | None = None
    for line in text.splitlines():
        # Entry headers look like: "lodash@^4.17.0":
        # or: "@babel/core@^7.0.0":
        header_match = re.match(r'^"?(@?[^@\s"]+)@', line)
        if header_match and not line.startswith(" "):
            current_name = header_match.group(1)
        elif line.strip().startswith("version ") and current_name:
            version = line.strip().split('"')[1] if '"' in line else line.strip().split()[-1]
            if version and PACKAGE_NAME_RE.fullmatch(current_name):
                provides.add((current_name, version))
            current_name = None
    return provides, provides
