import pytest

from gorget.config.schema import PipelineSpec, PostRunStep, PostSection
from gorget.config.substitution import SubstitutionVars
from gorget.context import RunContext
from gorget.exceptions import GorgetTransientError
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.stages.post import PostStage
from gorget.pipeline.state import StageState


def make_ctx(package_dir, dry_run=False):
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
    return StageState(work_dir=work_dir, spec=None, report=report)


def test_no_post_steps_skips(tmp_path):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    result = PostStage().run(ctx, PipelineSpec(), state)
    assert result.status == "skipped"
    assert result.reason == "no post steps declared"


def test_dry_run_skips_even_with_steps_declared(tmp_path):
    ctx = make_ctx(tmp_path, dry_run=True)
    state = make_state(tmp_path)
    spec = PipelineSpec(
        post=PostSection(steps=[PostRunStep(command=["touch", "should-not-exist"])])
    )
    result = PostStage().run(ctx, spec, state)
    assert result.status == "skipped"
    assert result.reason == "dry-run"
    assert not (tmp_path / "should-not-exist").exists()


def test_run_step_executes_with_package_dir_as_cwd(tmp_path):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    spec = PipelineSpec(
        post=PostSection(steps=[PostRunStep(command=["sh", "-c", "echo hi > post-output.txt"])])
    )
    result = PostStage().run(ctx, spec, state)
    assert result.status == "success"
    assert (tmp_path / "post-output.txt").read_text() == "hi\n"


def test_multiple_steps_run_in_declared_order(tmp_path):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    spec = PipelineSpec(
        post=PostSection(
            steps=[
                PostRunStep(command=["sh", "-c", "echo one >> order.txt"]),
                PostRunStep(command=["sh", "-c", "echo two >> order.txt"]),
            ]
        )
    )
    PostStage().run(ctx, spec, state)
    assert (tmp_path / "order.txt").read_text() == "one\ntwo\n"


def test_failing_step_raises_transient_error(tmp_path):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    spec = PipelineSpec(
        post=PostSection(steps=[PostRunStep(command=["sh", "-c", "echo boom >&2; exit 1"])])
    )
    with pytest.raises(GorgetTransientError, match="boom"):
        PostStage().run(ctx, spec, state)
