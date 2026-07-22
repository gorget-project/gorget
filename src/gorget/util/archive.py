"""Tar archive creation helpers."""

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
