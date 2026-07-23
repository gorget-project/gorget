"""Tar archive creation/extraction helpers."""

from __future__ import annotations

import tarfile
from pathlib import Path


def _exclude_git(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if ".git" in Path(tarinfo.name).parts:
        return None
    return tarinfo


def make_tar_gz(src_dir: Path, dest: Path, arcname: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz") as tar:
        tar.add(src_dir, arcname=arcname, filter=_exclude_git)


def extract_tar_gz(archive_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path) as tar:
        tar.extractall(dest_dir, filter="data")


def repack_tar_gz(src_dir: Path, dest: Path) -> None:
    """Tar up `src_dir`'s contents at their own top-level paths (no injected
    `arcname` wrapper like `make_tar_gz`) -- used to repack a tarball after
    stripping paths from it, preserving whatever internal layout it already had.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz") as tar:
        for entry in sorted(src_dir.iterdir()):
            tar.add(entry, arcname=entry.name)
