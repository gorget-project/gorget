"""`pack` transform step: build a deterministic archive from an explicit list
of files already in --package-dir, preserving each file's own relative path.

Unlike `run:` shelling out to the system `tar`/`gzip` binaries, this builds
the archive directly with Python's own tarfile/gzip modules (via
`util.archive.pack_files`) -- gzip's compressed output isn't uniquely
determined by its input, so two different tar/gzip builds can compress
byte-identical, identically-timestamped content into different bytes. Tying
reproducibility to the interpreter's own zlib instead of whatever tar/gzip
happens to be installed on the host removes that class of bug entirely.
"""

from __future__ import annotations

from gorget.config.schema import PackStep
from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import build_artifact
from gorget.pipeline.state import StageState
from gorget.transform.base import TransformContext
from gorget.util.archive import pack_files


class PackHandler:
    def run(self, step: PackStep, ctx: TransformContext, state: StageState) -> None:
        if ctx.dry_run:
            return

        files = []
        for rel in step.files:
            src = ctx.package_dir / rel
            if not src.exists():
                raise GorgetConfigError(f"pack: file not found: {src}")
            files.append((src, rel))

        dest = ctx.work_dir / step.output
        pack_files(files, dest)

        description = f"pack:{', '.join(step.files)}"
        state.artifacts.append(build_artifact(dest, step.output, description, ctx.dry_run))
