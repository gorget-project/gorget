"""Package-manager command selection and execution settings."""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Callable, Sequence
from contextlib import nullcontext
from pathlib import Path

import yaml

from gorget.config.schema import ToolchainEntry
from gorget.exceptions import GorgetTransientError
from gorget.toolchain import wrap_command
from gorget.util.subprocess_run import run


def yarn_is_berry(workspace: Path) -> bool:
    manifest = workspace / "package.json"
    if manifest.is_file():
        try:
            version = json.loads(manifest.read_text()).get("packageManager", "")
        except (json.JSONDecodeError, OSError):
            version = ""
        match = re.match(r"^yarn@(\d+)", version or "")
        if match:
            return int(match[1]) >= 2
    yarnrc = workspace / ".yarnrc.yml"
    if yarnrc.is_file() and "yarnPath" in (yaml.safe_load(yarnrc.read_text()) or {}):
        return True
    return (workspace / ".yarn/releases").is_dir()


def yarn_command(workspace: Path, args: Sequence[str]) -> list[str]:
    yarnrc = workspace / ".yarnrc.yml"
    config = yaml.safe_load(yarnrc.read_text()) if yarnrc.is_file() else {}
    yarn_path = (config or {}).get("yarnPath")
    if yarn_path:
        binary = workspace / yarn_path
        if not binary.is_file():
            raise GorgetTransientError(f"Configured Yarn release does not exist: {binary}")
        return ["node", str(binary), *args]
    return ["yarn", *args]


class PackageManager:
    def __init__(
        self,
        workspace: Path | None,
        toolchain: Sequence[ToolchainEntry] = (),
        *,
        runner: Callable = run,
        use_workspace: bool = True,
        offline: bool = False,
    ) -> None:
        self.workspace, self.toolchain, self.runner = workspace, toolchain, runner
        self.use_workspace, self.offline = use_workspace, offline

    def run(
        self, command: list[str], *, env: dict[str, str] | None = None, lockfile_only: bool = False
    ):
        settings = dict(env or {})
        ecosystem = command[0]
        if ecosystem == "go" and not self.use_workspace:
            settings["GOWORK"] = "off"
        if self.offline:
            if ecosystem == "go":
                settings.update(GOPROXY="off", GOSUMDB="off")
            elif ecosystem == "cargo":
                settings["CARGO_NET_OFFLINE"] = "true"
            elif (
                ecosystem == "yarn" and self.workspace is not None and yarn_is_berry(self.workspace)
            ):
                settings["YARN_ENABLE_NETWORK"] = "false"
            elif ecosystem == "yarn":
                command = [*command, "--offline"]
            elif ecosystem in ("npm", "pnpm"):
                command = [*command, "--offline"]
            elif ecosystem == "mvn" and "-o" not in command:
                command = [command[0], "-o", *command[1:]]
        if ecosystem == "yarn":
            if self.workspace is None:
                raise ValueError("Yarn requires a workspace")
            command = yarn_command(self.workspace, command[1:])
        temporary_state = (
            ecosystem == "yarn"
            and lockfile_only
            and self.workspace is not None
            and yarn_is_berry(self.workspace)
        )
        with (
            tempfile.TemporaryDirectory(prefix="gorget-manager-state-")
            if temporary_state
            else nullcontext()
        ) as temporary:
            if temporary_state:
                assert temporary is not None
                settings.update(
                    YARN_ENABLE_GLOBAL_CACHE="true",
                    YARN_INSTALL_STATE_PATH=str(Path(temporary) / "install-state.gz"),
                )
            kwargs = {"env": settings} if settings else {}
            return self.runner(wrap_command(command, self.toolchain), cwd=self.workspace, **kwargs)
