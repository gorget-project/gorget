import subprocess

import pytest

from gorget.config.schema import ToolchainEntry
from gorget.exceptions import GorgetTransientError
from gorget.fetch.vendor.go import GoVendor


def _ok(args=None):
    return subprocess.CompletedProcess(args=args or [], returncode=0, stdout="", stderr="")


def test_go_vendor_runs_tidy_then_vendor_by_default(tmp_path, mocker):
    mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
    result = GoVendor().vendor(tmp_path)
    assert mock_run.call_args_list == [
        mocker.call(["go", "mod", "tidy"], cwd=tmp_path),
        mocker.call(["go", "mod", "vendor"], cwd=tmp_path),
    ]
    assert result == tmp_path / "vendor"


def test_go_vendor_missing_config_file_behaves_like_no_package_dir(tmp_path, mocker):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
    GoVendor().vendor(tmp_path, package_dir=package_dir)
    assert mock_run.call_args_list == [
        mocker.call(["go", "mod", "tidy"], cwd=tmp_path),
        mocker.call(["go", "mod", "vendor"], cwd=tmp_path),
    ]


def test_go_vendor_toolchain_param_does_not_change_command(tmp_path, mocker):
    # toolchain activation isn't implemented yet (gorget/toolchain.py); the
    # param is accepted but wrap_command() is currently a no-op passthrough.
    mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
    GoVendor().vendor(tmp_path, toolchain=[ToolchainEntry(name="go", version="1.22.0")])
    assert mock_run.call_args_list == [
        mocker.call(["go", "mod", "tidy"], cwd=tmp_path),
        mocker.call(["go", "mod", "vendor"], cwd=tmp_path),
    ]


def test_go_vendor_raises_on_vendor_failure(tmp_path, mocker):
    mocker.patch(
        "gorget.fetch.vendor.go.run",
        side_effect=[_ok(), subprocess.CompletedProcess([], 1, "", "go.mod not found")],
    )
    with pytest.raises(GorgetTransientError, match="go.mod not found"):
        GoVendor().vendor(tmp_path)


def test_go_vendor_raises_on_tidy_failure(tmp_path, mocker):
    mocker.patch(
        "gorget.fetch.vendor.go.run",
        return_value=subprocess.CompletedProcess([], 1, "", "tidy exploded"),
    )
    with pytest.raises(GorgetTransientError, match="tidy exploded"):
        GoVendor().vendor(tmp_path)


class TestGoVendorToolsConfig:
    """go-vendor-tools.toml's `[archive]` table must be applied the same way
    go-vendor-tools' own `create_archive` applies it -- pre_commands, then
    dependency_overrides (via `go get <path>@<version>`), then `go mod tidy`
    if enabled, then `go mod vendor`, then post_commands -- so a package's
    vendored dependencies don't silently change just because gorget produced
    the archive instead of go-vendor-tools directly. Regression coverage for
    a real gap found migrating cosign: gorget previously ran plain `go mod
    vendor` and ignored this file entirely, silently reverting a CVE-pinned
    dependency_overrides entry and skipping a required post_commands step.
    """

    def _config(self, package_dir, text):
        (package_dir / "go-vendor-tools.toml").write_text(text)

    def test_applies_dependency_overrides_via_go_get(self, tmp_path, mocker):
        package_dir = tmp_path / "pkg"
        package_dir.mkdir()
        self._config(
            package_dir,
            '[archive.dependency_overrides]\n"golang.org/x/text" = "v0.39.0"\n',
        )
        mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
        GoVendor().vendor(tmp_path, package_dir=package_dir)
        assert mock_run.call_args_list == [
            mocker.call(["go", "get", "golang.org/x/text@v0.39.0"], cwd=tmp_path),
            mocker.call(["go", "mod", "tidy"], cwd=tmp_path),
            mocker.call(["go", "mod", "vendor"], cwd=tmp_path),
        ]

    def test_runs_post_commands_after_vendor(self, tmp_path, mocker):
        package_dir = tmp_path / "pkg"
        package_dir.mkdir()
        self._config(
            package_dir,
            '[archive]\npost_commands = [["cp", "-p", "a/LICENSE", "b/LICENSE"]]\n',
        )
        mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
        GoVendor().vendor(tmp_path, package_dir=package_dir)
        assert mock_run.call_args_list == [
            mocker.call(["go", "mod", "tidy"], cwd=tmp_path),
            mocker.call(["go", "mod", "vendor"], cwd=tmp_path),
            mocker.call(["cp", "-p", "a/LICENSE", "b/LICENSE"], cwd=tmp_path),
        ]

    def test_runs_pre_commands_before_everything_else(self, tmp_path, mocker):
        package_dir = tmp_path / "pkg"
        package_dir.mkdir()
        self._config(package_dir, '[archive]\npre_commands = [["echo", "prep"]]\n')
        mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
        GoVendor().vendor(tmp_path, package_dir=package_dir)
        assert mock_run.call_args_list == [
            mocker.call(["echo", "prep"], cwd=tmp_path),
            mocker.call(["go", "mod", "tidy"], cwd=tmp_path),
            mocker.call(["go", "mod", "vendor"], cwd=tmp_path),
        ]

    def test_tidy_false_skips_tidy(self, tmp_path, mocker):
        package_dir = tmp_path / "pkg"
        package_dir.mkdir()
        self._config(package_dir, "[archive]\ntidy = false\n")
        mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
        GoVendor().vendor(tmp_path, package_dir=package_dir)
        assert mock_run.call_args_list == [mocker.call(["go", "mod", "vendor"], cwd=tmp_path)]

    def test_raises_on_post_command_failure(self, tmp_path, mocker):
        package_dir = tmp_path / "pkg"
        package_dir.mkdir()
        self._config(package_dir, '[archive]\npost_commands = [["false"]]\n')
        mocker.patch(
            "gorget.fetch.vendor.go.run",
            side_effect=[_ok(), _ok(), subprocess.CompletedProcess([], 1, "", "no such file")],
        )
        with pytest.raises(GorgetTransientError, match="no such file"):
            GoVendor().vendor(tmp_path, package_dir=package_dir)
