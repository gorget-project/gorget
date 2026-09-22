"""Select the artifact files that leave the pipeline."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from gorget.config.schema import PublishSection
from gorget.exceptions import GorgetConfigError
from gorget.pipeline.artifact import (
    Artifact,
    build_derived_artifact,
    derived_artifact_path,
)

logger = logging.getLogger("gorget.pipeline")


@dataclass(frozen=True)
class ArtifactPlan:
    """One future artifact with one or more mutually exclusive output names."""

    alternatives: tuple[Artifact, ...]

    @property
    def output_names(self) -> tuple[str, ...]:
        return tuple(artifact.output_name for artifact in self.alternatives)


def build_artifact_plan(
    work_dir: Path,
    producer: str,
    output_names: Sequence[str],
    source_description: str,
) -> ArtifactPlan:
    alternatives = tuple(
        build_derived_artifact(
            derived_artifact_path(work_dir, producer, output_name),
            output_name,
            source_description,
            dry_run=True,
        )
        for output_name in dict.fromkeys(output_names)
    )
    if not alternatives:
        raise GorgetConfigError("An artifact plan must have at least one output name")
    return ArtifactPlan(alternatives=alternatives)


def assign_artifact_plans(
    artifacts: Sequence[Artifact],
    plans: Sequence[ArtifactPlan],
    required_names: set[str] | None = None,
) -> dict[int, Artifact]:
    """Choose one unique output from each plan, including all required names."""
    fixed_names = {artifact.output_name for artifact in artifacts}
    required = (required_names or set()) - fixed_names
    possible_names = {
        artifact.output_name for plan in plans for artifact in plan.alternatives
    }
    missing = required - possible_names
    if missing:
        name = sorted(missing)[0]
        raise GorgetConfigError(f"Published artifact was not produced: {name!r}")

    order = sorted(
        range(len(plans)),
        key=lambda index: (
            not bool(required.intersection(plans[index].output_names)),
            len(plans[index].alternatives),
        ),
    )
    assignment: dict[int, Artifact] = {}

    def search(position: int, used_names: set[str]) -> bool:
        if position == len(order):
            return required.issubset(used_names)

        remaining_names = {
            artifact.output_name
            for index in order[position:]
            for artifact in plans[index].alternatives
        }
        if not required.issubset(used_names | remaining_names):
            return False

        index = order[position]
        alternatives = sorted(
            plans[index].alternatives,
            key=lambda artifact: artifact.output_name not in required,
        )
        for artifact in alternatives:
            if artifact.output_name in fixed_names or artifact.output_name in used_names:
                continue
            assignment[index] = artifact
            if search(position + 1, used_names | {artifact.output_name}):
                return True
        assignment.pop(index, None)
        return False

    if search(0, set(fixed_names)):
        return assignment

    if required:
        names = ", ".join(repr(name) for name in sorted(required))
        raise GorgetConfigError(
            f"Published artifacts cannot be produced together: {names}"
        )
    raise GorgetConfigError("Planned artifacts cannot have unique output names")


def select_publications(
    artifacts: Sequence[Artifact],
    publish: PublishSection | None,
    artifact_plans: Sequence[ArtifactPlan] = (),
) -> list[Artifact]:
    """Return publication artifacts in declared order.

    The ``None`` branch preserves pipelines written before ``publish`` became
    available. Delete that branch when the section becomes required.
    """
    if publish is None:
        logger.warning(
            "Deprecated implicit publication: no 'publish' section; publishing "
            "all artifacts"
        )
        return list(artifacts)

    seen = set()
    for output_name in publish.files:
        if output_name in seen:
            raise GorgetConfigError(
                f"Duplicate filename in 'publish.files': {output_name!r}"
            )
        seen.add(output_name)

    by_name = {artifact.output_name: artifact for artifact in artifacts}
    missing_names = set(publish.files) - set(by_name)
    assignment = assign_artifact_plans(artifacts, artifact_plans, missing_names)
    by_name.update(
        (artifact.output_name, artifact) for artifact in assignment.values()
    )

    selected = []
    for output_name in publish.files:
        try:
            selected.append(by_name[output_name])
        except KeyError as exc:
            raise GorgetConfigError(
                f"Published artifact was not produced: {output_name!r}"
            ) from exc
    return selected
