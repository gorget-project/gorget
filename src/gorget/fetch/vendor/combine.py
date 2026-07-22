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

if TYPE_CHECKING:
    from gorget.config.schema import VendorModule


def _default_label(path: str) -> str:
    return path.strip("./").replace("/", "_") or "root"


def combine_vendor_archives(
    module_outputs: list[tuple[VendorModule, Path]], archive_path: Path
) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as tar:
        for module, vendor_dir in module_outputs:
            label = module.name or _default_label(module.path)
            tar.add(vendor_dir, arcname=label)
