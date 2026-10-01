"""Execution settings apply consistently to updates, vendoring, and inventory."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from gorget.package_manager import PackageManager


@pytest.mark.parametrize(
    "command,env",
    [
        (["go", "list", "-m", "foo"], {"GOWORK": "off", "GOPROXY": "off", "GOSUMDB": "off"}),
        (["cargo", "check"], {"CARGO_NET_OFFLINE": "true"}),
    ],
)
def test_offline_commands_and_go_isolation(tmp_path, command, env):
    runner = Mock()
    PackageManager(tmp_path, runner=runner, offline=True, use_workspace=False).run(command)
    runner.assert_called_once_with(command, cwd=tmp_path, env=env)


def test_bundled_yarn_uses_external_state_for_lock_updates(tmp_path):
    (tmp_path / "package.json").write_text('{"packageManager":"yarn@4.0.0"}')
    (tmp_path / ".yarnrc.yml").write_text("yarnPath: yarn.cjs\n")
    (tmp_path / "yarn.cjs").write_text("// fixture")
    paths = []

    def command(args, cwd, env):
        assert args == ["node", str(tmp_path / "yarn.cjs"), "install", "--mode", "update-lockfile"]
        assert env["YARN_ENABLE_GLOBAL_CACHE"] == "true"
        assert env["YARN_ENABLE_NETWORK"] == "false"
        path = Path(env["YARN_INSTALL_STATE_PATH"])
        assert not path.is_relative_to(tmp_path)
        path.write_text("transient")
        paths.append(path)

    PackageManager(tmp_path, runner=command, offline=True).run(
        ["yarn", "install", "--mode", "update-lockfile"], lockfile_only=True
    )
    assert not paths[0].exists()
