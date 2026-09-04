import subprocess

import pytest

from gorget.config.schema import ToolchainEntry
from gorget.exceptions import GorgetConfigError, GorgetTransientError
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


def test_go_vendor_use_workspace_false_forces_gowork_off_even_at_workspace_root(tmp_path, mocker):
    """Regression test: some packages have a go.work at the module root but
    deliberately don't want it applied to their vendor archive -- confirmed
    empirically for prometheus, which excludes workspace members like
    compliance/internal/tools (`go work vendor` pulls them in;
    `GOWORK=off go mod vendor` doesn't). `use_workspace=False` must force the
    isolated single-module path even though go.work is right here in
    `module_dir`, not just in an ancestor.
    """
    (tmp_path / "go.work").touch()
    mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
    GoVendor().vendor(tmp_path, use_workspace=False)
    assert mock_run.call_args_list == [
        mocker.call(["go", "mod", "tidy"], cwd=tmp_path, env=_OFF),
        mocker.call(["go", "mod", "vendor"], cwd=tmp_path, env=_OFF),
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


class TestGomodPatchSync:
    """Regression coverage for the bug that broke trivy: go-vendor-tools.toml's
    pre_commands/dependency_overrides mutate go.mod/go.sum only in this vendor
    checkout, since gorget's `fetch: {git}` step already archived Source0 from
    the checkout before `vendor:` ran. Without a spec patch replicating the same
    change, the plain source tree and the vendor archive can require different
    versions of the same dependency -- `go build -mod=vendor` then rejects it as
    inconsistent vendoring. See GoVendor._validate_gomod_patch_sync's docstring.
    """

    def _spec_with_patch(self, package_dir, patch_touches_gomod):
        (package_dir / "pkg.spec").write_text("Patch0: 0001-fix.patch\n")
        target = "go.mod" if patch_touches_gomod else "main.go"
        (package_dir / "0001-fix.patch").write_text(
            f"--- a/{target}\n+++ b/{target}\n@@ -1 +1 @@\n-old\n+new\n"
        )

    def test_go_get_precommand_with_matching_patch_is_allowed(self, tmp_path, mocker):
        package_dir = tmp_path / "pkg"
        package_dir.mkdir()
        (package_dir / "go-vendor-tools.toml").write_text(
            '[archive]\npre_commands = [["go", "get", "golang.org/x/text@v0.39.0"]]\n'
        )
        self._spec_with_patch(package_dir, patch_touches_gomod=True)
        mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
        GoVendor().vendor(tmp_path, package_dir=package_dir)
        assert mock_run.call_args_list[0] == mocker.call(
            ["go", "get", "golang.org/x/text@v0.39.0"], cwd=tmp_path, env=_OFF
        )

    def test_go_get_precommand_without_matching_patch_raises(self, tmp_path, mocker):
        package_dir = tmp_path / "pkg"
        package_dir.mkdir()
        (package_dir / "go-vendor-tools.toml").write_text(
            '[archive]\npre_commands = [["go", "get", "golang.org/x/text@v0.39.0"]]\n'
        )
        self._spec_with_patch(package_dir, patch_touches_gomod=False)
        mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
        with pytest.raises(GorgetConfigError, match="pre_commands or dependency_overrides"):
            GoVendor().vendor(tmp_path, package_dir=package_dir)
        mock_run.assert_not_called()

    def test_dependency_override_without_matching_patch_raises(self, tmp_path, mocker):
        package_dir = tmp_path / "pkg"
        package_dir.mkdir()
        (package_dir / "go-vendor-tools.toml").write_text(
            '[archive.dependency_overrides]\n"golang.org/x/text" = "v0.39.0"\n'
        )
        self._spec_with_patch(package_dir, patch_touches_gomod=False)
        mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
        with pytest.raises(GorgetConfigError, match="pre_commands or dependency_overrides"):
            GoVendor().vendor(tmp_path, package_dir=package_dir)
        mock_run.assert_not_called()

    def test_precommand_not_touching_gomod_is_allowed_without_a_patch(self, tmp_path, mocker):
        package_dir = tmp_path / "pkg"
        package_dir.mkdir()
        (package_dir / "go-vendor-tools.toml").write_text(
            '[archive]\npre_commands = [["echo", "prep"]]\n'
        )
        (package_dir / "pkg.spec").write_text("Name: pkg\n")
        mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
        GoVendor().vendor(tmp_path, package_dir=package_dir)
        assert mock_run.call_args_list[0] == mocker.call(["echo", "prep"], cwd=tmp_path, env=_OFF)

    def test_missing_spec_skips_validation_instead_of_crashing(self, tmp_path, mocker):
        # A malformed package layout (no spec, or more than one) isn't this
        # check's problem to report -- whatever reads the spec next will fail
        # with a clearer, more specific error.
        package_dir = tmp_path / "pkg"
        package_dir.mkdir()
        (package_dir / "go-vendor-tools.toml").write_text(
            '[archive]\npre_commands = [["go", "get", "golang.org/x/text@v0.39.0"]]\n'
        )
        mock_run = mocker.patch("gorget.fetch.vendor.go.run", return_value=_ok())
        GoVendor().vendor(tmp_path, package_dir=package_dir)
        assert mock_run.call_args_list[0] == mocker.call(
            ["go", "get", "golang.org/x/text@v0.39.0"], cwd=tmp_path, env=_OFF
        )


class TestArchiveRootFiles:
    """Regression coverage for a real gap found migrating grafana13.1: a
    vendor archive containing only "vendor/" gets mis-extracted by
    `go_vendor_license --use-archive` (it has a single common top-level
    directory, so the tool treats it as an independently-wrapped sibling
    archive instead of nesting it inside the source tree) -- which made
    every one of go-vendor-tools.toml's correctly-pinned license file
    checksums come up as unexpectedly "changed" in %check, even though the
    vendor content itself was byte-identical to what the pinned hashes
    expected. See GoVendor.archive_root_files's docstring for the full
    mechanism.
    """

    def test_returns_go_mod_and_go_sum_for_a_plain_module(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/x")
        (tmp_path / "go.sum").write_text("checksums")
        assert set(GoVendor().archive_root_files(tmp_path)) == {
            tmp_path / "go.mod",
            tmp_path / "go.sum",
        }

    def test_omits_go_sum_when_absent(self, tmp_path):
        # A module with zero external dependencies has no go.sum at all --
        # existence, not a hardcoded required/optional split, decides
        # inclusion (matches go-vendor-tools' own OPTIONAL_FILES treatment).
        (tmp_path / "go.mod").write_text("module example.com/x")
        assert GoVendor().archive_root_files(tmp_path) == [tmp_path / "go.mod"]

    def test_includes_go_work_files_for_a_workspace(self, tmp_path):
        (tmp_path / "go.work").write_text("go 1.22\n")
        (tmp_path / "go.work.sum").write_text("checksums")
        (tmp_path / "go.mod").write_text("module example.com/x")
        (tmp_path / "go.sum").write_text("checksums")
        assert set(GoVendor().archive_root_files(tmp_path)) == {
            tmp_path / "go.work",
            tmp_path / "go.work.sum",
            tmp_path / "go.mod",
            tmp_path / "go.sum",
        }

    def test_returns_empty_list_when_nothing_exists(self, tmp_path):
        assert GoVendor().archive_root_files(tmp_path) == []
