"""Combine one or more per-module vendor directories into a single archive.

A lone module with no explicit name produces a bare `vendor/` at the archive
root, matching go-vendor-tools' own convention for a standalone vendor
archive -- e.g. cosign, or each of etcd's three independent per-submodule
archives (separate `vendor:` steps, each with exactly one module, not one
archive combining all three). Multiple modules combined into *one* archive
(or a lone module with an explicit `name` override) instead get their own
top-level directory each, named after `VendorModule.name` or a sanitized form
of `VendorModule.path` -- e.g. a single combined `vendor:` step listing all of
etcd's submodules as modules:

    etcd-vendor/
    |-- server/...
    |-- etcdctl/...
    `-- etcdutl/...
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
    (`.tar.gz`/`.tgz` for gzip, `.tar.bz2`/`.tbz2` for bzip2, `.tar.xz`/`.txz`
    for xz) so the bytes on disk always match what the filename claims.

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
        # A lone module with no explicit name has nothing to disambiguate
        # against, so it always gets a bare "vendor" -- regardless of its
        # path -- matching go-vendor-tools' own convention for a standalone
        # archive. Found via etcd: three independent `vendor:` steps (one per
        # submodule, each with a non-trivial path like "server"), each
        # producing its own archive that %prep extracts with `-C server` --
        # so the archive itself must already be bare "vendor/", not
        # "server/vendor/" (that would double the "server/" nesting).
        # An explicit `name` is a deliberate override and is always honored.
        bare_vendor = len(module_outputs) == 1 and module_outputs[0][0].name is None
        for module, vendor_dir in module_outputs:
            arcname = "vendor" if bare_vendor else (module.name or _default_label(module.path))
            tar.add(vendor_dir, arcname=arcname, filter=_filter)

    if kind == "gz":
        with open_gzip_tar(archive_path) as tar:
            _add_all(tar)
    else:
        with tarfile.open(archive_path, f"w:{kind}") as tar:
            _add_all(tar)
