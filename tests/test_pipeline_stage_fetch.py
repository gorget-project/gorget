import subprocess
from pathlib import Path
from unittest.mock import Mock

from gorget.config.schema import GitStep, PipelineSpec, ToolchainEntry, ToolchainSection, VendorStep
from gorget.config.substitution import SubstitutionVars
from gorget.context import RunContext
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.stages.fetch import FetchStage
from gorget.pipeline.state import StageState


def make_run_ctx(package_dir, dry_run=False):
    return RunContext(
        package_dir=package_dir,
        pipeline_file=package_dir / "pipeline.yaml",
        gpg_keys_dir=package_dir / "gpg-keys",
        output_dir=package_dir / "output",
        dry_run=dry_run,
        spec_path=package_dir / "foo.spec",
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
    )


def make_state(work_dir):
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    return StageState(work_dir=work_dir, spec=Mock(), report=report)


def _fake_clone(args, cwd=None):
    if len(args) >= 2 and args[1] == "clone":
        dest = Path(args[-1])
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "README.md").write_text("hello\n")
    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")


def test_fetch_stage_syncs_source_dir_into_state(tmp_path, mocker):
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    ctx = make_run_ctx(tmp_path)
    state = make_state(tmp_path / "work")
    spec = PipelineSpec(
        fetch=[GitStep(repo="https://example.com/repo.git", ref="v1.2.3", shallow=True)]
    )

    FetchStage().run(ctx, spec, state)

    assert state.source_dir is not None
    assert (state.source_dir / "README.md").exists()


def test_fetch_stage_leaves_source_dir_none_without_git_step(tmp_path):
    ctx = make_run_ctx(tmp_path)
    state = make_state(tmp_path / "work")
    FetchStage().run(ctx, PipelineSpec(), state)
    assert state.source_dir is None


def test_fetch_stage_toolchain_param_does_not_change_vendor_command(tmp_path, mocker):
    # toolchain activation isn't implemented yet (gorget/toolchain.py); the
    # entries are threaded through but wrap_command() is currently a no-op.
    # (FetchStage.run() itself never calls verify_installed() -- that only
    # happens once, up front, in PipelineRunner.)
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    mocker.patch("gorget.fetch.vendor.commit_timestamp", return_value=1700000000)

    def _fake_go_vendor(args, cwd=None, env=None):
        (Path(cwd) / "vendor").mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    mock_go_run = mocker.patch("gorget.fetch.vendor.go.run", side_effect=_fake_go_vendor)

    ctx = make_run_ctx(tmp_path)
    state = make_state(tmp_path / "work")
    spec = PipelineSpec(
        fetch=[
            GitStep(repo="https://example.com/repo.git", ref="v1.2.3"),
            VendorStep(ecosystem="go"),
        ],
        toolchain=ToolchainSection(entries=[ToolchainEntry(name="go", version="1.22.0")]),
    )

    FetchStage().run(ctx, spec, state)

    # `go mod tidy` runs before `go mod vendor` by default (matching
    # go-vendor-tools' own default), even with no go-vendor-tools.toml present.
    assert mock_go_run.call_args_list == [
        mocker.call(["go", "mod", "tidy"], cwd=state.source_dir, env={"GOWORK": "off"}),
        mocker.call(["go", "mod", "vendor"], cwd=state.source_dir, env={"GOWORK": "off"}),
    ]
