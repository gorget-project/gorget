"""The mutable source workspace and its immutable source artifacts."""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from gorget.exceptions import GorgetConfigError
from gorget.pipeline.artifact import Artifact, build_derived_artifact
from gorget.util.archive import extract_tar_gz, make_tar_gz, repack_tar_gz, strip_archive_suffix
from gorget.util.git import commit_timestamp

SourceLayout = Literal["checkout", "archive"]


@dataclass(kw_only=True)
class SourceWorkspace:
    path: Path | None = None
    artifact: Artifact | None = None
    layout: SourceLayout | None = None
    dirty: bool = False

    def attach_checkout(self, path: Path, artifact: Artifact) -> None:
        self.path = path
        self.artifact = artifact
        self.layout = "checkout"
        self.dirty = False

    def attach_tree(self, path: Path) -> None:
        """Attach a source tree with no source artifact backing it."""
        self.path = path
        self.artifact = None
        self.layout = None
        self.dirty = False

    def materialize(self, work_dir: Path, artifacts: list[Artifact]) -> Path:
        if self.path is not None:
            return self.path
        if len(artifacts) != 1:
            raise GorgetConfigError(
                "This transform step needs a source checkout, but no 'git' fetch step "
                "ran and there isn't exactly one fetched artifact to extract instead "
                f"(found {len(artifacts)})"
            )
        extract_dir = work_dir / "_source"
        extract_tar_gz(artifacts[0].path, extract_dir)
        self.path = extract_dir
        self.artifact = artifacts[0]
        self.layout = "archive"
        return extract_dir

    def mark_dirty(self) -> None:
        self.dirty = True

    def adopt_filtered_artifact(
        self,
        parent: Artifact,
        derived: Artifact,
        removed_paths: Iterable[Path],
    ) -> None:
        """Apply an archive filter to the active tree when it backs ``parent``."""
        if self.artifact is not parent or self.path is None:
            return

        for archive_path in removed_paths:
            relative_path = archive_path
            if self.layout == "checkout":
                if len(archive_path.parts) < 2:
                    raise GorgetConfigError(
                        "Cannot remove the archive root from an active source checkout"
                    )
                relative_path = Path(*archive_path.parts[1:])
            workspace_path = self.path / relative_path
            if workspace_path.is_dir() and not workspace_path.is_symlink():
                shutil.rmtree(workspace_path)
            elif workspace_path.exists() or workspace_path.is_symlink():
                workspace_path.unlink()

        self.artifact = derived

    def commit(self, work_dir: Path, *, dry_run: bool) -> Artifact | None:
        if dry_run or not self.dirty or self.path is None or self.artifact is None:
            return None

        parent = self.artifact
        revision = parent.checksum[:12] if parent.checksum is not None else "unhashed"
        destination = work_dir / "_derived" / f"source-{revision}" / parent.output_name

        if self.layout == "checkout":
            make_tar_gz(
                self.path,
                destination,
                arcname=strip_archive_suffix(parent.output_name),
                mtime=commit_timestamp(self.path),
            )
        else:
            repack_tar_gz(self.path, destination)

        derived = build_derived_artifact(
            destination,
            parent.output_name,
            parent.source_description,
            dry_run=False,
            parents=[parent],
        )
        self.artifact = derived
        self.dirty = False
        return derived
