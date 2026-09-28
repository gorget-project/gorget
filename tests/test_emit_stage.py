import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from gorget.config.schema import PipelineSpec, PublishSection
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


def test_emit_writes_only_explicit_publications(tmp_path):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    source_path = work_dir / "foo-1.2.3.tar.gz"
    source_path.write_bytes(b"source")
    signature_path = work_dir / "foo-1.2.3.tar.gz.asc"
    signature_path.write_bytes(b"signature")
    artifacts = [
        FetchedArtifact(
            path=source_path,
            output_name=source_path.name,
            source_description="source",
            checksum="source-checksum",
        ),
        FetchedArtifact(
            path=signature_path,
            output_name=signature_path.name,
            source_description="signature",
            checksum="signature-checksum",
        ),
    ]
    output_dir = tmp_path / "output"
    state = make_state(work_dir, artifacts)
    spec = PipelineSpec(publish=PublishSection(files=[source_path.name]))

    EmitStage().run(make_ctx(output_dir), spec, state)

    assert (output_dir / source_path.name).read_bytes() == b"source"
    assert not (output_dir / signature_path.name).exists()
    assert (output_dir / "sources").read_text() == (
        "SHA512 (foo-1.2.3.tar.gz) = source-checksum\n"
    )
    report = json.loads((output_dir / "report.json").read_text())
    assert [artifact["output_name"] for artifact in report["artifacts"]] == [
        source_path.name
    ]


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


def test_dry_run_accepts_planned_and_dynamic_publications(tmp_path):
    output_dir = tmp_path / "output"
    ctx = replace(make_ctx(output_dir), dry_run=True)
    state = make_state(tmp_path / "work", [])
    state.plan_derived_artifact("packed.tar.gz", "pack:file", "pack")
    state.plan_dynamic_artifacts("run:discover (discovered)")
    spec = PipelineSpec(
        publish=PublishSection(files=["packed.tar.gz", "discovered.zip"])
    )

    result = EmitStage().run(ctx, spec, state)

    assert result.status == "skipped"
    assert [artifact.output_name for artifact in state.report.artifacts] == [
        "packed.tar.gz",
        "discovered.zip",
    ]
    assert all(artifact.checksum is None for artifact in state.report.artifacts)


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
