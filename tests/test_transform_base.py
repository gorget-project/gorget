import tarfile

import pytest

from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import FetchedArtifact
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.state import StageState
from gorget.transform.base import TransformContext, ensure_source_dir


def make_ctx(work_dir, source_dir=None):
    return TransformContext(
        work_dir=work_dir,
        source_dir=source_dir,
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
        toolchain=[],
        dry_run=False,
        package_dir=work_dir,
    )


def make_state(work_dir, artifacts=()):
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    return StageState(work_dir=work_dir, spec=None, report=report, artifacts=list(artifacts))


def make_artifact(base_dir, name, checksum):
    return FetchedArtifact(
        path=base_dir / name, output_name=name, source_description=name, checksum=checksum
    )


def test_returns_existing_source_dir_without_extracting(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    ctx = make_ctx(tmp_path, source_dir=existing)
    state = make_state(tmp_path)
    assert ensure_source_dir(ctx, state) == existing


def test_extracts_sole_artifact_when_source_dir_unset(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_text("hello")
    archive = tmp_path / "foo-1.2.3.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(src, arcname="foo-1.2.3")

    artifact = FetchedArtifact(
        path=archive, output_name="foo-1.2.3.tar.gz", source_description="x", checksum="abc"
    )
    ctx = make_ctx(tmp_path / "work")
    state = make_state(tmp_path / "work", artifacts=[artifact])

    result = ensure_source_dir(ctx, state)

    assert (result / "foo-1.2.3" / "file.txt").read_text() == "hello"
    assert ctx.source_dir == result


def test_raises_when_zero_artifacts_and_no_source_dir(tmp_path):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    with pytest.raises(GorgetConfigError, match="found 0"):
        ensure_source_dir(ctx, state)


def test_raises_when_multiple_artifacts_and_no_source_dir(tmp_path):
    artifacts = [make_artifact(tmp_path, "a.tar.gz", "1"), make_artifact(tmp_path, "b.tar.gz", "2")]
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, artifacts=artifacts)
    with pytest.raises(GorgetConfigError, match="found 2"):
        ensure_source_dir(ctx, state)
