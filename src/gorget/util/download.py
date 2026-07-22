"""HTTP fetch, streamed to disk."""

from __future__ import annotations

from pathlib import Path

import requests

from gorget.exceptions import GorgetTransientError

_CHUNK_SIZE = 64 * 1024
_TIMEOUT_SECONDS = 60


def download_to(url: str, dest: Path) -> None:
    try:
        response = requests.get(url, stream=True, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise GorgetTransientError(f"Failed to download {url}: {exc}") from exc

    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
            if chunk:
                f.write(chunk)
