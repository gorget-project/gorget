"""Single subprocess entry point so tests can mock exactly one call site.

This is also the single point where `--debug` traces every command gorget
runs -- git, rpmspec, go/npm/cargo/composer, toolchain version checks, etc.
all funnel through here.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("gorget.subprocess")


def run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run `cmd`, capturing stdout/stderr as text. Never raises on nonzero exit --
    callers inspect `.returncode` and decide how to translate failures into
    gorget's exception hierarchy.
    """
    logger.debug("+ %s%s", " ".join(cmd), f"  (cwd={cwd})" if cwd else "")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    logger.debug("  -> exit %d", result.returncode)
    if result.stdout:
        logger.debug("  stdout: %s", result.stdout.rstrip())
    if result.stderr:
        logger.debug("  stderr: %s", result.stderr.rstrip())
    return result
