"""`spec-source` fetch step: download Source URLs declared (and macro-resolved) in
the spec, by index or all of them.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from gorget.config.schema import SpecSourceStep
from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import FetchContext, FetchedArtifact, build_artifact
from gorget.util.download import download_to


class SpecSourceHandler:
    def run(self, step: SpecSourceStep, ctx: FetchContext) -> list[FetchedArtifact]:
        entries = ctx.spec.sources()
        if step.index is None:
            targets = entries
        else:
            targets = [entry for entry in entries if entry.index == step.index]
            if not targets:
                raise GorgetConfigError(f"No Source{step.index} found in spec")

        artifacts = []
        for entry in targets:
            filename = (
                step.rename
                if (step.rename and len(targets) == 1)
                else Path(urlparse(entry.url).path).name
            )
            if not filename:
                raise GorgetConfigError(f"Could not derive a filename from Source URL: {entry.url}")
            dest = ctx.work_dir / filename
            if not ctx.dry_run:
                download_to(entry.url, dest)
            artifacts.append(build_artifact(dest, filename, entry.url, ctx.dry_run))
        return artifacts
