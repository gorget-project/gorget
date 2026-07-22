"""Dataclass model for the ``*.source-pipeline.yaml`` schema.

Only the ``fetch`` section (and the ``spec-update``/``spec-source``/``url``/``git``/
``vendor`` step types within it) has real behavior in this story. The remaining
top-level sections (``transform``, ``toolchain``, ``verify``, ``policy``, ``patches``,
``post``) round-trip as untyped passthrough structures so the parser doesn't choke on
a full pipeline YAML, without this story guessing at shapes a future story owns.
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
class TransformSection:
    steps: list[dict] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class ToolchainSection:
    entries: list[dict] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class VerifySection:
    steps: list[dict] = field(default_factory=list)


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
