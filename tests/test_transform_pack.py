import tarfile

import pytest

from gorget.config.schema import PackStep
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetConfigError
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.state import StageState
from gorget.transform.base import TransformContext
from gorget.transform.pack import PackHandler


def make_ctx(package_dir, work_dir, dry_run=False):
    return TransformContext(
        work_dir=work_dir,
        source_dir=None,
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
        toolchain=[],
        dry_run=dry_run,
        package_dir=package_dir,
    )


def make_state(work_dir):
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    return StageState(work_dir=work_dir, spec=None, report=report, artifacts=[])


def test_packs_explicit_files_preserving_relative_paths(tmp_path):
    package_dir = tmp_path / "package"
    (package_dir / "packaging").mkdir(parents=True)
    (package_dir / "Makefile").write_text("all:\n")
    (package_dir / "packaging" / "helper.sh").write_text("#!/bin/sh\n")

    ctx = make_ctx(package_dir, tmp_path / "work")
    state = make_state(tmp_path / "work")
    step = PackStep(files=["Makefile", "packaging/helper.sh"], output="scripts.tar.gz")

    PackHandler().run(step, ctx, state)

    assert len(state.artifacts) == 1
    artifact = state.artifacts[0]
    assert artifact.output_name == "scripts.tar.gz"
    assert artifact.checksum is not None
    with tarfile.open(artifact.path) as tar:
        names = set(tar.getnames())
    assert names == {"Makefile", "packaging/helper.sh"}


def test_missing_file_raises(tmp_path):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    ctx = make_ctx(package_dir, tmp_path / "work")
    state = make_state(tmp_path / "work")
    step = PackStep(files=["does-not-exist.txt"], output="scripts.tar.gz")

    with pytest.raises(GorgetConfigError, match="file not found"):
        PackHandler().run(step, ctx, state)


def test_dry_run_produces_no_artifact(tmp_path):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "Makefile").write_text("all:\n")
    ctx = make_ctx(package_dir, tmp_path / "work", dry_run=True)
    state = make_state(tmp_path / "work")
    step = PackStep(files=["Makefile"], output="scripts.tar.gz")

    PackHandler().run(step, ctx, state)

    assert state.artifacts == []


def test_two_runs_produce_byte_identical_archives(tmp_path):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "Makefile").write_text("all:\n")
    step = PackStep(files=["Makefile"], output="scripts.tar.gz")

    ctx1 = make_ctx(package_dir, tmp_path / "work1")
    state1 = make_state(tmp_path / "work1")
    PackHandler().run(step, ctx1, state1)

    ctx2 = make_ctx(package_dir, tmp_path / "work2")
    state2 = make_state(tmp_path / "work2")
    PackHandler().run(step, ctx2, state2)

    assert state1.artifacts[0].path.read_bytes() == state2.artifacts[0].path.read_bytes()
