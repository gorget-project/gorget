import os
import subprocess
from pathlib import Path

import pytest

from gorget.config.schema import ToolchainEntry
from gorget.exceptions import GorgetConfigError
from gorget.toolchain import activate, verify_installed, wrap_command


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_verify_installed_empty_list_does_nothing(mocker):
    mock_run = mocker.patch("gorget.toolchain.run")
    verify_installed([])
    mock_run.assert_not_called()


def test_verify_installed_passes_on_exact_match(mocker):
    mocker.patch(
        "gorget.toolchain.run",
        return_value=_completed(stdout="go version go1.22.0 linux/amd64\n"),
    )
    verify_installed([ToolchainEntry(name="go", version="1.22.0")])


def test_verify_installed_passes_on_component_wise_prefix_match(mocker):
    mocker.patch(
        "gorget.toolchain.run",
        return_value=_completed(stdout="go version go1.22.3 linux/amd64\n"),
    )
    verify_installed([ToolchainEntry(name="go", version="1.22")])


def test_verify_installed_rejects_naive_string_prefix_false_positive(mocker):
    # "1.2" must NOT match "1.23.0" -- a naive str.startswith() would wrongly
    # accept this.
    mocker.patch(
        "gorget.toolchain.run",
        return_value=_completed(stdout="go version go1.23.0 linux/amd64\n"),
    )
    with pytest.raises(GorgetConfigError, match="does not match"):
        verify_installed([ToolchainEntry(name="go", version="1.2")])


def test_verify_installed_rejects_version_mismatch(mocker):
    mocker.patch(
        "gorget.toolchain.run",
        return_value=_completed(stdout="go version go1.20.0 linux/amd64\n"),
    )
    with pytest.raises(GorgetConfigError, match="does not match the active version"):
        verify_installed([ToolchainEntry(name="go", version="1.22.0")])


def test_verify_installed_node_version_format(mocker):
    mocker.patch("gorget.toolchain.run", return_value=_completed(stdout="v20.11.0\n"))
    verify_installed([ToolchainEntry(name="node", version="20.11.0")])


def test_verify_installed_npm_version_format(mocker):
    mocker.patch("gorget.toolchain.run", return_value=_completed(stdout="10.9.4\n"))
    verify_installed([ToolchainEntry(name="npm", version="10.9")])


def test_verify_installed_cargo_version_format(mocker):
    mocker.patch(
        "gorget.toolchain.run", return_value=_completed(stdout="cargo 1.95.0 (abc123 2026-01-01)\n")
    )
    verify_installed([ToolchainEntry(name="cargo", version="1.95.0")])


def test_verify_installed_python_version_format(mocker):
    mocker.patch("gorget.toolchain.run", return_value=_completed(stdout="Python 3.13.13\n"))
    verify_installed([ToolchainEntry(name="python", version="3.13")])


def test_verify_installed_maven_version_format(mocker):
    mocker.patch(
        "gorget.toolchain.run",
        return_value=_completed(stdout="Apache Maven 3.9.11\nMaven home: /usr/share/maven\n"),
    )
    verify_installed([ToolchainEntry(name="maven", version="3.9")])


def test_verify_installed_unknown_tool_name_raises(mocker):
    mock_run = mocker.patch("gorget.toolchain.run")
    with pytest.raises(GorgetConfigError, match="Unknown toolchain name"):
        verify_installed([ToolchainEntry(name="ruby", version="3.2")])
    mock_run.assert_not_called()


def test_invalid_declared_version_is_rejected_before_executable_lookup(mocker):
    mock_which = mocker.patch("gorget.toolchain.shutil.which")
    entry = ToolchainEntry(name="node", version="../../tmp/untrusted")

    with pytest.raises(GorgetConfigError, match="Invalid version"):
        with activate([entry]):
            pass

    mock_which.assert_not_called()


def test_verify_installed_tool_not_on_path_raises(mocker):
    mocker.patch(
        "gorget.toolchain.run",
        return_value=_completed(returncode=127, stderr="command not found"),
    )
    with pytest.raises(GorgetConfigError, match="not available"):
        verify_installed([ToolchainEntry(name="go", version="1.22.0")])


def test_verify_installed_binary_not_installed_raises_config_error(mocker):
    # Distinct from "on PATH but errors" above: the binary doesn't exist at
    # all, which subprocess.run() surfaces as FileNotFoundError even with
    # check=False -- must not crash with an unhandled traceback.
    mocker.patch("gorget.toolchain.run", side_effect=FileNotFoundError("go"))
    with pytest.raises(GorgetConfigError, match="not available"):
        verify_installed([ToolchainEntry(name="go", version="1.22.0")])


def test_verify_installed_unparseable_output_raises(mocker):
    mocker.patch("gorget.toolchain.run", return_value=_completed(stdout="nonsense"))
    with pytest.raises(GorgetConfigError, match="Could not parse"):
        verify_installed([ToolchainEntry(name="go", version="1.22.0")])


def test_verify_installed_checks_every_declared_entry(mocker):
    def fake_run(cmd):
        if cmd[0] == "go":
            return _completed(stdout="go version go1.22.0 linux/amd64\n")
        return _completed(stdout="v20.11.0\n")

    mock_run = mocker.patch("gorget.toolchain.run", side_effect=fake_run)
    verify_installed(
        [
            ToolchainEntry(name="go", version="1.22.0"),
            ToolchainEntry(name="node", version="20.11.0"),
        ]
    )
    assert mock_run.call_count == 2


def test_wrap_command_is_always_a_passthrough():
    entries = [ToolchainEntry(name="go", version="1.22.0")]
    assert wrap_command(["go", "build"], entries) == ["go", "build"]
    assert wrap_command(["go", "build"], []) == ["go", "build"]


def _executable(path: Path, output: str) -> None:
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\n")
    path.chmod(0o755)


def test_activate_selects_installed_node_rpm_binaries(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / "node", "v22.0.0")
    _executable(bin_dir / "node-24", "v24.18.1")
    _executable(bin_dir / "npm-24", "11.6.2")
    _executable(bin_dir / "npx-24", "11.6.2")
    monkeypatch.setenv("PATH", str(bin_dir))

    entries = [ToolchainEntry(name="node", version="24")]
    with activate(entries):
        assert Path(os.environ["PATH"].split(os.pathsep)[0]).name.startswith(
            "gorget-toolchain-"
        )
        assert subprocess.run(
            ["/usr/bin/env", "node"], capture_output=True, text=True, check=True
        ).stdout == "v24.18.1\n"
        assert subprocess.run(
            ["/usr/bin/env", "npm"], capture_output=True, text=True, check=True
        ).stdout == "11.6.2\n"
        verify_installed(entries)

    assert os.environ["PATH"] == str(bin_dir)


def test_activate_selects_installed_python_rpm_binary(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / "python3.12", "Python 3.12.12")
    monkeypatch.setenv("PATH", str(bin_dir))

    entries = [ToolchainEntry(name="python", version="3.12")]
    with activate(entries):
        assert subprocess.run(
            ["/usr/bin/env", "python3"], capture_output=True, text=True, check=True
        ).stdout == "Python 3.12.12\n"
        verify_installed(entries)


def test_activate_uses_ambient_tool_when_no_versioned_binary_exists(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / "node", "v24.18.1")
    monkeypatch.setenv("PATH", str(bin_dir))

    entries = [ToolchainEntry(name="node", version="24")]
    with activate(entries):
        assert os.environ["PATH"] == str(bin_dir)
        verify_installed(entries)
