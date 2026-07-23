import tarfile

import pytest

from gorget.config.schema import StripTarballStep
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import FetchedArtifact
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.state import StageState
from gorget.transform.base import TransformContext
from gorget.transform.strip_tarball import StripTarballHandler


def make_ctx(work_dir, dry_run=False):
    return TransformContext(
        work_dir=work_dir,
        source_dir=None,
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
        toolchain=[],
        dry_run=dry_run,
    )


def make_state(work_dir, artifacts):
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    return StageState(work_dir=work_dir, spec=None, report=report, artifacts=list(artifacts))


def make_artifact(path, name, checksum):
    return FetchedArtifact(path=path, output_name=name, source_description=name, checksum=checksum)


def make_two_artifacts(base_dir):
    return [
        make_artifact(base_dir / "a.tar.gz", "a.tar.gz", "1"),
        make_artifact(base_dir / "b.tar.gz", "b.tar.gz", "2"),
    ]


def _make_tarball(path, top_dir_name, files):
    src = path.parent / f"_src_{top_dir_name}"
    for rel, content in files.items():
        full = src / top_dir_name / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    with tarfile.open(path, "w:gz") as tar:
        tar.add(src / top_dir_name, arcname=top_dir_name)


def test_strips_matched_path_from_sole_artifact(tmp_path):
    archive = tmp_path / "foo-1.2.3.tar.gz"
    _make_tarball(
        archive,
        "foo-1.2.3",
        {"keep.txt": "keep", "deps/bundled-openssl/x.c": "bundled"},
    )
    artifact = make_artifact(archive, "foo-1.2.3.tar.gz", "abc")
    ctx = make_ctx(tmp_path / "work")
    state = make_state(tmp_path / "work", [artifact])

    step = StripTarballStep(paths=["*/deps/bundled-openssl"])
    StripTarballHandler().run(step, ctx, state)

    new_artifact = state.artifacts[0]
    assert new_artifact.output_name == "foo-1.2.3.tar.gz"
    assert new_artifact.checksum != "abc"
    with tarfile.open(new_artifact.path) as tar:
        names = tar.getnames()
    assert "foo-1.2.3/keep.txt" in names
    assert not any("bundled-openssl" in name for name in names)


def test_explicit_target_selects_among_multiple_artifacts(tmp_path):
    archive_a = tmp_path / "a.tar.gz"
    archive_b = tmp_path / "b.tar.gz"
    _make_tarball(archive_a, "a", {"keep.txt": "a"})
    _make_tarball(archive_b, "b", {"strip-me/file.txt": "b", "keep.txt": "b"})
    artifacts = [
        make_artifact(archive_a, "a.tar.gz", "1"),
        make_artifact(archive_b, "b.tar.gz", "2"),
    ]
    ctx = make_ctx(tmp_path / "work")
    state = make_state(tmp_path / "work", artifacts)

    step = StripTarballStep(target="b.tar.gz", paths=["*/strip-me"])
    StripTarballHandler().run(step, ctx, state)

    assert state.artifacts[0].output_name == "a.tar.gz"
    assert state.artifacts[0].checksum == "1"  # untouched
    with tarfile.open(state.artifacts[1].path) as tar:
        names = tar.getnames()
    assert "b/keep.txt" in names
    assert not any("strip-me" in name for name in names)


def test_ambiguous_target_raises_when_no_target_given(tmp_path):
    artifacts = make_two_artifacts(tmp_path)
    ctx = make_ctx(tmp_path / "work")
    state = make_state(tmp_path / "work", artifacts)
    with pytest.raises(GorgetConfigError, match="requires 'target'"):
        StripTarballHandler().run(StripTarballStep(paths=["x"]), ctx, state)


def test_target_not_found_raises(tmp_path):
    artifact = make_artifact(tmp_path / "a.tar.gz", "a.tar.gz", "1")
    ctx = make_ctx(tmp_path / "work")
    state = make_state(tmp_path / "work", [artifact])
    step = StripTarballStep(target="missing.tar.gz", paths=["x"])
    with pytest.raises(GorgetConfigError, match="not found among fetched artifacts"):
        StripTarballHandler().run(step, ctx, state)


def test_pattern_matching_nothing_raises(tmp_path):
    archive = tmp_path / "foo.tar.gz"
    _make_tarball(archive, "foo", {"keep.txt": "keep"})
    artifact = make_artifact(archive, "foo.tar.gz", "abc")
    ctx = make_ctx(tmp_path / "work")
    state = make_state(tmp_path / "work", [artifact])
    step = StripTarballStep(paths=["*/does-not-exist"])
    with pytest.raises(GorgetConfigError, match="matched nothing"):
        StripTarballHandler().run(step, ctx, state)


def test_dry_run_skips_repack_but_validates_target(tmp_path):
    archive = tmp_path / "foo.tar.gz"
    _make_tarball(archive, "foo", {"keep.txt": "keep"})
    artifact = make_artifact(archive, "foo.tar.gz", "abc")
    ctx = make_ctx(tmp_path / "work", dry_run=True)
    state = make_state(tmp_path / "work", [artifact])
    step = StripTarballStep(paths=["*/does-not-exist"])  # would raise if actually run
    StripTarballHandler().run(step, ctx, state)
    assert state.artifacts[0].checksum == "abc"  # untouched


def test_dry_run_still_validates_ambiguous_target(tmp_path):
    artifacts = make_two_artifacts(tmp_path)
    ctx = make_ctx(tmp_path / "work", dry_run=True)
    state = make_state(tmp_path / "work", artifacts)
    with pytest.raises(GorgetConfigError, match="requires 'target'"):
        StripTarballHandler().run(StripTarballStep(paths=["x"]), ctx, state)
