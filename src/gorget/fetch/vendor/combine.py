"""Combine one or more per-module vendor directories into a single archive.

Each module gets its own top-level directory in the combined archive (named after
`VendorModule.name`, or a sanitized form of `VendorModule.path`), preserving each
module's internal vendor layout untouched -- e.g. for etcd's multi-submodule case:

    etcd-vendor/
    |-- server/vendor/...
    |-- etcdctl/vendor/...
    `-- etcdutl/vendor/...
"""

from __future__ import annotations

import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

from gorget.util.archive import compression_kind, open_gzip_tar

if TYPE_CHECKING:
    from gorget.config.schema import VendorModule


def _default_label(path: str) -> str:
    return path.strip("./").replace("/", "_") or "vendor"


def combine_vendor_archives(
    module_outputs: list[tuple[VendorModule, Path]], archive_path: Path, *, mtime: int | None = None
) -> None:
    """Combine per-module vendor directories into a single archive.

    The archive's compression is derived from `archive_path`'s extension
    (`.tar.gz`/`.tgz` for gzip, `.tar.bz2`/`.tbz2` for bzip2) so the bytes on
    disk always match what the filename claims.

    `mtime`, when given, is stamped onto every archive member -- e.g. the
    source checkout's commit timestamp -- in place of the vendor tool's live
    filesystem mtimes (module downloads/installs happen at fetch wall-clock
    time), so re-running the same fetch produces a byte-identical archive.
    """
    kind = compression_kind(archive_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    def _filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
        if mtime is not None:
            tarinfo.mtime = mtime
        return tarinfo

    def _add_all(tar: tarfile.TarFile) -> None:
        for module, vendor_dir in module_outputs:
            label = module.name or _default_label(module.path)
            tar.add(vendor_dir, arcname=label, filter=_filter)

    if kind == "gz":
        with open_gzip_tar(archive_path) as tar:
            _add_all(tar)
    else:
        with tarfile.open(archive_path, "w:bz2") as tar:
            _add_all(tar)
