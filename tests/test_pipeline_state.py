from unittest.mock import Mock

import pytest

from gorget.exceptions import GorgetConfigError, GorgetInternalError
from gorget.fetch.base import FetchedArtifact
from gorget.pipeline.artifact import Artifact
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.state import StageState


def make_state(tmp_path, artifacts=()):
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    return StageState(work_dir=tmp_path, spec=Mock(), report=report, artifacts=list(artifacts))


def make_artifact(name):
    return FetchedArtifact(path=None, output_name=name, source_description=name, checksum="abc")


def make_derived_artifact(name):
    return Artifact(
        path=None,
        output_name=name,
        source_description=name,
        checksum="abc",
        kind="derived",
    )


def test_find_artifact_returns_matching_artifact(tmp_path):
    a = make_artifact("a.tar.gz")
    b = make_artifact("b.tar.gz")
    state = make_state(tmp_path, [a, b])
    assert state.find_artifact("b.tar.gz") is b


def test_find_artifact_raises_config_error_when_missing(tmp_path):
    state = make_state(tmp_path, [make_artifact("a.tar.gz")])
    with pytest.raises(GorgetConfigError, match="b.tar.gz"):
        state.find_artifact("b.tar.gz")


def test_add_input_artifacts_updates_inputs_and_publications(tmp_path):
    state = make_state(tmp_path)
    artifact = make_artifact("source.tar.gz")

    state.add_input_artifacts([artifact])

    assert state.input_artifacts == [artifact]
    assert state.artifacts == [artifact]


def test_add_input_artifacts_rejects_duplicate_batch_without_partial_update(tmp_path):
    state = make_state(tmp_path)

    with pytest.raises(GorgetConfigError, match="Duplicate artifact output name"):
        state.add_input_artifacts(
            [make_artifact("source.tar.gz"), make_artifact("source.tar.gz")]
        )

    assert state.input_artifacts == []
    assert state.artifacts == []


def test_add_derived_artifact_rejects_input_kind(tmp_path):
    state = make_state(tmp_path)

    with pytest.raises(GorgetInternalError, match="Derivation produced input"):
        state.add_derived_artifact(make_artifact("source.tar.gz"))


def test_add_derived_artifact_rejects_existing_output_name(tmp_path):
    existing = make_artifact("source.tar.gz")
    state = make_state(tmp_path, [existing])

    with pytest.raises(GorgetConfigError, match="Duplicate artifact output name"):
        state.add_derived_artifact(make_derived_artifact("source.tar.gz"))

    assert state.artifacts == [existing]
