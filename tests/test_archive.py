import os
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


def test_make_tar_gz_mtime_stamps_every_member(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello")
    (src / "sub").mkdir()
    (src / "sub" / "b.txt").write_text("world")
    os.utime(src / "a.txt", (12345, 12345))
    os.utime(src / "sub" / "b.txt", (67890, 67890))

    dest = tmp_path / "archive.tar.gz"
    make_tar_gz(src, dest, arcname="pkg", mtime=42)

    with tarfile.open(dest) as tar:
        mtimes = {member.mtime for member in tar.getmembers()}
    assert mtimes == {42}


def test_make_tar_gz_gzip_header_timestamp_is_pinned(tmp_path):
    """Regression test: gzip's own container header embeds a wall-clock
    timestamp by default (independent of any tar member mtime), so even with
    every tar member normalized, two runs built at different real times used to
    emit different bytes overall. The gzip header's mtime field (bytes 4-7) must
    always be pinned, not just the tar members inside it.
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello")

    dest = tmp_path / "archive.tar.gz"
    make_tar_gz(src, dest, arcname="pkg", mtime=999)

    header_mtime = int.from_bytes(dest.read_bytes()[4:8], "little")
    assert header_mtime == 0


def test_make_tar_gz_is_byte_identical_across_runs_with_different_source_mtimes(tmp_path):
    """End-to-end reproducibility check combining both fixes: identical content
    from two different source directories, with different filesystem mtimes,
    must produce byte-identical archives when the same `mtime` is requested.
    """

    def build(offset, dest_name):
        src = tmp_path / f"src-{offset}"
        src.mkdir()
        (src / "a.txt").write_text("hello")
        os.utime(src / "a.txt", (1000 + offset, 1000 + offset))
        os.utime(src, (1000 + offset, 1000 + offset))
        dest = tmp_path / dest_name
        make_tar_gz(src, dest, arcname="pkg", mtime=999)
        return dest.read_bytes()

    first = build(0, "first.tar.gz")
    second = build(3600, "second.tar.gz")
    assert first == second


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
