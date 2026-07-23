from unittest.mock import Mock

import pytest

from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import FetchedArtifact
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.state import StageState


def make_state(tmp_path, artifacts=()):
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    return StageState(work_dir=tmp_path, spec=Mock(), report=report, artifacts=list(artifacts))


def make_artifact(name):
    return FetchedArtifact(path=None, output_name=name, source_description=name, checksum="abc")


def test_find_artifact_returns_matching_artifact(tmp_path):
    a = make_artifact("a.tar.gz")
    b = make_artifact("b.tar.gz")
    state = make_state(tmp_path, [a, b])
    assert state.find_artifact("b.tar.gz") is b


def test_find_artifact_raises_config_error_when_missing(tmp_path):
    state = make_state(tmp_path, [make_artifact("a.tar.gz")])
    with pytest.raises(GorgetConfigError, match="b.tar.gz"):
        state.find_artifact("b.tar.gz")
