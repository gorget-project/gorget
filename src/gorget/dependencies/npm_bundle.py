"""Update the dependency trees shipped inside npm release archives."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path

from gorget.config.schema import ToolchainEntry, VendorBumpEntry
from gorget.dependencies import DependencyCopy, DependencyInventory
from gorget.dependencies.lockfiles import PACKAGE_NAME_RE
from gorget.dependencies.update import update_dependencies
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.package_manager import PackageManager
from gorget.util.subprocess_run import run


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n")


def _packages(module_dir: Path) -> dict[str, dict]:
    """Read installed packages, including nested copies, without following links."""
    packages: dict[str, dict] = {}

    def visit(node_modules: Path) -> None:
        if not node_modules.is_dir():
            return
        if node_modules.is_symlink():
            raise GorgetConfigError(f"Bundled node_modules must not be a symlink: {node_modules}")
        for entry in sorted(node_modules.iterdir()):
            if entry.name.startswith("."):
                continue
            if entry.is_symlink():
                raise GorgetConfigError(f"Bundled packages must not be symlinks: {entry}")
            candidates = sorted(entry.iterdir()) if entry.name.startswith("@") else [entry]
            for package in candidates:
                if package.is_symlink():
                    raise GorgetConfigError(f"Bundled packages must not be symlinks: {package}")
                manifest = package / "package.json"
                if manifest.is_file():
                    data = json.loads(manifest.read_text())
                    name, version = data.get("name"), data.get("version")
                    if not isinstance(name, str) or not PACKAGE_NAME_RE.fullmatch(name):
                        raise GorgetConfigError(f"Invalid bundled package name in {manifest}")
                    if not isinstance(version, str):
                        raise GorgetConfigError(f"Missing bundled package version in {manifest}")
                    packages[package.relative_to(module_dir).as_posix()] = data
                    visit(package / "node_modules")

    visit(module_dir / "node_modules")
    return packages


def _bundle_roots(manifest: dict, packages: dict[str, dict]) -> list[str]:
    dependencies = {**manifest.get("dependencies", {}), **manifest.get("optionalDependencies", {})}
    roots = manifest.get("bundleDependencies", manifest.get("bundledDependencies", []))
    if roots is True:
        roots = list(dependencies)
    if not isinstance(roots, list) or not roots:
        raise GorgetConfigError("bundled npm updates require nonempty bundleDependencies")
    for name in roots:
        if (not isinstance(name, str) or not PACKAGE_NAME_RE.fullmatch(name)
                or name not in dependencies):
            raise GorgetConfigError(f"Invalid bundled dependency: {name!r}")
        if (f"node_modules/{name}" not in packages
                and name not in manifest.get("optionalDependencies", {})):
            raise GorgetConfigError(f"Bundled dependency {name!r} is missing from node_modules")
    return [name for name in roots if f"node_modules/{name}" in packages]


def _inventory(module_dir: Path, packages: dict[str, dict]) -> DependencyInventory:
    return DependencyInventory("npm", module_dir, tuple(
        DependencyCopy(data["name"], data["version"], location)
        for location, data in packages.items()
    ))


def _npm(module_dir: Path, toolchain: Sequence[ToolchainEntry], *args: str) -> None:
    result = PackageManager(module_dir, toolchain, runner=run).run([
        "npm", *args, "--ignore-scripts", "--no-audit", "--no-fund",
    ])
    if result.returncode:
        raise GorgetTransientError(f"Bundled npm {' '.join(args)} failed: {result.stderr.strip()}")


def _preserve_package(source: Path, destination: Path) -> None:
    """Retain unchanged package payloads, including prebuilt native artifacts."""
    for entry in destination.iterdir():
        if entry.name == "node_modules":
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    for entry in source.iterdir():
        if entry.name == "node_modules":
            continue
        target = destination / entry.name
        if entry.is_symlink():
            target.symlink_to(entry.readlink())
        elif entry.is_dir():
            shutil.copytree(entry, target, symlinks=True)
        else:
            shutil.copy2(entry, target)


def _sync_lockfile(
    path: Path, manifest: dict, before: dict, resolved: dict,
) -> None:
    """Refresh shipped entries in an existing lock, retaining external dependencies."""
    if not path.is_file():
        return  # The synthetic lock is an install input, not a new upstream file.
    lock = json.loads(path.read_text())
    if not isinstance(lock.get("packages"), dict):
        raise GorgetConfigError("Bundled npm updates require lockfileVersion 2 or 3")
    for location in list(lock["packages"]):
        if any(location == old or location.startswith(old + "/node_modules/") for old in before):
            del lock["packages"][location]
    for location, data in resolved["packages"].items():
        if location:
            external = lock["packages"].get(location)
            name = location.rsplit("node_modules/", 1)[-1]
            if external and (
                external.get("version") != data.get("version")
                or external.get("name", name) != data.get("name", name)
                or (external.get("integrity") and data.get("integrity")
                    and external["integrity"] != data["integrity"])
            ):
                raise GorgetConfigError(
                    f"Bundled update conflicts with unbundled lockfile entry {location} in {path}"
                )
            lock["packages"][location] = {**(external or data), "inBundle": True}
    root = lock["packages"].get("", {})
    for section in ("dependencies", "optionalDependencies"):
        if section in manifest:
            root[section] = manifest[section]
    lock["packages"][""] = root
    # npm 7/8's compatibility section duplicates the graph; avoid stale v1 data.
    lock.pop("dependencies", None)
    lock["lockfileVersion"] = 3
    _write_json(path, lock)


def update_npm_bundle(
    module_dir: Path, pins: Sequence[VendorBumpEntry], toolchain: Sequence[ToolchainEntry] = (),
) -> None:
    """Resolve only the declared bundle roots and publish their runtime closure."""
    manifest_path = module_dir / "package.json"
    if not manifest_path.is_file():
        raise GorgetConfigError(f"No package.json found in {module_dir}")
    manifest = json.loads(manifest_path.read_text())
    before = _packages(module_dir)
    roots = _bundle_roots(manifest, before)
    inventory = _inventory(module_dir, before)
    for pin in pins:
        if not inventory.find(pin.dependency):
            raise GorgetConfigError(f"{pin.dependency!r} is not present in the npm bundle")
    if not any(inventory.violations(pin.dependency, pin.version) for pin in pins):
        return

    with tempfile.TemporaryDirectory(prefix="gorget-npm-bundle-") as temporary:
        project = Path(temporary)
        # Development/workspace dependencies and unbundled runtime dependencies
        # must never enter this resolver project or the published bundle.
        dependencies = {**manifest.get("dependencies", {}),
                        **manifest.get("optionalDependencies", {})}
        projected = {"name": "gorget-npm-bundle", "version": "1.0.0", "private": True,
                     "dependencies": {name: dependencies[name] for name in roots}}
        if manifest.get("overrides"):
            # Keep earlier pins effective when a later update changes another
            # part of the bundle. Work on a JSON copy, not the upstream object.
            projected["overrides"] = json.loads(json.dumps(manifest["overrides"]))
        _write_json(project / "package.json", projected)
        npmrc = module_dir / ".npmrc"
        if npmrc.is_file():
            shutil.copyfile(npmrc, project / ".npmrc")
        shutil.copytree(module_dir / "node_modules", project / "node_modules", symlinks=True)
        (project / "node_modules" / ".package-lock.json").unlink(missing_ok=True)
        _npm(project, toolchain, "install", "--package-lock-only")
        shutil.rmtree(project / "node_modules")
        update_dependencies("npm", project, pins, toolchain)
        _npm(project, toolchain, "ci", "--omit=dev")
        (project / "node_modules" / ".package-lock.json").unlink(missing_ok=True)
        after = _packages(project)
        actual = _inventory(project, after)
        for pin in pins:
            if not actual.find(pin.dependency) or actual.violations(pin.dependency, pin.version):
                raise GorgetTransientError(
                    f"Installed bundle does not satisfy {pin.dependency} {pin.version}"
                )
        for location, data in after.items():
            old = before.get(location)
            if old and (old["name"], old["version"]) == (data["name"], data["version"]):
                _preserve_package(module_dir / location, project / location)

        updated = json.loads((project / "package.json").read_text())
        for section in ("dependencies", "optionalDependencies"):
            for name in roots:
                if name in manifest.get(section, {}) and name in updated["dependencies"]:
                    # Preserve ranges for unrelated roots; change only bumped declarations.
                    if name in {pin.dependency for pin in pins}:
                        manifest[section][name] = updated["dependencies"][name]
        manifest.setdefault("overrides", {}).update(updated.get("overrides", {}))
        resolved = json.loads((project / "package-lock.json").read_text())
        for filename in ("package-lock.json", "npm-shrinkwrap.json"):
            _sync_lockfile(module_dir / filename, manifest, before, resolved)
        _write_json(manifest_path, manifest)
        shutil.rmtree(module_dir / "node_modules")
        shutil.copytree(project / "node_modules", module_dir / "node_modules", symlinks=True)
