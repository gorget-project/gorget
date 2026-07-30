import subprocess
import tarfile

import pytest

from gorget.config.schema import RunStep, ToolchainEntry
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.fetch.base import FetchedArtifact
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.state import StageState
from gorget.transform.base import TransformContext
from gorget.transform.run_step import RunHandler
from gorget.util.archive import make_tar_gz


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


def _make_tarball_artifact(tmp_path, output_name, file_contents):
    src_dir = tmp_path / f"_src_{output_name}"
    src_dir.mkdir()
    (src_dir / "marker.txt").write_text(file_contents)
    archive_path = tmp_path / f"_archive_{output_name}.tar.gz"
    make_tar_gz(src_dir, archive_path, arcname="extracted")
    return FetchedArtifact(
        path=archive_path, output_name=output_name, source_description="test", checksum=None
    )


def _make_plain_artifact(tmp_path, output_name, file_contents):
    path = tmp_path / f"_plain_{output_name}"
    path.write_text(file_contents)
    return FetchedArtifact(
        path=path, output_name=output_name, source_description="test", checksum=None
    )


def test_target_selects_named_artifact_among_multiple(tmp_path, mocker):
    tarball = _make_tarball_artifact(tmp_path, "tarball.tar.gz", "tarball contents")
    checksums = _make_plain_artifact(tmp_path, "SHASUMS256.txt", "checksums contents")

    mock_run = mocker.patch(
        "gorget.transform.run_step.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    ctx = make_ctx(tmp_path / "work", source_dir=None)
    state = make_state(tmp_path / "work")
    state.artifacts.extend([tarball, checksums])

    RunHandler().run(RunStep(command=["make"], target="tarball.tar.gz"), ctx, state)

    cwd = mock_run.call_args.kwargs["cwd"]
    assert (cwd / "extracted" / "marker.txt").read_text() == "tarball contents"


def test_omitting_target_with_multiple_artifacts_still_raises(tmp_path, mocker):
    mocker.patch(
        "gorget.transform.run_step.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    ctx = make_ctx(tmp_path / "work", source_dir=None)
    state = make_state(tmp_path / "work")
    state.artifacts.extend(
        [
            _make_tarball_artifact(tmp_path, "tarball.tar.gz", "a"),
            _make_plain_artifact(tmp_path, "SHASUMS256.txt", "b"),
        ]
    )
    with pytest.raises(GorgetConfigError, match="exactly one fetched artifact"):
        RunHandler().run(RunStep(command=["make"]), ctx, state)


def test_target_names_unknown_artifact_raises_config_error(tmp_path, mocker):
    mocker.patch(
        "gorget.transform.run_step.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    ctx = make_ctx(tmp_path / "work", source_dir=None)
    state = make_state(tmp_path / "work")
    with pytest.raises(GorgetConfigError, match="does-not-exist.tar.gz"):
        RunHandler().run(RunStep(command=["make"], target="does-not-exist.tar.gz"), ctx, state)


def test_discovered_outputs_happy_path_produces_named_artifacts(tmp_path, mocker):
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    def fake_run(args, cwd=None):
        (cwd / "b.zip").write_text("b-bytes")
        (cwd / "l.zip").write_text("l-bytes")
        (cwd / "manifest.tsv").write_text(
            "icu4c-78.2-data-bin-b.zip\tb.zip\nicu4c-78.2-data-bin-l.zip\tl.zip\n"
        )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    mocker.patch("gorget.transform.run_step.run", side_effect=fake_run)
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    step = RunStep(command=["discover.sh"], discovered_outputs="manifest.tsv")
    RunHandler().run(step, ctx, state)

    names_to_content = {a.output_name: a.path.read_text() for a in state.artifacts}
    assert names_to_content == {
        "icu4c-78.2-data-bin-b.zip": "b-bytes",
        "icu4c-78.2-data-bin-l.zip": "l-bytes",
    }


def test_discovered_outputs_missing_manifest_raises_config_error(tmp_path, mocker):
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    mocker.patch(
        "gorget.transform.run_step.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    step = RunStep(command=["discover.sh"], discovered_outputs="manifest.tsv")
    with pytest.raises(GorgetConfigError, match="manifest not found"):
        RunHandler().run(step, ctx, state)


def test_discovered_outputs_malformed_line_raises_config_error(tmp_path, mocker):
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    def fake_run(args, cwd=None):
        (cwd / "manifest.tsv").write_text("this line has no tab\n")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    mocker.patch("gorget.transform.run_step.run", side_effect=fake_run)
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    step = RunStep(command=["discover.sh"], discovered_outputs="manifest.tsv")
    with pytest.raises(GorgetConfigError, match="expected"):
        RunHandler().run(step, ctx, state)


def test_discovered_outputs_missing_referenced_file_raises_config_error(tmp_path, mocker):
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    def fake_run(args, cwd=None):
        (cwd / "manifest.tsv").write_text("some-name.zip\tmissing.zip\n")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    mocker.patch("gorget.transform.run_step.run", side_effect=fake_run)
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    step = RunStep(command=["discover.sh"], discovered_outputs="manifest.tsv")
    with pytest.raises(GorgetConfigError, match="discovered output not found"):
        RunHandler().run(step, ctx, state)


def test_artifacts_materializes_raw_bytes_into_cwd_before_command_runs(tmp_path, mocker):
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    raw_file = tmp_path / "raw-tarball.tar.gz"
    raw_file.write_bytes(b"pristine upstream bytes")
    artifact = FetchedArtifact(
        path=raw_file, output_name="tarball.tar.gz", source_description="test", checksum=None
    )

    seen = {}

    def fake_run(args, cwd=None):
        seen["bytes"] = (cwd / "tarball.tar.gz").read_bytes()
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    mocker.patch("gorget.transform.run_step.run", side_effect=fake_run)
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    state.artifacts.append(artifact)

    step = RunStep(command=["verify.sh"], artifacts=["tarball.tar.gz"])
    RunHandler().run(step, ctx, state)

    assert seen["bytes"] == b"pristine upstream bytes"


def test_artifacts_names_unknown_artifact_raises_config_error(tmp_path, mocker):
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    mocker.patch(
        "gorget.transform.run_step.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    ctx = make_ctx(tmp_path / "work", source_dir=source_dir)
    state = make_state(tmp_path / "work")
    step = RunStep(command=["verify.sh"], artifacts=["does-not-exist.tar.gz"])
    with pytest.raises(GorgetConfigError, match="does-not-exist.tar.gz"):
        RunHandler().run(step, ctx, state)
