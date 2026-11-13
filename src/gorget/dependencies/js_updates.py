"""Parse JavaScript targets and derive parent co-updates from Yarn's graph."""

from collections.abc import Callable, Sequence

from semantic_version import NpmSpec, Version

from gorget.config.schema import VendorBumpEntry
from gorget.dependencies import DependencyInventory
from gorget.exceptions import GorgetConfigError, GorgetTransientError


def js_target(dependency: str) -> tuple[str, NpmSpec | None]:
    name, separator, qualifier = dependency.rpartition("@")
    if not separator or not name:
        return dependency, None
    try:
        return name, NpmSpec(qualifier)
    except ValueError as exc:
        raise GorgetConfigError(f"Invalid JavaScript dependency selector: {dependency}") from exc


def version_floor(constraint: str) -> Version:
    """Preserve existing minimum/prefix pins such as '~4.18' and 'v1.2.3'."""
    try:
        return Version.coerce(constraint.lstrip("~vV"))
    except ValueError as exc:
        raise GorgetConfigError(f"Invalid Yarn target version: {constraint}") from exc


def _range(reference: str) -> NpmSpec | None:
    try:
        return NpmSpec(reference.removeprefix("npm:"))
    except ValueError:
        # Local/Git/patch references are not registry semver requirements.
        return None


def parent_updates(
    pins: Sequence[VendorBumpEntry],
    inventory: DependencyInventory,
    metadata: Callable[[str, str], dict],
) -> list[VendorBumpEntry]:
    """Upgrade a parent within its major when a forced child major is incompatible.

    A same-major child update is intentionally left to the explicit override;
    that is the normal security-backport case. Workspace parents are source
    packages rather than registry dependencies and are never replaced here.
    """
    updates: dict[str, VendorBumpEntry] = {}
    candidates: dict[str, dict] = {}
    for pin in pins:
        name, branch = js_target(pin.dependency)
        target = version_floor(pin.version)
        selected = [copy for copy in inventory.find(name)
                    if branch is None or branch.match(Version(copy.version))]
        old_majors = {Version(copy.version).major for copy in selected}
        if not old_majors or old_majors == {target.major}:
            continue
        for parent in inventory.copies:
            if "@workspace:" in parent.location:
                continue
            requirements = [reference for child, reference in parent.dependencies if child == name]
            for reference in requirements:
                requirement = _range(reference)
                if requirement is None or requirement.match(target):
                    continue
                major = Version(parent.version).major
                key = f"{parent.name}@^{major}"
                if key not in candidates:
                    candidates[key] = metadata(parent.name, f"^{major}")
                candidate = candidates[key]
                version = Version(candidate["version"])
                candidate_dependencies = {
                    **candidate.get("dependencies", {}),
                    **candidate.get("optionalDependencies", {}),
                }
                candidate_requirement = candidate_dependencies.get(name)
                supported = _range(candidate_requirement) if candidate_requirement else None
                if (version.major != major or version < Version(parent.version)
                        or (candidate_requirement and (
                            supported is None or not supported.match(target)
                        ))):
                    raise GorgetTransientError(
                        f"vendor-bump: {parent.name} requires {name}@{reference}; "
                        f"the latest same-major parent release does not accept {pin.version}"
                    )
                updates[key] = VendorBumpEntry(dependency=key, version=str(version))
    return list(updates.values())
