import subprocess
from unittest.mock import Mock

import pytest
from test_transform_vendor_handler import make_ctx

from gorget.config.loader import parse_pipeline_spec
from gorget.config.schema import VendorOutput, VendorStep
from gorget.exceptions import GorgetConfigError
from gorget.transform.vendor import VendorHandler


def test_vendor_outputs_parse():
    spec = parse_pipeline_spec({"transform": [{
        "type": "vendor", "ecosystem": "gradle",
        "outputs": [{"path": "core/build/kafka_*.tgz", "name": "runtime.tgz"}],
    }]})
    assert spec.transform.steps[0].outputs == [
        VendorOutput(path="core/build/kafka_*.tgz", name="runtime.tgz")
    ]


@pytest.mark.parametrize("raw", [[{}], ["runtime.tgz"], None])
def test_vendor_outputs_parse_rejects_invalid_entries(raw):
    with pytest.raises(GorgetConfigError, match="Invalid vendor outputs"):
        parse_pipeline_spec({"transform": [{
            "type": "vendor", "ecosystem": "gradle", "outputs": raw,
        }]})


def test_gradle_output_is_retained_without_a_second_build(tmp_path, mocker):
    source = tmp_path / "source"
    source.mkdir()
    (source / "build.gradle").write_text("// upstream")
    mocker.patch("gorget.transform.vendor.commit_timestamp", return_value=1700000000)

    def build(_command, *, cwd, env):
        cache = cwd / "vendor"
        cache.mkdir()
        (cache / "dependency.jar").write_bytes(b"dependency")
        runtime = cwd / "core/build/distributions"
        runtime.mkdir(parents=True)
        (runtime / "kafka_2.13-1.2.3.tgz").write_bytes(b"runtime archive")
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    command = mocker.patch("gorget.transform.vendor.gradle.run", side_effect=build)
    step = VendorStep(ecosystem="gradle", task="releaseTarGz", outputs=[
        VendorOutput(path="core/build/distributions/kafka_*-1.2.3.tgz", name="runtime.tgz")
    ])
    result = VendorHandler().run(step, make_ctx(tmp_path, source_dir=source))
    command.assert_called_once()
    assert [a.output_name for a in result.artifacts] == ["foo-vendor.tar.gz", "runtime.tgz"]
    assert result.artifacts[1].path.read_bytes() == b"runtime archive"
    assert result.artifacts[1].checksum
    assert result.source_changes == ()
    assert list(source.iterdir()) == [source / "build.gradle"]


def test_vendor_output_dry_run_plans_without_building(tmp_path, mocker):
    command = mocker.patch("gorget.transform.vendor.gradle.run")
    result = VendorHandler().run(VendorStep(ecosystem="gradle", outputs=[
        VendorOutput(path="build/*.tgz", name="runtime.tgz")
    ]), make_ctx(tmp_path, dry_run=True))
    command.assert_not_called()
    assert result.artifacts[1].output_name == "runtime.tgz"
    assert result.artifacts[1].checksum is None
    assert not result.artifacts[1].path.exists()


@pytest.mark.parametrize("path,name", [
    ("../output", "runtime.tgz"), ("/tmp/output", "runtime.tgz"),
    ("", "runtime.tgz"), ("build/*.tgz", "../runtime.tgz"),
    ("build/*.tgz", "foo-vendor.tar.gz"), (123, "runtime.tgz"), ("build/*.tgz", None),
])
def test_vendor_output_rejects_invalid_paths_and_names(tmp_path, path, name):
    with pytest.raises(GorgetConfigError):
        VendorHandler().run(VendorStep(ecosystem="gradle", outputs=[
            VendorOutput(path=path, name=name)
        ]), make_ctx(tmp_path, dry_run=True))


def test_vendor_output_rejects_other_ecosystems(tmp_path):
    with pytest.raises(GorgetConfigError, match="only supported.*gradle"):
        VendorHandler().run(VendorStep(ecosystem="go", outputs=[
            VendorOutput(path="build/*.tgz", name="runtime.tgz")
        ]), make_ctx(tmp_path, dry_run=True))


def test_vendor_output_rejects_duplicate_names(tmp_path):
    with pytest.raises(GorgetConfigError, match="Duplicate"):
        VendorHandler().run(VendorStep(ecosystem="gradle", outputs=[
            VendorOutput(path="a", name="runtime.tgz"),
            VendorOutput(path="b", name="runtime.tgz"),
        ]), make_ctx(tmp_path, dry_run=True))


@pytest.mark.parametrize("kind", ["missing", "ambiguous", "directory", "escape"])
def test_vendor_output_requires_one_file_inside_workspace(tmp_path, mocker, kind):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.tgz"
    outside.write_bytes(b"outside")
    mocker.patch("gorget.transform.vendor.commit_timestamp", return_value=1700000000)

    def build(module_dir, *_args, **_kwargs):
        cache = module_dir / "vendor"
        cache.mkdir()
        if kind == "ambiguous":
            (module_dir / "a.tgz").touch()
            (module_dir / "b.tgz").touch()
        elif kind == "directory":
            (module_dir / "a.tgz").mkdir()
        elif kind == "escape":
            (module_dir / "a.tgz").symlink_to(outside)
        return cache

    mocker.patch("gorget.transform.vendor._ECOSYSTEMS", {"gradle": Mock(
        vendor=Mock(side_effect=build), source_files=Mock(return_value=()),
        archive_root_files=Mock(return_value=[]),
    )})
    with pytest.raises(GorgetConfigError, match="exactly one|must be a file|escapes"):
        VendorHandler().run(VendorStep(ecosystem="gradle", outputs=[
            VendorOutput(path="*.tgz", name="runtime.tgz")
        ]), make_ctx(tmp_path, source_dir=source))


def test_retained_output_reaches_post_without_publication(tmp_path, mocker):
    from test_pipeline_stage_transform import make_run_ctx, make_state

    from gorget.config.schema import (
        PipelineSpec,
        PostRunStep,
        PostSection,
        PublishSection,
        TransformSection,
    )
    from gorget.pipeline.stages.emit import EmitStage
    from gorget.pipeline.stages.post import PostStage
    from gorget.pipeline.stages.transform import TransformStage

    package = tmp_path / "package"
    package.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    (source / "build.gradle").write_text("// upstream")
    wrapper = source / "gradlew"
    wrapper.write_text(
        '#!/bin/sh\nset -eu\nmkdir -p "$GRADLE_USER_HOME" build\n'
        'echo cache > "$GRADLE_USER_HOME/dependency"\n'
        'echo runtime > build/runtime.tgz\n'
    )
    wrapper.chmod(0o755)
    mocker.patch("gorget.transform.vendor.commit_timestamp", return_value=1700000000)
    spec = PipelineSpec(
        transform=TransformSection(steps=[VendorStep(ecosystem="gradle", outputs=[
            VendorOutput(path="build/runtime.tgz", name="runtime.tgz")
        ])]),
        post=PostSection(steps=[PostRunStep(
            artifacts=["runtime.tgz"], command=["sh", "-c", "cat runtime.tgz > provides.inc"],
        )]),
        publish=PublishSection(files=["foo-vendor.tar.gz"]),
    )
    ctx = make_run_ctx(package)
    state = make_state(tmp_path / "work", source_dir=source)
    TransformStage().run(ctx, spec, state)
    PostStage().run(ctx, spec, state)
    EmitStage().run(ctx, spec, state)
    assert (package / "provides.inc").read_text() == "runtime\n"
    assert not (ctx.output_dir / "runtime.tgz").exists()
    assert (ctx.output_dir / "foo-vendor.tar.gz").is_file()
    assert "runtime.tgz" not in (ctx.output_dir / "sources").read_text()
    assert not (source / "build").exists()


def test_vendor_worker_limit_parses():
    spec = parse_pipeline_spec({"transform": [{
        "type": "vendor", "ecosystem": "gradle", "max-workers": 1,
    }]})
    assert spec.transform.steps[0].max_workers == 1


def test_vendor_worker_limit_requires_gradle(tmp_path):
    with pytest.raises(GorgetConfigError, match="only supported.*gradle"):
        VendorHandler().run(
            VendorStep(ecosystem="go", max_workers=1), make_ctx(tmp_path, dry_run=True)
        )


@pytest.mark.parametrize("workers", [0, -1, True, "2", 1.5])
def test_vendor_worker_limit_validates_dry_runs(tmp_path, workers):
    with pytest.raises(GorgetConfigError, match="positive integer"):
        VendorHandler().run(
            VendorStep(ecosystem="gradle", max_workers=workers), make_ctx(tmp_path, dry_run=True)
        )
