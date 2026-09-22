"""Derive a filtered tarball without changing its input artifact."""

from __future__ import annotations

import shutil
from pathlib import Path

from gorget.config.schema import StripTarballStep
from gorget.exceptions import GorgetConfigError
from gorget.pipeline.artifact import (
    Artifact,
    build_derived_artifact,
    derived_artifact_path,
)
from gorget.pipeline.state import StageState
from gorget.transform.base import TransformContext
from gorget.util.archive import extract_tar_gz, repack_tar_gz


class StripTarballHandler:
    def run(self, step: StripTarballStep, ctx: TransformContext, state: StageState) -> None:
        target = _select_target(step.target, state.artifacts)
        if ctx.dry_run:
            return

        extract_dir = ctx.work_dir / "_strip" / target.output_name
        extract_tar_gz(target.path, extract_dir)
        removed_paths = _remove_paths(extract_dir, step.paths)

        if target.checksum is None:
            raise AssertionError("non-dry-run artifacts must have a checksum")
        new_path = derived_artifact_path(
            ctx.work_dir, f"strip-tarball/{target.checksum}", target.output_name
        )
        repack_tar_gz(extract_dir, new_path)
        replacement = build_derived_artifact(
            new_path,
            target.output_name,
            target.source_description,
            dry_run=False,
            parents=[target],
        )
        state.replace_artifact(replacement)
        state.source.adopt_filtered_artifact(target, replacement, removed_paths)


def _select_target(target_name: str | None, artifacts: list[Artifact]) -> Artifact:
    if target_name is not None:
        for artifact in artifacts:
            if artifact.output_name == target_name:
                return artifact
        raise GorgetConfigError(
            f"strip-tarball target not found among pipeline artifacts: {target_name!r}"
        )
    if len(artifacts) != 1:
        raise GorgetConfigError(
            "strip-tarball requires 'target' when there is more than one pipeline "
            f"artifact (found {len(artifacts)})"
        )
    return artifacts[0]


def _remove_paths(extract_dir: Path, patterns: list[str]) -> list[Path]:
    removed_paths = []
    for pattern in patterns:
        matches = list(extract_dir.glob(pattern))
        if not matches:
            raise GorgetConfigError(f"strip-tarball path pattern matched nothing: {pattern!r}")
        for match in matches:
            removed_paths.append(match.relative_to(extract_dir))
            if match.is_dir() and not match.is_symlink():
                shutil.rmtree(match)
            else:
                match.unlink()
    return removed_paths
