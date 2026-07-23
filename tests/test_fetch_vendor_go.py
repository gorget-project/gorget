import subprocess

import pytest

from gorget.config.schema import ToolchainEntry
from gorget.exceptions import GorgetTransientError
from gorget.fetch.vendor.go import GoVendor


def test_go_vendor_runs_go_mod_vendor(tmp_path, mocker):
    mock_run = mocker.patch(
        "gorget.fetch.vendor.go.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    result = GoVendor().vendor(tmp_path)
    mock_run.assert_called_once_with(["go", "mod", "vendor"], cwd=tmp_path)
    assert result == tmp_path / "vendor"


def test_go_vendor_toolchain_param_does_not_change_command(tmp_path, mocker):
    # toolchain activation isn't implemented yet (gorget/toolchain.py); the
    # param is accepted but wrap_command() is currently a no-op passthrough.
    mock_run = mocker.patch(
        "gorget.fetch.vendor.go.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    GoVendor().vendor(tmp_path, toolchain=[ToolchainEntry(name="go", version="1.22.0")])
    mock_run.assert_called_once_with(["go", "mod", "vendor"], cwd=tmp_path)


def test_go_vendor_raises_on_failure(tmp_path, mocker):
    mocker.patch(
        "gorget.fetch.vendor.go.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="go.mod not found"
        ),
    )
    with pytest.raises(GorgetTransientError, match="go.mod not found"):
        GoVendor().vendor(tmp_path)
