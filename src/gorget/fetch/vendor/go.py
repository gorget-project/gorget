from __future__ import annotations

import shlex
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from gorget.config.schema import ToolchainEntry
from gorget.exceptions import GorgetTransientError
from gorget.toolchain import wrap_command
from gorget.util.subprocess_run import run

_CONFIG_FILENAME = "go-vendor-tools.toml"


@dataclass(frozen=True, kw_only=True)
class _ArchiveConfig:
    """The subset of go-vendor-tools.toml's `[archive]` table that affects
    vendor *content* (as opposed to how go-vendor-tools itself packs/compresses
    an archive, which gorget always does its own way). Mirrors go-vendor-tools'
    own `create_archive` command order -- pre_commands, then
    dependency_overrides (each applied via `go get <path>@<version>`), then
    `go mod tidy` if enabled, then `go mod vendor`, then post_commands -- so a
    package's vendored dependencies don't change just because gorget produced
    the archive instead of go-vendor-tools directly.
    """

    pre_commands: list[list[str]] = field(default_factory=list)
    post_commands: list[list[str]] = field(default_factory=list)
    dependency_overrides: dict[str, str] = field(default_factory=dict)
    tidy: bool = True


def _load_archive_config(package_dir: Path | None) -> _ArchiveConfig:
    if package_dir is None:
        return _ArchiveConfig()
    config_path = package_dir / _CONFIG_FILENAME
    if not config_path.is_file():
        return _ArchiveConfig()
    archive = tomllib.loads(config_path.read_text()).get("archive", {})
    return _ArchiveConfig(
        pre_commands=archive.get("pre_commands", []),
        post_commands=archive.get("post_commands", []),
        dependency_overrides=archive.get("dependency_overrides", {}),
        tidy=archive.get("tidy", True),
    )


class GoVendor:
    def vendor(
        self,
        module_dir: Path,
        toolchain: Sequence[ToolchainEntry] = (),
        package_dir: Path | None = None,
    ) -> Path:
        config = _load_archive_config(package_dir)

        commands = [
            *config.pre_commands,
            *(
                ["go", "get", f"{import_path}@{version}"]
                for import_path, version in config.dependency_overrides.items()
            ),
        ]
        if config.tidy:
            commands.append(["go", "mod", "tidy"])
        commands.append(["go", "mod", "vendor"])
        commands.extend(config.post_commands)

        for command in commands:
            self._run(command, module_dir, toolchain)
        return module_dir / "vendor"

    def _run(
        self, command: list[str], module_dir: Path, toolchain: Sequence[ToolchainEntry]
    ) -> None:
        result = run(wrap_command(command, toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"{shlex.join(command)} failed in {module_dir}: {result.stderr.strip()}"
            )
