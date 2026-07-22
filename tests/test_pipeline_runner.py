import argparse
import dataclasses
import subprocess
from pathlib import Path
from typing import ClassVar

import pytest

from gorget.config.schema import PipelineSpec
from gorget.context import build_run_context
from gorget.exceptions import GorgetPolicyViolation
from gorget.pipeline.result import StageResult
from gorget.pipeline.runner import PipelineRunner


def make_ctx(tmp_path: Path):
    (tmp_path / "foo.spec").write_text("Name: foo\nVersion: 1.0.0\nRelease: 1\n")
    args = argparse.Namespace(
        pkg_version="1.2.3",
        old_version="1.2.2",
        dry_run=False,
        package_dir=str(tmp_path),
        pipeline_file=str(tmp_path / "pipeline.yaml"),
        gpg_keys_dir=str(tmp_path / "gpg-keys"),
        output_dir=str(tmp_path / "output"),
    )
    return build_run_context(args)


class RecordingStage:
    name: ClassVar[str] = "recording"
    calls: ClassVar[list] = None

    def __init__(self, label, calls):
        self.label = label
        self.calls = calls

    def run(self, ctx, spec, state):
        self.calls.append(self.label)
        return StageResult(name=self.label, status="success")


def make_recording_stage_cls(label, calls):
    def _factory():
        return RecordingStage(label, calls)

    _factory.__name__ = f"Stage_{label}"
    return _factory


def test_stages_run_in_declared_order(tmp_path, mocker):
    calls = []
    fake_order = [make_recording_stage_cls(name, calls) for name in ["a", "b", "c"]]
    mocker.patch("gorget.pipeline.runner.STAGE_ORDER", fake_order)

    ctx = make_ctx(tmp_path)
    report = PipelineRunner(ctx, PipelineSpec()).run()

    assert calls == ["a", "b", "c"]
    assert [s.name for s in report.stages] == ["a", "b", "c"]


def test_dry_run_skips_emit_stage_without_calling_it(tmp_path, mocker):
    from gorget.pipeline.stages.emit import EmitStage

    emit_run = mocker.patch.object(EmitStage, "run")
    ctx = dataclasses.replace(make_ctx(tmp_path), dry_run=True)

    report = PipelineRunner(ctx, PipelineSpec()).run()

    emit_run.assert_not_called()
    emit_stage_result = next(s for s in report.stages if s.name == "emit")
    assert emit_stage_result.status == "skipped"
    assert emit_stage_result.reason == "dry-run"


def test_non_dry_run_calls_emit_stage(tmp_path):
    ctx = make_ctx(tmp_path)
    report = PipelineRunner(ctx, PipelineSpec()).run()
    emit_stage_result = next(s for s in report.stages if s.name == "emit")
    assert emit_stage_result.status == "success"
    assert (Path(ctx.output_dir) / "report.json").exists()
    assert (Path(ctx.output_dir) / "sources").exists()


def test_exception_from_a_stage_propagates_uncaught(tmp_path, mocker):
    def _raise(ctx, spec, state):
        raise GorgetPolicyViolation("nope")

    calls = []
    fake_order = [make_recording_stage_cls("a", calls)]

    class ExplodingStage:
        name: ClassVar[str] = "exploding"

        def run(self, ctx, spec, state):
            _raise(ctx, spec, state)

    mocker.patch("gorget.pipeline.runner.STAGE_ORDER", [*fake_order, ExplodingStage])

    ctx = make_ctx(tmp_path)
    with pytest.raises(GorgetPolicyViolation, match="nope"):
        PipelineRunner(ctx, PipelineSpec()).run()
    assert calls == ["a"]


def test_fetch_stage_runs_for_real_and_populates_report_artifacts(tmp_path, mocker):
    mocker.patch(
        "gorget.fetch.spec_source.download_to",
        side_effect=lambda url, dest: dest.write_bytes(b"data"),
    )
    mocker.patch(
        "gorget.specfile.run",
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="Source0: https://example.com/foo-1.2.3.tar.gz\n",
            stderr="",
        ),
    )
    ctx = make_ctx(tmp_path)
    from gorget.config.schema import SpecSourceStep

    spec = PipelineSpec(fetch=[SpecSourceStep(index=None)])
    report = PipelineRunner(ctx, spec).run()

    fetch_result = next(s for s in report.stages if s.name == "fetch")
    assert fetch_result.status == "success"
    assert report.artifacts[0].output_name == "foo-1.2.3.tar.gz"
    assert report.artifacts[0].checksum is not None
    assert (Path(ctx.output_dir) / "foo-1.2.3.tar.gz").read_bytes() == b"data"
