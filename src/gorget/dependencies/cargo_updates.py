"""Edit registry requirements in a Cargo workspace without losing TOML formatting."""

from collections.abc import Mapping
from pathlib import Path

import tomlkit

from gorget.exceptions import GorgetConfigError


def cargo_manifests(module_dir: Path) -> list[Path]:
    root = module_dir.resolve()
    manifest = root / "Cargo.toml"
    if not manifest.is_file():
        raise GorgetConfigError(f"vendor-bump: no Cargo.toml found in {module_dir}")
    workspace = tomlkit.parse(manifest.read_text()).get("workspace", {})
    manifests = {manifest}
    for pattern in workspace.get("members", []):
        for member in root.glob(pattern):
            relative = member.relative_to(root)
            if any(relative.match(exclude) for exclude in workspace.get("exclude", [])):
                continue
            if not member.resolve().is_relative_to(root):
                raise GorgetConfigError(f"Cargo member escapes its workspace: {member}")
            if (member / "Cargo.toml").is_file():
                manifests.add(member / "Cargo.toml")
    return sorted(manifests)


def bump_cargo_requirements(module_dir: Path, dependency: str, specifier: str) -> bool:
    changed = False

    def edit(table: Mapping) -> bool:
        found = False
        for key, value in table.items():
            if key in ("dependencies", "dev-dependencies", "build-dependencies"):
                for alias, requirement in value.items():
                    name = (requirement.get("package", alias)
                            if isinstance(requirement, Mapping) else alias)
                    if name != dependency:
                        continue
                    if isinstance(requirement, str):
                        value[alias] = specifier
                        found = True
                    elif "version" in requirement and not any(
                        source in requirement for source in ("path", "git", "workspace")
                    ):
                        requirement["version"] = specifier
                        found = True
            elif isinstance(value, Mapping):
                found = edit(value) or found
        return found

    for manifest in cargo_manifests(module_dir):
        document = tomlkit.parse(manifest.read_text())
        if edit(document):
            manifest.write_text(tomlkit.dumps(document))
            changed = True
    return changed
