"""The mutable source workspace and its immutable source artifacts."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from gorget.exceptions import GorgetConfigError
from gorget.pipeline.artifact import Artifact, build_derived_artifact
from gorget.util.archive import extract_tar_gz, make_tar_gz, repack_tar_gz, strip_archive_suffix
from gorget.util.git import commit_timestamp


@dataclass(frozen=True)
class SourceChange:
    """A relative source file replacement, or deletion when content is None."""

    path: Path
    content: bytes | None


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

    def select(
        self,
        work_dir: Path,
        artifacts: list[Artifact],
        target: str | None = None,
        *,
        detached: bool = False,
    ) -> Path:
        """Select a source, with source switches and extraction owned here."""
        if target is None:
            return self.materialize(work_dir, artifacts)
        artifact = next((item for item in artifacts if item.output_name == target), None)
        if artifact is None:
            raise GorgetConfigError(f"No publication artifact named {target!r}")
        if detached:
            destination = work_dir / "_transform_source" / target
            if destination.exists():
                shutil.rmtree(destination)
            extract_tar_gz(artifact.path, destination)
            return destination
        if self.artifact is artifact and self.path is not None:
            return self.path
        if self.dirty:
            raise GorgetConfigError(
                "Cannot switch vendor sources while the active workspace has uncommitted changes"
            )
        # Use an artifact-specific directory, so an old extraction cannot leak
        # files into the newly selected source.
        work_dir.mkdir(parents=True, exist_ok=True)
        destination = Path(tempfile.mkdtemp(prefix="_source-", dir=work_dir))
        extract_tar_gz(artifact.path, destination)
        self.path, self.artifact, self.layout = destination, artifact, "archive"
        return destination

    def apply_changes(self, changes: Iterable[SourceChange]) -> None:
        """Validate all changes before applying them; mark real changes dirty."""
        changes = tuple(changes)
        if not changes:
            return
        if self.path is None:
            raise GorgetConfigError("Source changes require an active source workspace")
        root = self.path.resolve()
        for change in changes:
            destination = self.path / change.path
            if change.path.is_absolute() or not destination.resolve().is_relative_to(root):
                raise GorgetConfigError(f"Source change escapes the workspace: {change.path}")
        for change in changes:
            destination = self.path / change.path
            if change.content is None:
                if destination.is_file() or destination.is_symlink():
                    destination.unlink()
                    self.mark_dirty()
            elif not destination.is_file() or destination.read_bytes() != change.content:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(change.content)
                self.mark_dirty()

    @contextmanager
    def edit_metadata(self, paths: Iterable[Path]) -> Iterator[Path]:
        """Edit an isolated tree; publish declared metadata only after success."""
        if self.path is None:
            raise GorgetConfigError("Source edits require an active workspace")
        paths = tuple(paths)
        for relative in paths:
            if relative.is_absolute() or not (self.path / relative).resolve().is_relative_to(
                self.path.resolve()
            ):
                raise GorgetConfigError(f"Source change escapes the workspace: {relative}")
        with tempfile.TemporaryDirectory(prefix="gorget-source-edit-") as temporary:
            tree = Path(temporary) / "source"
            shutil.copytree(self.path, tree, symlinks=True, ignore=shutil.ignore_patterns(".git"))
            yield tree
            changes = []
            for relative in paths:
                edited = tree / relative
                changes.append(
                    SourceChange(relative, edited.read_bytes() if edited.is_file() else None)
                )
            self.apply_changes(changes)

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
