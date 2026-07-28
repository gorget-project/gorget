import subprocess
import tarfile

import pytest

from gorget.config.schema import RunStep, ToolchainEntry
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.state import StageState
from gorget.transform.base import TransformContext
from gorget.transform.run_step import RunHandler


def make_ctx(work_dir, source_dir, toolchain=(), dry_run=False):
    return TransformContext(
        work_dir=work_dir,
        source_dir=source_dir,
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
        toolchain=list(toolchain),
        dry_run=dry_run,
        package_dir=work_dir,
    )


def make_state(work_dir):
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    return StageState(work_dir=work_dir, spec=None, report=report)


def test_run_archives_file_output(tmp_path, mocker):
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    def fake_run(args, cwd=None):
        (cwd / "generated.txt").write_text("output")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    mock_run = mocker.patch("gorget.transform.run_step.run", side_effect=fake_run)
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    step = RunStep(command=["make", "generate"], outputs=["generated.txt"])
    RunHandler().run(step, ctx, state)

    assert mock_run.call_args.args[0] == ["make", "generate"]
    assert mock_run.call_args.kwargs["cwd"] == source_dir
    artifact = state.artifacts[0]
    assert artifact.output_name == "generated.txt"
    assert artifact.path.read_text() == "output"


def test_run_archives_directory_output_as_tarball(tmp_path, mocker):
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    def fake_run(args, cwd=None):
        (cwd / "generated" / "sub").mkdir(parents=True)
        (cwd / "generated" / "a.txt").write_text("a")
        (cwd / "generated" / "sub" / "b.txt").write_text("b")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    mocker.patch("gorget.transform.run_step.run", side_effect=fake_run)
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    step = RunStep(command=["make", "generate"], outputs=["generated"])
    RunHandler().run(step, ctx, state)

    artifact = state.artifacts[0]
    assert artifact.output_name == "generated.tar.gz"
    with tarfile.open(artifact.path) as tar:
        names = tar.getnames()
    assert "a.txt" in names
    assert "sub/b.txt" in names


def test_run_multiple_declared_outputs_produce_multiple_artifacts(tmp_path, mocker):
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    def fake_run(args, cwd=None):
        (cwd / "a.txt").write_text("a")
        (cwd / "b.txt").write_text("b")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    mocker.patch("gorget.transform.run_step.run", side_effect=fake_run)
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    step = RunStep(command=["touch-both"], outputs=["a.txt", "b.txt"])
    RunHandler().run(step, ctx, state)

    assert {a.output_name for a in state.artifacts} == {"a.txt", "b.txt"}


def test_run_uses_declared_path_as_cwd(tmp_path, mocker):
    source_dir = tmp_path / "src"
    (source_dir / "subdir").mkdir(parents=True)
    mock_run = mocker.patch(
        "gorget.transform.run_step.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    step = RunStep(command=["make"], path="subdir")
    RunHandler().run(step, ctx, state)
    assert mock_run.call_args.kwargs["cwd"] == source_dir / "subdir"


def test_run_toolchain_param_does_not_change_command(tmp_path, mocker):
    # toolchain activation isn't implemented yet (gorget/toolchain.py); the
    # param is accepted but wrap_command() is currently a no-op passthrough.
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    mock_run = mocker.patch(
        "gorget.transform.run_step.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    ctx = make_ctx(
        tmp_path / "work",
        source_dir=source_dir,
        toolchain=[ToolchainEntry(name="go", version="1.22.0")],
    )
    state = make_state(tmp_path / "work")
    RunHandler().run(RunStep(command=["make"]), ctx, state)
    assert mock_run.call_args.args[0] == ["make"]


def test_run_missing_declared_output_raises_config_error(tmp_path, mocker):
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    mocker.patch(
        "gorget.transform.run_step.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    step = RunStep(command=["make"], outputs=["missing.txt"])
    with pytest.raises(GorgetConfigError, match="not found"):
        RunHandler().run(step, ctx, state)


def test_run_subprocess_failure_raises_transient_error(tmp_path, mocker):
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    mocker.patch(
        "gorget.transform.run_step.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="make failed"
        ),
    )
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    with pytest.raises(GorgetTransientError, match="make failed"):
        RunHandler().run(RunStep(command=["make"]), ctx, state)


def test_run_dry_run_does_nothing(tmp_path, mocker):
    mock_run = mocker.patch("gorget.transform.run_step.run")
    ctx = make_ctx(tmp_path / "work", source_dir=None, dry_run=True)
    state = make_state(tmp_path / "work")
    RunHandler().run(RunStep(command=["make"], outputs=["x.txt"]), ctx, state)
    mock_run.assert_not_called()
    assert state.artifacts == []
