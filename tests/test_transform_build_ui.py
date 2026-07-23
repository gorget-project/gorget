import subprocess
import tarfile

import pytest

from gorget.config.schema import BuildUiStep, ToolchainEntry
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.state import StageState
from gorget.transform.base import TransformContext
from gorget.transform.build_ui import BuildUiHandler


def make_ctx(work_dir, source_dir, toolchain=(), dry_run=False):
    return TransformContext(
        work_dir=work_dir,
        source_dir=source_dir,
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
        toolchain=list(toolchain),
        dry_run=dry_run,
    )


def make_state(work_dir):
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    return StageState(work_dir=work_dir, spec=None, report=report)


def _fake_build_writes_dist(args, cwd=None):
    (cwd / "dist").mkdir(parents=True, exist_ok=True)
    (cwd / "dist" / "bundle.js").write_text("built")
    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")


def test_build_ui_runs_script_and_archives_output(tmp_path, mocker):
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    mock_run = mocker.patch("gorget.transform.build_ui.run", side_effect=_fake_build_writes_dist)

    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    BuildUiHandler().run(BuildUiStep(), ctx, state)

    assert mock_run.call_args.args[0] == ["npm", "run", "build"]
    assert mock_run.call_args.kwargs["cwd"] == source_dir
    artifact = state.artifacts[0]
    assert artifact.output_name == "foo-ui-assets.tar.gz"
    with tarfile.open(artifact.path) as tar:
        names = tar.getnames()
    assert "bundle.js" in names


def test_build_ui_custom_path_ecosystem_script_output_dir(tmp_path, mocker):
    source_dir = tmp_path / "src"
    (source_dir / "ui").mkdir(parents=True)

    def fake_run(args, cwd=None):
        (cwd / "build").mkdir(parents=True, exist_ok=True)
        (cwd / "build" / "index.html").write_text("<html></html>")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    mock_run = mocker.patch("gorget.transform.build_ui.run", side_effect=fake_run)
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    step = BuildUiStep(ecosystem="yarn", script="compile", path="ui", output_dir="build")
    BuildUiHandler().run(step, ctx, state)

    assert mock_run.call_args.args[0] == ["yarn", "run", "compile"]
    assert mock_run.call_args.kwargs["cwd"] == source_dir / "ui"


def test_build_ui_custom_archive_name(tmp_path, mocker):
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    mocker.patch("gorget.transform.build_ui.run", side_effect=_fake_build_writes_dist)
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    BuildUiHandler().run(BuildUiStep(archive_name="assets.tar.gz"), ctx, state)
    assert state.artifacts[0].output_name == "assets.tar.gz"


def test_build_ui_toolchain_param_does_not_change_command(tmp_path, mocker):
    # toolchain activation isn't implemented yet (gorget/toolchain.py); the
    # param is accepted but wrap_command() is currently a no-op passthrough.
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    mock_run = mocker.patch("gorget.transform.build_ui.run", side_effect=_fake_build_writes_dist)
    toolchain = [ToolchainEntry(name="node", version="20.11.0")]
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir, toolchain=toolchain)
    state = make_state(tmp_path / "work")
    BuildUiHandler().run(BuildUiStep(), ctx, state)
    assert mock_run.call_args.args[0] == ["npm", "run", "build"]


def test_build_ui_missing_output_dir_raises_config_error(tmp_path, mocker):
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    def fake_run(args, cwd=None):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    mocker.patch("gorget.transform.build_ui.run", side_effect=fake_run)
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    with pytest.raises(GorgetConfigError, match="output directory not found"):
        BuildUiHandler().run(BuildUiStep(), ctx, state)


def test_build_ui_subprocess_failure_raises_transient_error(tmp_path, mocker):
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    mocker.patch(
        "gorget.transform.build_ui.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="build broke"
        ),
    )
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    with pytest.raises(GorgetTransientError, match="build broke"):
        BuildUiHandler().run(BuildUiStep(), ctx, state)


def test_build_ui_dry_run_appends_placeholder_and_skips_subprocess(tmp_path, mocker):
    mock_run = mocker.patch("gorget.transform.build_ui.run")
    ctx = make_ctx(tmp_path / "work", source_dir=None, dry_run=True)
    state = make_state(tmp_path / "work")
    BuildUiHandler().run(BuildUiStep(), ctx, state)
    mock_run.assert_not_called()
    assert state.artifacts[0].checksum is None
    assert state.artifacts[0].output_name == "foo-ui-assets.tar.gz"
