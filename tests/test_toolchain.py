import os
import subprocess
from pathlib import Path

import pytest

from gorget.config.schema import ToolchainEntry
from gorget.exceptions import GorgetConfigError
from gorget.toolchain import _rpm_owned, activate, verify_installed, wrap_command


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_rpm_ownership_check_uses_absolute_trusted_command(tmp_path, monkeypatch, mocker):
    mock_run = mocker.patch("gorget.toolchain.run", return_value=_completed())
    monkeypatch.setattr("gorget.toolchain._RPM_BINDIR", Path("/trusted/bin"))
    candidate = tmp_path / "node-24"

    assert _rpm_owned(candidate)
    mock_run.assert_called_once_with(["/trusted/bin/rpm", "-qf", str(candidate)])


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


def test_verify_installed_accepts_version_above_minimum(mocker):
    mocker.patch("gorget.toolchain.run", return_value=_completed(stdout="v24.18.1\n"))

    verify_installed(
        [ToolchainEntry(name="node", version="24", minimum_version="24.16")]
    )


def test_verify_installed_rejects_version_below_minimum(mocker):
    mocker.patch("gorget.toolchain.run", return_value=_completed(stdout="v24.15.9\n"))

    with pytest.raises(GorgetConfigError, match="needs at least version 24.16"):
        verify_installed(
            [ToolchainEntry(name="node", version="24", minimum_version="24.16")]
        )


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


def test_verify_installed_gradle_version_format(mocker):
    mocker.patch("gorget.toolchain.run", return_value=_completed(stdout="Gradle 8.10.2\n"))
    verify_installed([ToolchainEntry(name="gradle", version="8.10")])


def test_verify_installed_unknown_tool_name_raises(mocker):
    mock_run = mocker.patch("gorget.toolchain.run")
    with pytest.raises(GorgetConfigError, match="Unknown toolchain name"):
        verify_installed([ToolchainEntry(name="ruby", version="3.2")])
    mock_run.assert_not_called()


def test_invalid_declared_version_is_rejected_before_executable_lookup(mocker):
    mock_rpm_owned = mocker.patch("gorget.toolchain._rpm_owned")
    entry = ToolchainEntry(name="node", version="../../tmp/untrusted")

    with pytest.raises(GorgetConfigError, match="Invalid version"):
        with activate([entry]):
            pass

    mock_rpm_owned.assert_not_called()


def test_invalid_minimum_version_is_rejected(mocker):
    mock_run = mocker.patch("gorget.toolchain.run")
    entry = ToolchainEntry(name="node", version="24", minimum_version=">=24.16")

    with pytest.raises(GorgetConfigError, match="Invalid minimum-version"):
        verify_installed([entry])

    mock_run.assert_not_called()


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
    monkeypatch.setattr("gorget.toolchain._RPM_BINDIR", bin_dir)
    monkeypatch.setattr("gorget.toolchain._rpm_owned", lambda path: True)

    entries = [ToolchainEntry(name="node", version="24", minimum_version="24.16")]
    with activate(entries):
        shim_dir = Path(os.environ["PATH"].split(os.pathsep)[0])
        assert shim_dir.name.startswith("gorget-toolchain-")
        assert Path(os.readlink(shim_dir / "node")).is_absolute()
        assert subprocess.run(
            ["/usr/bin/env", "node"], capture_output=True, text=True, check=True
        ).stdout == "v24.18.1\n"
        assert subprocess.run(
            ["/usr/bin/env", "npm"], capture_output=True, text=True, check=True
        ).stdout == "11.6.2\n"
        verify_installed(entries)

    assert os.environ["PATH"] == str(bin_dir)


@pytest.mark.parametrize("missing", ["npm-24", "npx-24"])
def test_activate_rejects_partial_node_rpm_toolchain(tmp_path, monkeypatch, missing):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, output in (
        ("node-24", "v24.18.1"),
        ("npm-24", "11.6.2"),
        ("npx-24", "11.6.2"),
    ):
        if name != missing:
            _executable(bin_dir / name, output)
    monkeypatch.setattr("gorget.toolchain._RPM_BINDIR", bin_dir)
    monkeypatch.setattr("gorget.toolchain._rpm_owned", lambda path: True)

    with pytest.raises(
        GorgetConfigError,
        match=rf"node-24 is installed but {missing} is missing",
    ):
        with activate([ToolchainEntry(name="node", version="24")]):
            pass


def test_activate_selects_installed_python_rpm_binary(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / "python3.12", "Python 3.12.12")
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr("gorget.toolchain._RPM_BINDIR", bin_dir)
    monkeypatch.setattr("gorget.toolchain._rpm_owned", lambda path: True)

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
    monkeypatch.setattr("gorget.toolchain._RPM_BINDIR", tmp_path / "empty-rpm-bindir")

    entries = [ToolchainEntry(name="node", version="24")]
    with activate(entries):
        assert os.environ["PATH"] == str(bin_dir)
        verify_installed(entries)


def test_activate_ignores_non_rpm_versioned_binary(tmp_path, monkeypatch):
    ambient_dir = tmp_path / "ambient"
    rpm_bin_dir = tmp_path / "rpm-bin"
    ambient_dir.mkdir()
    rpm_bin_dir.mkdir()
    _executable(ambient_dir / "node", "v24.18.1")
    _executable(rpm_bin_dir / "node-24", "v24.99.0")
    monkeypatch.setenv("PATH", f"{rpm_bin_dir}{os.pathsep}{ambient_dir}")
    monkeypatch.setattr("gorget.toolchain._RPM_BINDIR", rpm_bin_dir)
    monkeypatch.setattr("gorget.toolchain._rpm_owned", lambda path: False)

    entries = [ToolchainEntry(name="node", version="24", minimum_version="24.16")]
    with activate(entries):
        assert os.environ["PATH"] == f"{rpm_bin_dir}{os.pathsep}{ambient_dir}"
        verify_installed(entries)


def test_activate_restores_path_and_removes_shims_after_failure(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / "node-24", "v24.18.1")
    _executable(bin_dir / "npm-24", "11.6.2")
    _executable(bin_dir / "npx-24", "11.6.2")
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr("gorget.toolchain._RPM_BINDIR", bin_dir)
    monkeypatch.setattr("gorget.toolchain._rpm_owned", lambda path: True)
    shim_dir = None

    with pytest.raises(RuntimeError, match="stage failed"):
        with activate([ToolchainEntry(name="node", version="24")]):
            shim_dir = Path(os.environ["PATH"].split(os.pathsep)[0])
            raise RuntimeError("stage failed")

    assert os.environ["PATH"] == str(bin_dir)
    assert shim_dir is not None
    assert not shim_dir.exists()
