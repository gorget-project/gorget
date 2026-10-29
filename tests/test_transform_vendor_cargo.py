import subprocess

import pytest

from gorget.exceptions import GorgetTransientError
from gorget.transform.vendor.cargo import CargoVendor


def test_cargo_vendor_runs_cargo_vendor(tmp_path, mocker):
    config = '[source.crates-io]\nreplace-with = "vendored-sources"\n'
    mock_run = mocker.patch(
        "gorget.transform.vendor.cargo.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=config, stderr=""),
    )
    result = CargoVendor().vendor(tmp_path)
    mock_run.assert_called_once_with(["cargo", "vendor", "vendor"], cwd=tmp_path)
    assert result == tmp_path / "vendor"
    assert (tmp_path / "vendor-config.toml").read_text() == config


def test_cargo_vendor_raises_on_failure(tmp_path, mocker):
    mocker.patch(
        "gorget.transform.vendor.cargo.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Cargo.toml not found"
        ),
    )
    with pytest.raises(GorgetTransientError, match="Cargo.toml not found"):
        CargoVendor().vendor(tmp_path)
    assert not (tmp_path / "vendor-config.toml").exists()


def test_cargo_vendor_includes_source_config_in_archive(tmp_path):
    assert CargoVendor().archive_root_files(tmp_path) == [tmp_path / "vendor-config.toml"]
