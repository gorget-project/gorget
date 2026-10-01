import tarfile
from pathlib import Path

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


def test_source_changes_mark_only_real_changes_dirty(tmp_path):
    from gorget.pipeline.source import SourceChange

    (tmp_path / "lock").write_bytes(b"same")
    source = SourceWorkspace(path=tmp_path)
    source.apply_changes([SourceChange(Path("lock"), b"same"), SourceChange(Path("absent"), None)])
    assert not source.dirty
    source.apply_changes(
        [SourceChange(Path("lock"), None), SourceChange(Path("nested/lock"), b"new")]
    )
    assert source.dirty
    assert not (tmp_path / "lock").exists()
    assert (tmp_path / "nested/lock").read_bytes() == b"new"


def test_source_changes_validate_the_entire_set_before_writing(tmp_path):
    from gorget.pipeline.source import SourceChange

    source = SourceWorkspace(path=tmp_path)
    with pytest.raises(GorgetConfigError, match="escapes"):
        source.apply_changes(
            [SourceChange(Path("valid"), b"new"), SourceChange(Path("../outside"), b"bad")]
        )
    assert not (tmp_path / "valid").exists()
    assert not source.dirty


def test_source_switch_does_not_retain_files_from_the_previous_archive(tmp_path):
    artifacts = []
    for name in ("first", "second"):
        tree = tmp_path / name
        tree.mkdir()
        (tree / name).write_text(name)
        archive = tmp_path / f"{name}.tar.gz"
        repack_tar_gz(tree, archive)
        artifacts.append(build_input_artifact(archive, archive.name, "url", False))
    source = SourceWorkspace()
    source.select(tmp_path / "work", artifacts, "first.tar.gz")
    selected = source.select(tmp_path / "work", artifacts, "second.tar.gz")
    assert (selected / "second").exists()
    assert not (selected / "first").exists()


def test_failed_metadata_edit_rolls_back_all_changes(tmp_path):
    source = SourceWorkspace(path=tmp_path)
    (tmp_path / "lock").write_text("original")
    with pytest.raises(RuntimeError, match="failed resolution"):
        with source.edit_metadata([Path("lock")]) as tree:
            (tree / "lock").write_text("partial update")
            raise RuntimeError("failed resolution")
    assert (tmp_path / "lock").read_text() == "original"
    assert not source.dirty


def test_metadata_edit_preserves_relative_sibling_dependencies(tmp_path):
    source = SourceWorkspace(path=tmp_path)
    (tmp_path / "module").mkdir()
    (tmp_path / "sibling").mkdir()
    (tmp_path / "sibling/dependency").write_text("local dependency")
    with source.edit_metadata([Path("module/lock")]) as tree:
        assert (tree / "module/../sibling/dependency").read_text() == "local dependency"
        (tree / "module/lock").write_text("new metadata")
        (tree / "sibling/dependency").write_text("scratch mutation")
    assert (tmp_path / "module/lock").read_text() == "new metadata"
    assert (tmp_path / "sibling/dependency").read_text() == "local dependency"
    assert source.dirty
