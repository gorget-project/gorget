import os
import shutil
import tarfile

from gorget.util.archive import (
    compression_kind,
    extract_tar_gz,
    make_tar_gz,
    pack_files,
    repack_tar_gz,
)


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


def test_make_tar_gz_normalizes_owner_fields(tmp_path):
    """Regression test: `tarfile.add()` populates uid/gid/uname/gname from the
    local filesystem's owner and passwd/group lookups by default, so the same
    content built under two different users (or CI service accounts with
    different names) would otherwise emit different header bytes even with
    mtime already pinned.
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello")

    dest = tmp_path / "archive.tar.gz"
    make_tar_gz(src, dest, arcname="pkg", mtime=42)

    with tarfile.open(dest) as tar:
        for member in tar.getmembers():
            assert member.uid == 0
            assert member.gid == 0
            assert member.uname == ""
            assert member.gname == ""


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


def test_repack_tar_gz_is_deterministic_after_removing_a_path(tmp_path):
    """Regression test: removing a path bumps its parent directory's own
    mtime to wall-clock "now" (standard filesystem behavior), independent of
    any file content -- repack_tar_gz must not let that leak into the
    archive, or repacking the same stripped content twice (e.g. two runs of
    `strip-tarball`) would produce different bytes each time.
    """

    def build(dest_name):
        extracted = tmp_path / f"extracted-{dest_name}"
        (extracted / "pkg-1.0.0" / "deps").mkdir(parents=True)
        (extracted / "pkg-1.0.0" / "keep.txt").write_text("keep")
        (extracted / "pkg-1.0.0" / "deps" / "bundled.tar").write_text("strip me")
        os.utime(extracted / "pkg-1.0.0" / "keep.txt", (1000, 1000))
        shutil.rmtree(extracted / "pkg-1.0.0" / "deps")
        dest = tmp_path / f"{dest_name}.tar.gz"
        repack_tar_gz(extracted, dest)
        return dest.read_bytes()

    first = build("first")
    second = build("second")
    assert first == second


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


def test_compression_kind_recognizes_xz_suffixes(tmp_path):
    assert compression_kind(tmp_path / "archive.tar.xz") == "xz"
    assert compression_kind(tmp_path / "archive.txz") == "xz"


def test_make_tar_gz_writes_real_xz_content(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello")

    dest = tmp_path / "archive.tar.xz"
    make_tar_gz(src, dest, arcname="pkg-1.0.0")

    with tarfile.open(dest) as tar:
        assert tar.getnames() == ["pkg-1.0.0", "pkg-1.0.0/a.txt"]


def test_make_tar_xz_is_byte_identical_across_runs_with_different_source_mtimes(tmp_path):
    def build(offset, dest_name):
        src = tmp_path / f"src-{offset}"
        src.mkdir()
        (src / "a.txt").write_text("hello")
        os.utime(src / "a.txt", (1000 + offset, 1000 + offset))
        os.utime(src, (1000 + offset, 1000 + offset))
        dest = tmp_path / dest_name
        make_tar_gz(src, dest, arcname="pkg", mtime=999)
        return dest.read_bytes()

    first = build(0, "first.tar.xz")
    second = build(3600, "second.tar.xz")
    assert first == second


def test_pack_files_preserves_each_files_own_relative_path(tmp_path):
    top = tmp_path / "pkg"
    (top / "sub").mkdir(parents=True)
    (top / "a.txt").write_text("hello")
    (top / "sub" / "b.txt").write_text("world")

    dest = tmp_path / "out" / "archive.tar.gz"
    pack_files([(top / "a.txt", "a.txt"), (top / "sub" / "b.txt", "sub/b.txt")], dest)

    with tarfile.open(dest) as tar:
        names = set(tar.getnames())
    # No injected wrapper directory (unlike make_tar_gz's arcname) -- each
    # file lands exactly at the arcname given.
    assert names == {"a.txt", "sub/b.txt"}


def test_pack_files_normalizes_mtime_and_owner_fields(tmp_path):
    top = tmp_path / "pkg"
    top.mkdir()
    (top / "a.txt").write_text("hello")
    os.utime(top / "a.txt", (12345, 12345))

    dest = tmp_path / "archive.tar.gz"
    pack_files([(top / "a.txt", "a.txt")], dest)

    with tarfile.open(dest) as tar:
        (member,) = tar.getmembers()
    assert member.mtime == 0
    assert member.uid == 0
    assert member.gid == 0
    assert member.uname == ""
    assert member.gname == ""


def test_pack_files_is_deterministic_regardless_of_source_mtime(tmp_path):
    def build(offset, dest_name):
        top = tmp_path / f"pkg-{offset}"
        top.mkdir()
        (top / "a.txt").write_text("hello")
        os.utime(top / "a.txt", (1000 + offset, 1000 + offset))
        dest = tmp_path / dest_name
        pack_files([(top / "a.txt", "a.txt")], dest)
        return dest.read_bytes()

    first = build(0, "first.tar.gz")
    second = build(3600, "second.tar.gz")
    assert first == second


def test_pack_files_respects_dest_compression_suffix(tmp_path):
    top = tmp_path / "pkg"
    top.mkdir()
    (top / "a.txt").write_text("hello")

    dest = tmp_path / "archive.tar.xz"
    pack_files([(top / "a.txt", "a.txt")], dest)

    with tarfile.open(dest) as tar:
        assert tar.getnames() == ["a.txt"]
