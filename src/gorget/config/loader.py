"""Load a `*.source-pipeline.yaml` file into a `PipelineSpec`.

Sequencing: yaml.safe_load -> substitute (raw dict/list/str tree) -> parse into
dataclasses. Substitution happens before parsing so the schema/parsing code never
has to reason about `${...}` tokens.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from gorget.config.schema import (
    FETCH_STEP_TYPES,
    FetchStep,
    MacroSubstitution,
    PatchesSection,
    PipelineSpec,
    PolicySection,
    PostSection,
    ToolchainSection,
    TransformSection,
    VendorModule,
    VerifySection,
)
from gorget.config.substitution import SubstitutionVars, walk_and_substitute
from gorget.exceptions import GorgetConfigError

logger = logging.getLogger(__name__)

_KNOWN_TOP_LEVEL_KEYS = {
    "package",
    "fetch",
    "transform",
    "toolchain",
    "verify",
    "policy",
    "patches",
    "post",
}


def load_yaml(path: Path) -> dict:
    try:
        text = path.read_text()
    except OSError as exc:
        raise GorgetConfigError(f"Could not read pipeline YAML {path}: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise GorgetConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise GorgetConfigError(f"Pipeline YAML {path} must be a mapping at the top level")
    return raw


def _snake_case_keys(raw: dict) -> dict:
    """YAML keys are kebab-case (e.g. `reset-release`); dataclass fields are snake_case."""
    return {key.replace("-", "_"): value for key, value in raw.items()}


def _parse_fetch_step(raw_step: object) -> FetchStep:
    if not isinstance(raw_step, dict):
        raise GorgetConfigError(f"Each fetch step must be a mapping, got: {raw_step!r}")
    step = _snake_case_keys(raw_step)
    step_type = step.pop("type", None)
    if step_type not in FETCH_STEP_TYPES:
        raise GorgetConfigError(
            f"Unknown fetch step type: {step_type!r} (expected one of "
            f"{sorted(FETCH_STEP_TYPES)})"
        )
    step_cls = FETCH_STEP_TYPES[step_type]
    if step_type == "spec-update" and "substitutions" in step:
        step["substitutions"] = [
            MacroSubstitution(**_snake_case_keys(sub)) for sub in step["substitutions"]
        ]
    if step_type == "vendor" and "modules" in step:
        step["modules"] = [VendorModule(**_snake_case_keys(mod)) for mod in step["modules"]]
    try:
        return step_cls(**step)
    except TypeError as exc:
        raise GorgetConfigError(f"Invalid {step_type} fetch step: {exc}") from exc


def parse_pipeline_spec(raw: dict) -> PipelineSpec:
    unknown_keys = set(raw) - _KNOWN_TOP_LEVEL_KEYS
    for key in sorted(unknown_keys):
        logger.warning("Ignoring unknown top-level pipeline YAML key: %s", key)

    raw_fetch = raw.get("fetch", [])
    if not isinstance(raw_fetch, list):
        raise GorgetConfigError("The 'fetch' section must be a list of steps")
    fetch_steps = [_parse_fetch_step(step) for step in raw_fetch]

    return PipelineSpec(
        package=raw.get("package"),
        fetch=fetch_steps,
        transform=_parse_list_section(raw, "transform", TransformSection, "steps"),
        toolchain=_parse_list_section(raw, "toolchain", ToolchainSection, "entries"),
        verify=_parse_list_section(raw, "verify", VerifySection, "steps"),
        policy=_parse_dict_section(raw, "policy", PolicySection, "rules"),
        patches=_parse_list_section(raw, "patches", PatchesSection, "entries"),
        post=_parse_list_section(raw, "post", PostSection, "steps"),
    )


def _parse_list_section(raw: dict, key: str, section_cls: type, field_name: str):
    if key not in raw:
        return section_cls()
    value = raw[key]
    if not isinstance(value, list):
        raise GorgetConfigError(f"The '{key}' section must be a list")
    return section_cls(**{field_name: value})


def _parse_dict_section(raw: dict, key: str, section_cls: type, field_name: str):
    if key not in raw:
        return section_cls()
    value = raw[key]
    if not isinstance(value, dict):
        raise GorgetConfigError(f"The '{key}' section must be a mapping")
    return section_cls(**{field_name: value})


def build_pipeline_spec(path: Path, *, substitution_vars: SubstitutionVars) -> PipelineSpec:
    raw = load_yaml(path)
    substituted = walk_and_substitute(raw, substitution_vars)
    assert isinstance(substituted, dict)
    return parse_pipeline_spec(substituted)


__all__ = [
    "build_pipeline_spec",
    "load_yaml",
    "parse_pipeline_spec",
]
