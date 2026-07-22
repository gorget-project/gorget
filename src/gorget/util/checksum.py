"""File hashing and dist-git `sources` manifest formatting."""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 1024 * 1024


def compute_digest(path: Path, algo: str) -> str:
    hasher = hashlib.new(algo)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def format_sources_manifest(entries: list[tuple[str, str]], algo: str) -> str:
    """Fedora dist-git `sources` file format: `SHA512 (<filename>) = <digest>`."""
    lines = [f"{algo.upper()} ({name}) = {digest}" for name, digest in sorted(entries)]
    return "".join(f"{line}\n" for line in lines)
