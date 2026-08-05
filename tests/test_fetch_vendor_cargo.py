import subprocess

import pytest

from gorget.exceptions import GorgetTransientError
from gorget.fetch.vendor.cargo import CargoVendor


def test_cargo_vendor_runs_cargo_vendor(tmp_path, mocker):
    mock_run = mocker.patch(
        "gorget.fetch.vendor.cargo.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    result = CargoVendor().vendor(tmp_path)
    mock_run.assert_called_once_with(["cargo", "vendor", str(tmp_path / "vendor")], cwd=tmp_path)
    assert result == tmp_path / "vendor"


def test_cargo_vendor_raises_on_failure(tmp_path, mocker):
    mocker.patch(
        "gorget.fetch.vendor.cargo.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Cargo.toml not found"
        ),
    )
    with pytest.raises(GorgetTransientError, match="Cargo.toml not found"):
        CargoVendor().vendor(tmp_path)


def test_cargo_vendor_has_no_archive_root_files(tmp_path):
    # No known equivalent to go-vendor-tools' archive-layout requirement
    # (see GoVendor.archive_root_files) for this ecosystem.
    assert CargoVendor().archive_root_files(tmp_path) == []
