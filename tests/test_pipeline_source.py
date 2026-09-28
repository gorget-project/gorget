import tarfile

import pytest

from gorget.exceptions import GorgetConfigError
from gorget.pipeline.artifact import build_input_artifact
from gorget.pipeline.source import SourceWorkspace
from gorget.util.archive import make_tar_gz, repack_tar_gz


def _members(tar_path):
    with tarfile.open(tar_path) as tar:
        return {member.name for member in tar.getmembers()}


def _read(tar_path, member):
    with tarfile.open(tar_path) as tar:
        extracted = tar.extractfile(member)
        assert extracted is not None
        return extracted.read().decode()


def test_commit_checkout_creates_derived_revision_and_preserves_input(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "go.mod").write_text("require x v1.0.0\n")
    input_path = tmp_path / "foo-1.0.0.tar.gz"
    make_tar_gz(checkout, input_path, arcname="foo-1.0.0", mtime=1700000000)
    input_bytes = input_path.read_bytes()
    parent = build_input_artifact(input_path, input_path.name, "repo", False)
    source = SourceWorkspace()
    source.attach_checkout(checkout, parent)

    (checkout / "go.mod").write_text("require x v2.0.0\n")
    source.mark_dirty()
    revision = source.commit(tmp_path / "work", dry_run=False)

    assert revision is not None
    assert revision.kind == "derived"
    assert revision.parents == (parent.ref(),)
    assert revision.path != parent.path
    assert input_path.read_bytes() == input_bytes
    assert _read(revision.path, "foo-1.0.0/go.mod") == "require x v2.0.0\n"
    assert all(name.startswith("foo-1.0.0") for name in _members(revision.path))
    assert source.artifact is revision
    assert source.dirty is False


def test_materialize_archive_and_commit_preserve_internal_layout(tmp_path):
    extracted = tmp_path / "original"
    (extracted / "foo-1.0.0").mkdir(parents=True)
    (extracted / "foo-1.0.0" / "package.json").write_text('{"v": 1}')
    input_path = tmp_path / "foo-1.0.0.tar.gz"
    repack_tar_gz(extracted, input_path)
    input_bytes = input_path.read_bytes()
    parent = build_input_artifact(input_path, input_path.name, "url", False)
    source = SourceWorkspace()

    path = source.materialize(tmp_path / "work", [parent])
    (path / "foo-1.0.0" / "package.json").write_text('{"v": 2}')
    source.mark_dirty()
    revision = source.commit(tmp_path / "work", dry_run=False)

    assert revision is not None
    assert input_path.read_bytes() == input_bytes
    assert _read(revision.path, "foo-1.0.0/package.json") == '{"v": 2}'


def test_materialize_requires_exactly_one_artifact(tmp_path):
    source = SourceWorkspace()

    with pytest.raises(GorgetConfigError, match="found 0"):
        source.materialize(tmp_path, [])


def test_commit_skips_clean_dry_run_and_unbacked_workspaces(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    input_path = tmp_path / "foo.tar.gz"
    make_tar_gz(checkout, input_path, arcname="foo", mtime=1700000000)
    parent = build_input_artifact(input_path, input_path.name, "repo", False)

    clean = SourceWorkspace()
    clean.attach_checkout(checkout, parent)
    assert clean.commit(tmp_path / "clean", dry_run=False) is None

    dry_run = SourceWorkspace()
    dry_run.attach_checkout(checkout, parent)
    dry_run.mark_dirty()
    assert dry_run.commit(tmp_path / "dry", dry_run=True) is None

    unbacked = SourceWorkspace()
    unbacked.attach_tree(checkout)
    unbacked.mark_dirty()
    assert unbacked.commit(tmp_path / "unbacked", dry_run=False) is None


def test_commit_is_deterministic(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "go.mod").write_text("require x v2.0.0\n")

    def run_once(name):
        input_path = tmp_path / name
        make_tar_gz(checkout, input_path, arcname="foo-1.0.0", mtime=1700000000)
        parent = build_input_artifact(input_path, "foo-1.0.0.tar.gz", "repo", False)
        source = SourceWorkspace()
        source.attach_checkout(checkout, parent)
        source.mark_dirty()
        revision = source.commit(tmp_path / f"work-{name}", dry_run=False)
        assert revision is not None
        return revision.path.read_bytes()

    assert run_once("a.tar.gz") == run_once("b.tar.gz")
