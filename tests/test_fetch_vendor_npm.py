import subprocess

import pytest

from gorget.exceptions import GorgetTransientError
from gorget.fetch.vendor.npm import NpmVendor


def test_npm_vendor_runs_install_ignore_scripts(tmp_path, mocker):
    mock_run = mocker.patch(
        "gorget.fetch.vendor.npm.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    result = NpmVendor().vendor(tmp_path)
    args = mock_run.call_args.args[0]
    assert args[:2] == ["npm", "install"]
    assert "--ignore-scripts" in args
    assert mock_run.call_args.kwargs == {"cwd": tmp_path}
    assert result == tmp_path / "node_modules"


def test_npm_vendor_raises_on_failure(tmp_path, mocker):
    mocker.patch(
        "gorget.fetch.vendor.npm.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="package.json not found"
        ),
    )
    with pytest.raises(GorgetTransientError, match="package.json not found"):
        NpmVendor().vendor(tmp_path)
