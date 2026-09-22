import subprocess
from pathlib import Path
from unittest.mock import Mock

from gorget.config.schema import GitStep, PipelineSpec
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

    assert state.source.path is not None
    assert (state.source.path / "README.md").exists()


def test_fetch_stage_leaves_source_dir_none_without_git_step(tmp_path):
    ctx = make_run_ctx(tmp_path)
    state = make_state(tmp_path / "work")
    FetchStage().run(ctx, PipelineSpec(), state)
    assert state.source.path is None
