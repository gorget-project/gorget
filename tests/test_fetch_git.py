import subprocess
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from gorget.config.schema import GitStep
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetTransientError
from gorget.fetch.base import FetchContext
from gorget.fetch.git import GitHandler


def make_ctx(work_dir, dry_run=False):
    return FetchContext(
        work_dir=work_dir,
        package_dir=work_dir,
        spec=Mock(),
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
        dry_run=dry_run,
    )


def _ok(stdout=""):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _fail(stderr="boom"):
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


def _fake_clone(args, cwd=None):
    """Simulate `git clone ... <dest>` by creating a fake checkout on disk."""
    if len(args) >= 2 and args[1] == "clone":
        dest = Path(args[-1])
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "README.md").write_text("hello\n")
        git_dir = dest / ".git"
        git_dir.mkdir(exist_ok=True)
        (git_dir / "config").write_text("")
    return _ok()


def test_shallow_clone_of_tag_uses_branch_and_depth(tmp_path, mocker):
    mock_run = mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    step = GitStep(repo="https://example.com/repo.git", ref="v1.2.3", shallow=True)
    artifacts = GitHandler().run(step, make_ctx(tmp_path))

    clone_args = mock_run.call_args_list[0].args[0]
    assert clone_args[:2] == ["git", "clone"]
    assert "--branch" in clone_args and "v1.2.3" in clone_args
    assert "--depth" in clone_args and "1" in clone_args
    assert mock_run.call_count == 1  # branch clone alone checks out the ref, no separate checkout

    assert artifacts[0].output_name == "foo-v1.2.3.tar.gz"
    assert artifacts[0].checksum is not None
    assert (tmp_path / "foo-v1.2.3.tar.gz").exists()


def test_shallow_clone_of_sha_ref_falls_back_to_partial_clone(tmp_path, mocker):
    mock_run = mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    step = GitStep(repo="https://example.com/repo.git", ref="abc1234", shallow=True)
    GitHandler().run(step, make_ctx(tmp_path))

    clone_args = mock_run.call_args_list[0].args[0]
    assert "--filter=blob:none" in clone_args
    checkout_args = mock_run.call_args_list[1].args[0]
    assert checkout_args == ["git", "checkout", "abc1234"]


def test_full_clone_performs_explicit_checkout(tmp_path, mocker):
    mock_run = mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    step = GitStep(repo="https://example.com/repo.git", ref="main", shallow=False)
    GitHandler().run(step, make_ctx(tmp_path))

    clone_args = mock_run.call_args_list[0].args[0]
    assert clone_args == ["git", "clone", "https://example.com/repo.git", clone_args[-1]]
    assert "--depth" not in clone_args
    assert "--filter=blob:none" not in clone_args
    checkout_args = mock_run.call_args_list[1].args[0]
    assert checkout_args == ["git", "checkout", "main"]


def test_archive_excludes_dot_git_directory(tmp_path, mocker):
    mocker.patch("gorget.fetch.git.run", side_effect=_fake_clone)
    step = GitStep(repo="https://example.com/repo.git", ref="v1.0.0", shallow=True)
    artifacts = GitHandler().run(step, make_ctx(tmp_path))

    with tarfile.open(artifacts[0].path) as tar:
        names = tar.getnames()
    assert any(name.endswith("README.md") for name in names)
    assert not any(".git" in Path(name).parts for name in names)


def test_subdir_archives_only_that_subdirectory(tmp_path, mocker):
    def _clone_with_subdir(args, cwd=None):
        _fake_clone(args, cwd)
        if args[1] == "clone":
            dest = Path(args[-1])
            (dest / "sub").mkdir(exist_ok=True)
            (dest / "sub" / "inner.txt").write_text("x")
        return _ok()

    mocker.patch("gorget.fetch.git.run", side_effect=_clone_with_subdir)
    step = GitStep(repo="https://example.com/repo.git", ref="v1.0.0", shallow=True, subdir="sub")
    artifacts = GitHandler().run(step, make_ctx(tmp_path))

    with tarfile.open(artifacts[0].path) as tar:
        names = tar.getnames()
    assert any(name.endswith("inner.txt") for name in names)
    assert not any(name.endswith("README.md") for name in names)


def test_clone_failure_raises_transient_error(tmp_path, mocker):
    mocker.patch("gorget.fetch.git.run", return_value=_fail("repository not found"))
    step = GitStep(repo="https://example.com/repo.git", ref="v1.0.0", shallow=True)
    with pytest.raises(GorgetTransientError, match="repository not found"):
        GitHandler().run(step, make_ctx(tmp_path))


def test_checkout_failure_raises_transient_error(tmp_path, mocker):
    def _run(args, cwd=None):
        if args[1] == "clone":
            return _fake_clone(args, cwd)
        return _fail("unknown revision")

    mocker.patch("gorget.fetch.git.run", side_effect=_run)
    step = GitStep(repo="https://example.com/repo.git", ref="deadbeef", shallow=False)
    with pytest.raises(GorgetTransientError, match="unknown revision"):
        GitHandler().run(step, make_ctx(tmp_path))


def test_dry_run_skips_clone_entirely(tmp_path, mocker):
    mock_run = mocker.patch("gorget.fetch.git.run")
    step = GitStep(repo="https://example.com/repo.git", ref="v1.0.0", shallow=True)
    artifacts = GitHandler().run(step, make_ctx(tmp_path, dry_run=True))
    mock_run.assert_not_called()
    assert artifacts[0].checksum is None
    assert not artifacts[0].path.exists()
