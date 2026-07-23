import shutil
import tarfile

from gorget.util.archive import extract_tar_gz, make_tar_gz, repack_tar_gz


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


def test_extract_tar_gz_round_trips_make_tar_gz(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello")
    (src / "sub").mkdir()
    (src / "sub" / "b.txt").write_text("world")

    archive = tmp_path / "archive.tar.gz"
    make_tar_gz(src, archive, arcname="pkg-1.0.0")

    dest_dir = tmp_path / "extracted"
    extract_tar_gz(archive, dest_dir)

    assert (dest_dir / "pkg-1.0.0" / "a.txt").read_text() == "hello"
    assert (dest_dir / "pkg-1.0.0" / "sub" / "b.txt").read_text() == "world"


def test_repack_tar_gz_preserves_top_level_layout(tmp_path):
    extracted = tmp_path / "extracted"
    (extracted / "pkg-1.0.0" / "sub").mkdir(parents=True)
    (extracted / "pkg-1.0.0" / "a.txt").write_text("hello")
    (extracted / "pkg-1.0.0" / "sub" / "b.txt").write_text("world")

    dest = tmp_path / "repacked.tar.gz"
    repack_tar_gz(extracted, dest)

    with tarfile.open(dest) as tar:
        names = set(tar.getnames())
    # No extra arcname wrapper injected -- "pkg-1.0.0" is already the top-level
    # entry because that's what was actually inside `extracted`.
    assert "pkg-1.0.0" in names
    assert "pkg-1.0.0/a.txt" in names
    assert "pkg-1.0.0/sub/b.txt" in names


def test_repack_tar_gz_after_removing_a_path(tmp_path):
    extracted = tmp_path / "extracted"
    (extracted / "pkg-1.0.0" / "deps").mkdir(parents=True)
    (extracted / "pkg-1.0.0" / "keep.txt").write_text("keep")
    (extracted / "pkg-1.0.0" / "deps" / "bundled.tar").write_text("strip me")

    shutil.rmtree(extracted / "pkg-1.0.0" / "deps")

    dest = tmp_path / "stripped.tar.gz"
    repack_tar_gz(extracted, dest)

    with tarfile.open(dest) as tar:
        names = tar.getnames()
    assert "pkg-1.0.0/keep.txt" in names
    assert not any("deps" in name for name in names)
