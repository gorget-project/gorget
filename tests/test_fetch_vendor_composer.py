import subprocess

import pytest

from gorget.exceptions import GorgetTransientError
from gorget.fetch.vendor.composer import ComposerVendor


def test_composer_vendor_runs_install_no_dev(tmp_path, mocker):
    mock_run = mocker.patch(
        "gorget.fetch.vendor.composer.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    result = ComposerVendor().vendor(tmp_path)
    args = mock_run.call_args.args[0]
    assert args[:2] == ["composer", "install"]
    assert "--no-dev" in args
    assert result == tmp_path / "vendor"


def test_composer_vendor_raises_on_failure(tmp_path, mocker):
    mocker.patch(
        "gorget.fetch.vendor.composer.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="composer.json not found"
        ),
    )
    with pytest.raises(GorgetTransientError, match="composer.json not found"):
        ComposerVendor().vendor(tmp_path)
