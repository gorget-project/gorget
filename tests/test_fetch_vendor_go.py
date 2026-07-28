import subprocess

import pytest

from gorget.config.schema import ToolchainEntry
from gorget.exceptions import GorgetTransientError
from gorget.fetch.vendor.go import GoVendor

_OFF = {"GOWORK": "off"}


def _ok(args=None):
    return subprocess.CompletedProcess(args=args or [], returncode=0, stdout="", stderr="")


def test_go_vendor_runs_tidy_then_vendor_by_default(tmp_path, mocker):
    mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
    result = GoVendor().vendor(tmp_path)
    assert mock_run.call_args_list == [
        mocker.call(["go", "mod", "tidy"], cwd=tmp_path, env=_OFF),
        mocker.call(["go", "mod", "vendor"], cwd=tmp_path, env=_OFF),
    ]
    assert result == tmp_path / "vendor"


def test_go_vendor_uses_go_work_vendor_in_workspace_mode(tmp_path, mocker):
    """Regression test: `go mod tidy`/`go mod vendor` refuse to run at all in
    a Go workspace ("cannot be run in workspace mode"), which broke every
    workspace-based package (found migrating grafana, kubernetes, prometheus).
    A `go.work` file at the module root means `go work vendor` is the only
    valid vendor command -- tidy doesn't apply in workspace mode either.
    """
    (tmp_path / "go.work").touch()
    mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
    result = GoVendor().vendor(tmp_path)
    assert mock_run.call_args_list == [
        mocker.call(["go", "work", "vendor"], cwd=tmp_path, env=None)
    ]
    assert result == tmp_path / "vendor"


def test_go_vendor_go_work_takes_priority_over_dependency_overrides_and_post_commands(
    tmp_path, mocker
):
    (tmp_path / "go.work").touch()
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    (package_dir / "go-vendor-tools.toml").write_text(
        '[archive]\npost_commands = [["echo", "done"]]\n'
        '[archive.dependency_overrides]\n"golang.org/x/text" = "v0.39.0"\n'
    )
    mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
    GoVendor().vendor(tmp_path, package_dir=package_dir)
    assert mock_run.call_args_list == [
        mocker.call(["go", "get", "golang.org/x/text@v0.39.0"], cwd=tmp_path, env=None),
        mocker.call(["go", "work", "vendor"], cwd=tmp_path, env=None),
        mocker.call(["echo", "done"], cwd=tmp_path, env=None),
    ]


def test_go_vendor_forces_gowork_off_when_module_is_under_an_ancestor_workspace(tmp_path, mocker):
    """Regression test: Go finds the *nearest* go.work by searching upward
    from cwd, so vendoring a submodule of a larger workspace (e.g. etcd's
    server/etcdctl/etcdutl, each vendored into its own archive even though
    the repo root has its own go.work) would otherwise be swept into that
    ancestor's workspace mode too, hitting the same "cannot be run in
    workspace mode" error as the root itself. There's no go.work directly in
    `module_dir` here (only in its parent), so this must force GOWORK=off
    rather than run `go work vendor` -- matching how these packages are
    actually built (e.g. etcd's spec sets GOWORK=off for the equivalent
    build-time step).
    """
    (tmp_path / "go.work").touch()
    module_dir = tmp_path / "server"
    module_dir.mkdir()
    mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
    GoVendor().vendor(module_dir)
    assert mock_run.call_args_list == [
        mocker.call(["go", "mod", "tidy"], cwd=module_dir, env=_OFF),
        mocker.call(["go", "mod", "vendor"], cwd=module_dir, env=_OFF),
    ]


def test_go_vendor_missing_config_file_behaves_like_no_package_dir(tmp_path, mocker):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
    GoVendor().vendor(tmp_path, package_dir=package_dir)
    assert mock_run.call_args_list == [
        mocker.call(["go", "mod", "tidy"], cwd=tmp_path, env=_OFF),
        mocker.call(["go", "mod", "vendor"], cwd=tmp_path, env=_OFF),
    ]


def test_go_vendor_toolchain_param_does_not_change_command(tmp_path, mocker):
    # toolchain activation isn't implemented yet (gorget/toolchain.py); the
    # param is accepted but wrap_command() is currently a no-op passthrough.
    mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
    GoVendor().vendor(tmp_path, toolchain=[ToolchainEntry(name="go", version="1.22.0")])
    assert mock_run.call_args_list == [
        mocker.call(["go", "mod", "tidy"], cwd=tmp_path, env=_OFF),
        mocker.call(["go", "mod", "vendor"], cwd=tmp_path, env=_OFF),
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
            mocker.call(["go", "get", "golang.org/x/text@v0.39.0"], cwd=tmp_path, env=_OFF),
            mocker.call(["go", "mod", "tidy"], cwd=tmp_path, env=_OFF),
            mocker.call(["go", "mod", "vendor"], cwd=tmp_path, env=_OFF),
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
            mocker.call(["go", "mod", "tidy"], cwd=tmp_path, env=_OFF),
            mocker.call(["go", "mod", "vendor"], cwd=tmp_path, env=_OFF),
            mocker.call(["cp", "-p", "a/LICENSE", "b/LICENSE"], cwd=tmp_path, env=_OFF),
        ]

    def test_runs_pre_commands_before_everything_else(self, tmp_path, mocker):
        package_dir = tmp_path / "pkg"
        package_dir.mkdir()
        self._config(package_dir, '[archive]\npre_commands = [["echo", "prep"]]\n')
        mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
        GoVendor().vendor(tmp_path, package_dir=package_dir)
        assert mock_run.call_args_list == [
            mocker.call(["echo", "prep"], cwd=tmp_path, env=_OFF),
            mocker.call(["go", "mod", "tidy"], cwd=tmp_path, env=_OFF),
            mocker.call(["go", "mod", "vendor"], cwd=tmp_path, env=_OFF),
        ]

    def test_tidy_false_skips_tidy(self, tmp_path, mocker):
        package_dir = tmp_path / "pkg"
        package_dir.mkdir()
        self._config(package_dir, "[archive]\ntidy = false\n")
        mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
        GoVendor().vendor(tmp_path, package_dir=package_dir)
        assert mock_run.call_args_list == [
            mocker.call(["go", "mod", "vendor"], cwd=tmp_path, env=_OFF)
        ]

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
