import subprocess

import pytest

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


def test_go_vendor_raises_on_failure(tmp_path, mocker):
    mocker.patch(
        "gorget.fetch.vendor.go.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="go.mod not found"
        ),
    )
    with pytest.raises(GorgetTransientError, match="go.mod not found"):
        GoVendor().vendor(tmp_path)
