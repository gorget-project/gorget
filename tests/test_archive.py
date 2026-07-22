import tarfile

from gorget.util.archive import make_tar_gz


def test_make_tar_gz_includes_files_under_arcname(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello")
    (src / "sub").mkdir()
    (src / "sub" / "b.txt").write_text("world")

    dest = tmp_path / "out" / "archive.tar.gz"
    make_tar_gz(src, dest, arcname="pkg-1.0.0")

    with tarfile.open(dest) as tar:
        names = set(tar.getnames())
    assert "pkg-1.0.0" in names
    assert "pkg-1.0.0/a.txt" in names
    assert "pkg-1.0.0/sub/b.txt" in names


def test_make_tar_gz_excludes_git_directory(tmp_path):
    src = tmp_path / "src"
    (src / ".git").mkdir(parents=True)
    (src / ".git" / "config").write_text("")
    (src / "file.txt").write_text("keep me")

    dest = tmp_path / "archive.tar.gz"
    make_tar_gz(src, dest, arcname="pkg")

    with tarfile.open(dest) as tar:
        names = tar.getnames()
    assert "pkg/file.txt" in names
    assert not any(".git" in name for name in names)
