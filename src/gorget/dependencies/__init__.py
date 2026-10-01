"""Resolved dependency copies shared by updates, policy, and RPM Provides."""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from gorget.config.schema import ToolchainEntry
from gorget.dependencies.lockfiles import (
    PACKAGE_NAME_RE,
    _pnpm_reference,
    _yarn_descriptor_name,
    pnpm_provides,
    yarn_provides,
)
from gorget.package_manager import PackageManager
from gorget.util.subprocess_run import run
from gorget.util.version import satisfies_constraint


@dataclass(frozen=True)
class DependencyCopy:
    name: str
    version: str
    location: str
    dependencies: tuple[tuple[str, str], ...] = ()
    production: bool = True


@dataclass(frozen=True)
class DependencyInventory:
    ecosystem: str
    workspace: Path
    copies: tuple[DependencyCopy, ...]

    def find(self, name: str) -> tuple[DependencyCopy, ...]:
        return tuple(copy for copy in self.copies if copy.name == name)

    def violations(self, name: str, constraint: str) -> tuple[DependencyCopy, ...]:
        return tuple(
            copy for copy in self.find(name) if not satisfies_constraint(copy.version, constraint)
        )

    def provides(self, *, production: bool = False) -> set[tuple[str, str]]:
        return {
            (copy.name, copy.version) for copy in self.copies if not production or copy.production
        }


def _edges(package: dict) -> tuple[tuple[str, str], ...]:
    return tuple(
        (name, str(reference))
        for section in ("dependencies", "optionalDependencies")
        for name, reference in package.get(section, {}).items()
    )


def read_inventory(
    ecosystem: str,
    workspace: Path,
    packages: Sequence[str] = (),
    *,
    toolchain: Sequence[ToolchainEntry] = (),
    runner: Callable = run,
    use_workspace: bool = True,
) -> DependencyInventory:
    """Preserve every resolved copy and its location, including unused lock entries."""
    copies: list[DependencyCopy] = []
    if ecosystem == "npm":
        lockfile = workspace / "package-lock.json"
        if lockfile.is_file():
            data = json.loads(lockfile.read_text().strip() or "{}")

            def visit(dependencies: dict, parent: str = "") -> None:
                for name, entry in dependencies.items():
                    if not isinstance(entry, dict):
                        continue
                    location = f"{parent}/node_modules/{name}".lstrip("/")
                    if isinstance(entry.get("version"), str) and PACKAGE_NAME_RE.fullmatch(name):
                        copies.append(
                            DependencyCopy(
                                name,
                                entry["version"],
                                location,
                                _edges(entry),
                                not entry.get("dev", False),
                            )
                        )
                    visit(entry.get("dependencies", {}), location)

            if data.get("packages"):
                for location, entry in data["packages"].items():
                    if "node_modules/" in location and isinstance(entry.get("version"), str):
                        name = entry.get("name") or location.rsplit("node_modules/", 1)[1]
                        if not PACKAGE_NAME_RE.fullmatch(name):
                            continue
                        copies.append(
                            DependencyCopy(
                                name,
                                entry["version"],
                                location,
                                _edges(entry),
                                not entry.get("dev", False),
                            )
                        )
            else:
                visit(data.get("dependencies", {}))
        if not copies:
            for name in packages:
                manifest = workspace / "node_modules" / name / "package.json"
                if manifest.is_file():
                    entry = json.loads(manifest.read_text())
                    if isinstance(entry.get("version"), str):
                        copies.append(DependencyCopy(name, entry["version"], str(manifest)))
    elif ecosystem == "pnpm":
        lockfile = workspace / "pnpm-lock.yaml"
        if lockfile.is_file():
            production, _ = pnpm_provides(lockfile)
            data = yaml.safe_load(lockfile.read_text()) or {}
            for location, entry in data.get("snapshots", {}).items():
                name, _, version = location.split("(", 1)[0].rpartition("@")
                if name and version:
                    edges = tuple(
                        (child, reference)
                        for child, dependency in (entry or {}).get("dependencies", {}).items()
                        if (reference := _pnpm_reference(child, dependency))
                    )
                    copies.append(
                        DependencyCopy(
                            name, version, location, edges, (name, version) in production
                        )
                    )
    elif ecosystem == "yarn":
        lockfile = workspace / "yarn.lock"
        if not lockfile.is_file():
            return read_inventory("npm", workspace, packages)
        text = lockfile.read_text()
        production, all_packages = yarn_provides(lockfile)
        if re.search(r"^__metadata:", text, re.M):
            for location, entry in (yaml.safe_load(text) or {}).items():
                if location == "__metadata":
                    continue
                name = _yarn_descriptor_name(entry.get("resolution", ""))
                if not name:
                    name = location.split(", ")[0].rsplit("@", 1)[0]
                if name and entry.get("version"):
                    version = str(entry["version"])
                    copies.append(
                        DependencyCopy(
                            name, version, location, _edges(entry), (name, version) in production
                        )
                    )
        else:
            blocks = re.split(r"(?=^[^\s#].*:$)", text, flags=re.M)
            for block in blocks:
                lines = block.splitlines()
                if not lines or lines[0].startswith("#"):
                    continue
                header = lines[0].rstrip(":")
                descriptor = header.split(", ")[0].strip('"')
                name = descriptor.rsplit("@", 1)[0]
                match = re.search(r'^  version\s+"?([^"\s]+)', block, re.M)
                if match and (name, match[1]) in all_packages:
                    edges = tuple(re.findall(r'^    "?([^"\s]+)"?\s+"?([^"\s]+)', block, re.M))
                    copies.append(DependencyCopy(name, match[1], header, edges))
    elif ecosystem == "cargo":
        lockfile = workspace / "Cargo.lock"
        if lockfile.is_file():
            for entry in tomllib.loads(lockfile.read_text()).get("package", []):
                if entry.get("name") and entry.get("version"):
                    copies.append(
                        DependencyCopy(
                            entry["name"],
                            entry["version"],
                            f"{entry['name']}@{entry['version']}:"
                            f"{entry.get('source', 'workspace')}",
                            tuple(
                                (dep.split(" ", 1)[0], dep) for dep in entry.get("dependencies", [])
                            ),
                        )
                    )
    elif ecosystem in ("go", "maven"):
        manager = PackageManager(
            workspace,
            toolchain,
            runner=runner,
            use_workspace=use_workspace and (workspace / "go.work").is_file(),
        )
        for name in packages:
            if ecosystem == "go":
                result = manager.run(["go", "list", "-m", name])
                parts = result.stdout.split()
                version = parts[1] if result.returncode == 0 and len(parts) >= 2 else None
            else:
                command = ["mvn"]
                if (workspace / "vendor").is_dir():
                    command.extend(["-o", f"-Dmaven.repo.local={workspace / 'vendor'}"])
                command.extend(["dependency:tree", f"-Dincludes={name}", "-DoutputType=text"])
                result = manager.run(command)
                if result.returncode == 0:
                    for index, match in enumerate(
                        re.finditer(rf"(?:^|\s){re.escape(name)}:[^:\s]+:([^:\s]+):", result.stdout)
                    ):
                        copies.append(DependencyCopy(name, match[1], f"{workspace}:tree:{index}"))
                continue
            if version:
                copies.append(DependencyCopy(name, version, str(workspace)))
    return DependencyInventory(ecosystem, workspace, tuple(copies))


def bundled_provides(ecosystem: str, workspace: Path, modules: Sequence) -> dict:
    inventories = [read_inventory(ecosystem, workspace / module.path) for module in modules]
    return {
        scope: sorted(
            set().union(
                *(inventory.provides(production=scope == "production") for inventory in inventories)
            )
        )
        for scope in ("production", "all")
    }
