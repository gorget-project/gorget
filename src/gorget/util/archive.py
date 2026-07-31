"""Tar archive creation/extraction helpers."""

from __future__ import annotations

import contextlib
import gzip
import tarfile
from pathlib import Path

from gorget.exceptions import GorgetConfigError

# gzip's container header embeds two things that would otherwise vary between
# runs with byte-identical tar content: a wall-clock mtime (`mtime=None`
# stamps `time.time()`) and the destination's own filename (the FNAME field,
# populated whenever `GzipFile` is given a nonempty `filename`). Pin mtime to
# a fixed epoch and suppress the filename (`filename=""`) so archives are
# fully reproducible regardless of when or under what path they're built.
_GZIP_MTIME = 0

GZIP_SUFFIXES = (".tar.gz", ".tgz")
BZ2_SUFFIXES = (".tar.bz2", ".tbz2")


def strip_archive_suffix(filename: str) -> str:
    """Strip a known tar/compression suffix (`.tar.gz`, `.tar.bz2`, etc.) from
    `filename`, leaving the bare name -- e.g. `helm-4.2.3` from
    `helm-4.2.3.tar.gz`. Used to derive an archive's internal top-level
    directory from its own output filename, so the two always agree.
    """
    for suffix in (*GZIP_SUFFIXES, *BZ2_SUFFIXES):
        if filename.endswith(suffix):
            return filename[: -len(suffix)]
    return filename


def compression_kind(path: Path) -> str:
    """Derive the compression scheme ("gz" or "bz2") from `path`'s extension,
    so an archive's actual bytes always match what its filename claims.
    """
    name = path.name
    if name.endswith(GZIP_SUFFIXES):
        return "gz"
    if name.endswith(BZ2_SUFFIXES):
        return "bz2"
    raise GorgetConfigError(
        f"Unrecognized archive extension for {path}: expected one of "
        f"{', '.join(GZIP_SUFFIXES + BZ2_SUFFIXES)}"
    )


@contextlib.contextmanager
def open_gzip_tar(dest: Path):
    """Open `dest` for writing as a tar stream wrapped in a gzip container
    whose header carries neither a wall-clock timestamp nor an embedded
    filename, so identical tar content always produces identical bytes.
    """
    with (
        open(dest, "wb") as raw,
        gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=_GZIP_MTIME) as gz,
        tarfile.open(fileobj=gz, mode="w:") as tar,
    ):
        yield tar


def _exclude_git(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if ".git" in Path(tarinfo.name).parts:
        return None
    return tarinfo


def _normalize_mtime(mtime: int):
    def _filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
        filtered = _exclude_git(tarinfo)
        if filtered is None:
            return None
        filtered.mtime = mtime
        return filtered

    return _filter


def make_tar_gz(src_dir: Path, dest: Path, arcname: str, *, mtime: int | None = None) -> None:
    """Tar up `src_dir` (excluding `.git`) as `arcname`.

    The archive's compression is derived from `dest`'s extension (`.tar.gz`/
    `.tgz` for gzip, `.tar.bz2`/`.tbz2` for bzip2) so the bytes on disk always
    match what the filename claims.

    `mtime`, when given, is stamped onto every archive member in place of the
    checkout's live filesystem mtimes -- e.g. the commit's own timestamp -- so
    that re-fetching an unchanged ref produces byte-identical archives.
    """
    kind = compression_kind(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    filter_fn = _normalize_mtime(mtime) if mtime is not None else _exclude_git
    if kind == "gz":
        with open_gzip_tar(dest) as tar:
            tar.add(src_dir, arcname=arcname, filter=filter_fn)
    else:
        with tarfile.open(dest, "w:bz2") as tar:
            tar.add(src_dir, arcname=arcname, filter=filter_fn)


def extract_tar_gz(archive_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path) as tar:
        tar.extractall(dest_dir, filter="data")


def _reference_mtime(src_dir: Path) -> int:
    """The newest mtime among `src_dir`'s actual files.

    Directory mtimes aren't trustworthy here: removing an entry from a
    directory (e.g. `strip-tarball` deleting a matched path) bumps that
    directory's own mtime to wall-clock "now", which would otherwise leak
    into the repacked archive and make it non-deterministic across runs.
    Regular files are untouched by that and keep the mtime `extract_tar_gz`
    restored from the original archive, so deriving the reference from them
    instead keeps repacking reproducible.
    """
    mtimes = [p.stat().st_mtime for p in src_dir.rglob("*") if p.is_file()]
    return int(max(mtimes)) if mtimes else 0


def repack_tar_gz(src_dir: Path, dest: Path) -> None:
    """Tar up `src_dir`'s contents at their own top-level paths (no injected
    `arcname` wrapper like `make_tar_gz`) -- used to repack a tarball after
    stripping paths from it, preserving whatever internal layout it already had.

    The archive's compression is derived from `dest`'s extension (`.tar.gz`/
    `.tgz` for gzip, `.tar.bz2`/`.tbz2` for bzip2) so the bytes on disk always
    match what the filename claims.

    Every member is stamped with `_reference_mtime(src_dir)` so repacking the
    same stripped content twice always produces byte-identical output.
    """
    kind = compression_kind(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    filter_fn = _normalize_mtime(_reference_mtime(src_dir))
    if kind == "gz":
        with open_gzip_tar(dest) as tar:
            for entry in sorted(src_dir.iterdir()):
                tar.add(entry, arcname=entry.name, filter=filter_fn)
    else:
        with tarfile.open(dest, "w:bz2") as tar:
            for entry in sorted(src_dir.iterdir()):
                tar.add(entry, arcname=entry.name, filter=filter_fn)
