"""Dataclass model for the ``*.source-pipeline.yaml`` schema.

The ``fetch``, ``transform``, and ``toolchain`` sections have real behavior. The
remaining top-level sections (``verify``, ``policy``, ``patches``, ``post``) round-trip
as untyped passthrough structures so the parser doesn't choke on a full pipeline YAML,
without this story guessing at shapes a future story owns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, kw_only=True)
class MacroSubstitution:
    """A single regex-based text substitution applied to the raw spec file."""

    pattern: str
    replacement: str


@dataclass(frozen=True, kw_only=True)
class SpecUpdateStep:
    type: Literal["spec-update"] = "spec-update"
    set_version: bool = True
    reset_release: str | None = "1"
    substitutions: list[MacroSubstitution] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class SpecSourceStep:
    type: Literal["spec-source"] = "spec-source"
    index: int | None = None
    rename: str | None = None


@dataclass(frozen=True, kw_only=True)
class UrlStep:
    type: Literal["url"] = "url"
    url: str
    filename: str | None = None


@dataclass(frozen=True, kw_only=True)
class GitStep:
    type: Literal["git"] = "git"
    repo: str
    ref: str
    shallow: bool = True
    archive_name: str | None = None
    subdir: str | None = None


@dataclass(frozen=True, kw_only=True)
class VendorModule:
    path: str = "."
    name: str | None = None


@dataclass(frozen=True, kw_only=True)
class VendorStep:
    type: Literal["vendor"] = "vendor"
    ecosystem: Literal["go", "npm", "cargo", "composer"]
    archive_name: str | None = None
    modules: list[VendorModule] = field(default_factory=lambda: [VendorModule(path=".")])


FetchStep = SpecUpdateStep | SpecSourceStep | UrlStep | GitStep | VendorStep

# type-key -> dataclass, used by config/loader.py to dispatch `fetch:` list items.
FETCH_STEP_TYPES: dict[str, type] = {
    "spec-update": SpecUpdateStep,
    "spec-source": SpecSourceStep,
    "url": UrlStep,
    "git": GitStep,
    "vendor": VendorStep,
}


@dataclass(frozen=True, kw_only=True)
class ToolchainEntry:
    name: str
    version: str


@dataclass(frozen=True, kw_only=True)
class StripTarballStep:
    type: Literal["strip-tarball"] = "strip-tarball"
    target: str | None = None
    paths: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class VendorPinEntry:
    dependency: str
    minimum_version: str


@dataclass(frozen=True, kw_only=True)
class VendorPinStep:
    type: Literal["vendor-pin"] = "vendor-pin"
    ecosystem: Literal["go", "npm", "cargo"]
    pins: list[VendorPinEntry] = field(default_factory=list)
    modules: list[VendorModule] = field(default_factory=lambda: [VendorModule(path=".")])


@dataclass(frozen=True, kw_only=True)
class BuildUiStep:
    type: Literal["build-ui"] = "build-ui"
    ecosystem: Literal["npm", "yarn"] = "npm"
    script: str = "build"
    path: str = "."
    output_dir: str = "dist"
    archive_name: str | None = None


@dataclass(frozen=True, kw_only=True)
class RunStep:
    type: Literal["run"] = "run"
    command: list[str] = field(default_factory=list)
    path: str = "."
    outputs: list[str] = field(default_factory=list)


# `vendor` is reused verbatim from the fetch schema: a `transform:` list can run
# `vendor-pin` then `vendor` in order (edit lockfiles, then vendor) since Fetch's
# own `vendor` step always runs before Transform and can't do that ordering itself.
TransformStep = StripTarballStep | VendorPinStep | BuildUiStep | RunStep | VendorStep

TRANSFORM_STEP_TYPES: dict[str, type] = {
    "strip-tarball": StripTarballStep,
    "vendor-pin": VendorPinStep,
    "build-ui": BuildUiStep,
    "run": RunStep,
    "vendor": VendorStep,
}


@dataclass(frozen=True, kw_only=True)
class TransformSection:
    steps: list[TransformStep] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class ToolchainSection:
    entries: list[ToolchainEntry] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class GpgSignatureStep:
    type: Literal["gpg-signature"] = "gpg-signature"
    # No auto-select fallback (unlike e.g. strip-tarball's optional `target`) --
    # guessing wrong on a security check is worse than on a convenience transform.
    target: str
    signature: str
    keyring: str


@dataclass(frozen=True, kw_only=True)
class ChecksumFileStep:
    type: Literal["checksum-file"] = "checksum-file"
    target: str
    checksums_file: str
    algorithm: Literal["sha256", "sha512", "sha1", "md5"] = "sha256"


VerifyStep = GpgSignatureStep | ChecksumFileStep

VERIFY_STEP_TYPES: dict[str, type] = {
    "gpg-signature": GpgSignatureStep,
    "checksum-file": ChecksumFileStep,
}


@dataclass(frozen=True, kw_only=True)
class VerifySection:
    steps: list[VerifyStep] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class AcceptedChecksumEntry:
    file: str
    checksum: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class AcceptedChecksumsSection:
    entries: list[AcceptedChecksumEntry] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class PolicySection:
    rules: dict = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class PatchesSection:
    entries: list[dict] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class PostSection:
    steps: list[dict] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class PipelineSpec:
    package: str | None = None
    fetch: list[FetchStep] = field(default_factory=list)
    transform: TransformSection = field(default_factory=TransformSection)
    toolchain: ToolchainSection = field(default_factory=ToolchainSection)
    verify: VerifySection = field(default_factory=VerifySection)
    policy: PolicySection = field(default_factory=PolicySection)
    patches: PatchesSection = field(default_factory=PatchesSection)
    post: PostSection = field(default_factory=PostSection)
    accepted_checksums: AcceptedChecksumsSection = field(
        default_factory=AcceptedChecksumsSection
    )
