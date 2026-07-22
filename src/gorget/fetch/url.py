"""`url` fetch step: download an explicit URL declared in the pipeline YAML."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from gorget.config.schema import UrlStep
from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import FetchContext, FetchedArtifact, build_artifact
from gorget.util.download import download_to


class UrlHandler:
    def run(self, step: UrlStep, ctx: FetchContext) -> list[FetchedArtifact]:
        filename = step.filename or Path(urlparse(step.url).path).name
        if not filename:
            raise GorgetConfigError(f"Could not derive a filename from URL: {step.url}")
        dest = ctx.work_dir / filename
        if not ctx.dry_run:
            download_to(step.url, dest)
        return [build_artifact(dest, filename, step.url, ctx.dry_run)]
