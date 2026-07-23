"""`strip-tarball` transform step: remove paths from a fetched tarball and repack
it, preserving the tarball's original internal layout.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from gorget.config.schema import StripTarballStep
from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import FetchedArtifact, build_artifact
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
        _remove_paths(extract_dir, step.paths)

        new_path = ctx.work_dir / target.output_name
        repack_tar_gz(extract_dir, new_path)
        _replace_artifact(state, target.output_name, new_path)


def _select_target(target_name: str | None, artifacts: list[FetchedArtifact]) -> FetchedArtifact:
    if target_name is not None:
        for artifact in artifacts:
            if artifact.output_name == target_name:
                return artifact
        raise GorgetConfigError(
            f"strip-tarball target not found among fetched artifacts: {target_name!r}"
        )
    if len(artifacts) != 1:
        raise GorgetConfigError(
            "strip-tarball requires 'target' when there is more than one fetched "
            f"artifact (found {len(artifacts)})"
        )
    return artifacts[0]


def _remove_paths(extract_dir: Path, patterns: list[str]) -> None:
    for pattern in patterns:
        matches = list(extract_dir.glob(pattern))
        if not matches:
            raise GorgetConfigError(f"strip-tarball path pattern matched nothing: {pattern!r}")
        for match in matches:
            if match.is_dir():
                shutil.rmtree(match)
            else:
                match.unlink()


def _replace_artifact(state: StageState, output_name: str, new_path: Path) -> None:
    for index, artifact in enumerate(state.artifacts):
        if artifact.output_name == output_name:
            state.artifacts[index] = build_artifact(
                new_path, output_name, artifact.source_description, dry_run=False
            )
            return
