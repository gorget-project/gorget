import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from gorget.config.schema import PipelineSpec
from gorget.config.substitution import SubstitutionVars
from gorget.context import RunContext
from gorget.exceptions import GorgetTransientError
from gorget.fetch.base import FetchedArtifact
from gorget.pipeline.result import PipelineReport, StageResult
from gorget.pipeline.stages.emit import EmitStage
from gorget.pipeline.state import StageState


def make_ctx(output_dir: Path) -> RunContext:
    return RunContext(
        package_dir=output_dir,
        pipeline_file=output_dir / "pipeline.yaml",
        gpg_keys_dir=output_dir / "gpg-keys",
        output_dir=output_dir,
        dry_run=False,
        spec_path=output_dir / "foo.spec",
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
    )


def make_state(work_dir: Path, artifacts: list[FetchedArtifact]) -> StageState:
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    state = StageState(work_dir=work_dir, spec=Mock(), report=report, artifacts=artifacts)
    return state


def test_emit_copies_artifacts_and_writes_manifest(tmp_path):
    src = tmp_path / "work" / "foo-1.2.3.tar.gz"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"tarball-bytes")
    artifact = FetchedArtifact(
        path=src,
        output_name="foo-1.2.3.tar.gz",
        source_description="https://example.com/foo-1.2.3.tar.gz",
        checksum="deadbeef",
    )

    output_dir = tmp_path / "output"
    ctx = make_ctx(output_dir)
    state = make_state(tmp_path / "work", [artifact])

    result = EmitStage().run(ctx, PipelineSpec(), state)

    assert result.status == "success"
    assert (output_dir / "foo-1.2.3.tar.gz").read_bytes() == b"tarball-bytes"
    assert (output_dir / "sources").read_text() == "SHA512 (foo-1.2.3.tar.gz) = deadbeef\n"


def test_emit_writes_report_json_including_own_result(tmp_path):
    output_dir = tmp_path / "output"
    ctx = make_ctx(output_dir)
    state = make_state(tmp_path / "work", [])
    state.report.stages.append(StageResult(name="fetch", status="success"))

    EmitStage().run(ctx, PipelineSpec(), state)

    report = json.loads((output_dir / "report.json").read_text())
    assert report["package"] == "foo"
    assert report["version"] == "1.2.3"
    stage_names = [s["name"] for s in report["stages"]]
    assert stage_names == ["fetch", "emit"]
    assert report["stages"][-1]["status"] == "success"


def test_emit_does_not_mutate_state_report_stages(tmp_path):
    output_dir = tmp_path / "output"
    ctx = make_ctx(output_dir)
    state = make_state(tmp_path / "work", [])

    EmitStage().run(ctx, PipelineSpec(), state)

    assert state.report.stages == []  # runner appends emit's result, not EmitStage itself


def test_emit_zero_artifacts_is_non_fatal(tmp_path):
    output_dir = tmp_path / "output"
    ctx = make_ctx(output_dir)
    state = make_state(tmp_path / "work", [])

    result = EmitStage().run(ctx, PipelineSpec(), state)

    assert result.status == "success"
    assert (output_dir / "sources").read_text() == ""


def test_emit_skips_dry_run_placeholder_artifacts_with_no_checksum(tmp_path):
    dry_run_artifact = FetchedArtifact(
        path=tmp_path / "work" / "would-be-fetched.tar.gz",
        output_name="would-be-fetched.tar.gz",
        source_description="https://example.com/would-be-fetched.tar.gz",
        checksum=None,
    )
    output_dir = tmp_path / "output"
    ctx = make_ctx(output_dir)
    state = make_state(tmp_path / "work", [dry_run_artifact])

    result = EmitStage().run(ctx, PipelineSpec(), state)

    assert result.status == "success"
    assert not (output_dir / "would-be-fetched.tar.gz").exists()
    assert (output_dir / "sources").read_text() == ""


def test_emit_raises_transient_error_when_output_dir_not_writable(tmp_path, mocker):
    output_dir = tmp_path / "output"
    ctx = make_ctx(output_dir)
    state = make_state(tmp_path / "work", [])

    mocker.patch(
        "gorget.pipeline.stages.emit.shutil.copyfile",
        side_effect=OSError("disk full"),
    )
    artifact = FetchedArtifact(
        path=tmp_path / "work" / "x.tar.gz",
        output_name="x.tar.gz",
        source_description="x",
        checksum="abc",
    )
    state.artifacts.append(artifact)

    with pytest.raises(GorgetTransientError, match="disk full"):
        EmitStage().run(ctx, PipelineSpec(), state)
