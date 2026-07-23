import subprocess
import tarfile
from unittest.mock import Mock

from gorget.config.schema import (
    PipelineSpec,
    RunStep,
    StripTarballStep,
    ToolchainEntry,
    ToolchainSection,
    TransformSection,
    VendorModule,
    VendorStep,
)
from gorget.config.substitution import SubstitutionVars
from gorget.context import RunContext
from gorget.fetch.base import FetchedArtifact
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.stages.transform import TransformStage
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


def make_state(work_dir, artifacts=(), source_dir=None):
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    state = StageState(work_dir=work_dir, spec=Mock(), report=report, artifacts=list(artifacts))
    state.source_dir = source_dir
    return state


def test_skips_cleanly_when_no_transform_steps(tmp_path):
    ctx = make_run_ctx(tmp_path)
    state = make_state(tmp_path / "work")
    result = TransformStage().run(ctx, PipelineSpec(), state)
    assert result.status == "skipped"
    assert result.reason == "no transform steps declared"


def test_dispatches_strip_tarball_and_replaces_artifact(tmp_path):
    work_dir = tmp_path / "work"
    src = tmp_path / "_src"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "keep.txt").write_text("keep")
    (src / "pkg" / "drop.txt").write_text("drop")
    archive = tmp_path / "foo.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(src / "pkg", arcname="pkg")
    artifact = FetchedArtifact(
        path=archive, output_name="foo.tar.gz", source_description="x", checksum="orig"
    )

    ctx = make_run_ctx(tmp_path)
    state = make_state(work_dir, artifacts=[artifact])
    spec = PipelineSpec(
        transform=TransformSection(steps=[StripTarballStep(paths=["*/drop.txt"])])
    )

    result = TransformStage().run(ctx, spec, state)

    assert result.status == "success"
    assert state.artifacts[0].checksum != "orig"
    with tarfile.open(state.artifacts[0].path) as tar:
        names = tar.getnames()
    assert not any("drop.txt" in n for n in names)


def test_vendor_adapter_extends_artifacts_from_vendor_handler(tmp_path, mocker):
    # toolchain activation isn't implemented yet (gorget/toolchain.py); the
    # entries are threaded through but wrap_command() is currently a no-op.
    # (TransformStage.run() itself never calls verify_installed() -- that
    # only happens once, up front, in PipelineRunner.)
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    def fake_go_vendor(args, cwd=None):
        (cwd / "vendor").mkdir(parents=True, exist_ok=True)
        (cwd / "vendor" / "modules.txt").write_text("x v1")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    mock_run = mocker.patch("gorget.fetch.vendor.go.run", side_effect=fake_go_vendor)

    ctx = make_run_ctx(tmp_path)
    state = make_state(tmp_path / "work", source_dir=source_dir)
    spec = PipelineSpec(
        transform=TransformSection(
            steps=[VendorStep(ecosystem="go", modules=[VendorModule(path=".")])]
        ),
        toolchain=ToolchainSection(entries=[ToolchainEntry(name="go", version="1.22.0")]),
    )

    result = TransformStage().run(ctx, spec, state)

    assert result.status == "success"
    assert len(state.artifacts) == 1
    assert state.artifacts[0].output_name == "foo-vendor.tar.gz"
    mock_run.assert_called_once_with(["go", "mod", "vendor"], cwd=source_dir)


def test_syncs_source_dir_back_to_state_after_extraction(tmp_path, mocker):
    work_dir = tmp_path / "work"
    src = tmp_path / "_src"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "go.mod").write_text("module example\n")
    archive = tmp_path / "foo.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(src / "pkg", arcname="pkg")
    artifact = FetchedArtifact(
        path=archive, output_name="foo.tar.gz", source_description="x", checksum="c"
    )

    mocker.patch(
        "gorget.transform.run_step.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    ctx = make_run_ctx(tmp_path)
    state = make_state(work_dir, artifacts=[artifact], source_dir=None)
    spec = PipelineSpec(transform=TransformSection(steps=[RunStep(command=["true"])]))

    TransformStage().run(ctx, spec, state)

    assert state.source_dir is not None
    assert (state.source_dir / "pkg" / "go.mod").exists()
