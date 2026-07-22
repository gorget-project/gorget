"""Single subprocess entry point so tests can mock exactly one call site."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run `cmd`, capturing stdout/stderr as text. Never raises on nonzero exit --
    callers inspect `.returncode` and decide how to translate failures into
    gorget's exception hierarchy.
    """
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
