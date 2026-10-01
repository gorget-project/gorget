"""End-to-end: git (fetch) -> vendor-bump -> vendor (transform) through the real
PipelineRunner, with mocked subprocess calls -- confirms the pinned dependency
actually reaches the `go mod edit` call before vendoring runs, and that the
final emitted artifact is the vendor archive it produced.
"""

import argparse
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from gorget.cli import resolve_pipeline_spec
from gorget.context import build_run_context
from gorget.pipeline.runner import PipelineRunner

PIPELINE_YAML = """
fetch:
  - type: git
    repo: "https://example.com/example.git"
    ref: "v${VERSION}"
transform:
  - type: vendor-bump
    ecosystem: go
    pins:
      - dependency: "golang.org/x/net"
        version: "0.23.0"
  - type: vendor
    ecosystem: go
"""


def make_ctx(tmp_path, pipeline_yaml, dry_run=False):
    (tmp_path / "foo.spec").write_text(
        "Name: foo\nVersion: 1.2.3\nRelease: 1\nPatch0: 0001-bump-x-net.patch\n"
    )
    # vendor-bump mutates go.mod in the checkout -- gomod_patch_sync.py requires a
    # spec patch replicating that onto the real build tree, or it fails closed.
    (tmp_path / "0001-bump-x-net.patch").write_text(
        "--- a/go.mod\n+++ b/go.mod\n@@ -1 +1 @@\n-old\n+new\n"
    )
    pipeline_file = tmp_path / "pipeline.yaml"
    pipeline_file.write_text(pipeline_yaml)

    args = argparse.Namespace(
        pkg_version="1.2.3",
        old_version=None,
        dry_run=dry_run,
        package_dir=str(tmp_path),
        pipeline_file=str(pipeline_file),
        gpg_keys_dir=str(tmp_path / "gpg-keys"),
        output_dir=str(tmp_path / "output"),
        upstream_repo=None,
    )
    return build_run_context(args)


def _fake_run(calls):
    def run(args, cwd=None, env=None):
        calls.append((args, cwd))
        if args[:2] == ["git", "clone"]:
            dest = Path(args[-1])
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "go.mod").write_text("module example\n\nrequire golang.org/x/net v0.20.0\n")
            (dest / "go.sum").write_text("")
        elif args[:3] == ["go", "list", "-m"]:
            text = (Path(cwd) / "go.mod").read_text()
            version = "v0.23.0" if "v0.23.0" in text else "v0.20.0"
            return subprocess.CompletedProcess(args, 0, "golang.org/x/net " + version, "")
        elif "edit" in args:
            gomod = Path(cwd) / "go.mod"
            gomod.write_text(gomod.read_text().replace("v0.20.0", "v0.23.0"))
        elif args[-3:] == ["go", "mod", "vendor"]:
            vendor_dir = Path(cwd) / "vendor"
            vendor_dir.mkdir(parents=True, exist_ok=True)
            (vendor_dir / "modules.txt").write_text("golang.org/x/net v0.23.0\n")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    return run


def test_git_fetch_then_vendor_bump_then_vendor(tmp_path, mocker):
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    mocker.patch("gorget.transform.vendor.commit_timestamp", return_value=1700000000)
    calls = []
    fake_run = _fake_run(calls)
    mocker.patch("gorget.fetch.git.run", side_effect=fake_run)
    mocker.patch("gorget.dependencies.update.run", side_effect=fake_run)
    mocker.patch("gorget.transform.vendor.go.run", side_effect=fake_run)

    ctx = make_ctx(tmp_path, PIPELINE_YAML)
    spec = resolve_pipeline_spec(ctx)
    report = PipelineRunner(ctx, spec).run()

    fetch_result = next(s for s in report.stages if s.name == "fetch")
    transform_result = next(s for s in report.stages if s.name == "transform")
    assert fetch_result.status == "success"
    assert transform_result.status == "success"

    # The vendor-bump edit ran before vendor ran.
    edit_call = next(c for c in calls if "edit" in c[0])
    assert edit_call[0] == ["go", "mod", "edit", "-require=golang.org/x/net@0.23.0"]

    vendor_call_index = next(i for i, c in enumerate(calls) if c[0][-3:] == ["go", "mod", "vendor"])
    assert calls.index(edit_call) < vendor_call_index

    # Both the git-fetched source tarball and the vendor archive it produced
    # end up as artifacts; the vendor one reflects the pinned dependency.
    output_names = {a.output_name for a in report.artifacts}
    assert output_names == {"foo-1.2.3.tar.gz", "foo-vendor.tar.gz"}

    # Artifacts' original paths live under the pipeline's scratch work_dir,
    # already cleaned up by the time PipelineRunner.run() returns -- read the
    # copies Emit persisted to /output instead.
    output_dir = Path(ctx.output_dir)
    with tarfile.open(output_dir / "foo-vendor.tar.gz") as tar:
        modules_txt_name = next(n for n in tar.getnames() if n.endswith("modules.txt"))
        member = tar.extractfile(modules_txt_name)
        assert member is not None
        assert b"0.23.0" in member.read()

    report_json = json.loads((output_dir / "report.json").read_text())
    assert {a["output_name"] for a in report_json["artifacts"]} == output_names


@pytest.mark.parametrize("auxiliary", [None, "url", "git"])
def test_url_archive_can_be_vendored_without_a_git_checkout(tmp_path, mocker, auxiliary):
    """Downloaded source archives retain their layout and remain immutable."""
    from gorget.util.archive import make_tar_gz

    source = tmp_path / "upstream"
    source.mkdir()
    (source / "Cargo.toml").write_text('[package]\nname = "foo"\nversion = "1.2.3"\n')
    (source / "Cargo.lock").write_text("upstream lockfile\n")
    archive = tmp_path / "upstream.tar.gz"
    make_tar_gz(source, archive, arcname="foo-1.2.3", mtime=1700000000)
    original = archive.read_bytes()
    pipeline = """fetch:
  - type: url
    url: https://example.com/foo-1.2.3.tar.gz
transform:
  - type: vendor
    ecosystem: cargo
    archive_name: foo-vendor.tar.gz
    modules:
      - path: foo-1.2.3
"""
    if auxiliary:
        extra = (
            "  - type: url\n    url: https://example.com/keys.asc\n"
            if auxiliary == "url"
            else "  - type: git\n    repo: https://example.com/keys\n    ref: main\n"
        )
        pipeline = pipeline.replace("transform:", extra + "transform:").replace(
            "    ecosystem: cargo", "    ecosystem: cargo\n    source: foo-1.2.3.tar.gz"
        )
        if auxiliary == "git":
            from gorget.pipeline.artifact import build_input_artifact

            def fetch_keys(step, fetch_ctx):
                keys = fetch_ctx.work_dir / "keys"
                keys.mkdir()
                (keys / "keys.asc").write_text("public keys")
                dest = fetch_ctx.work_dir / "keys.tar.gz"
                make_tar_gz(keys, dest, arcname="keys", mtime=1700000000)
                fetch_ctx.source_dir = keys
                return [build_input_artifact(dest, dest.name, "keys", False)]

            mocker.patch("gorget.fetch.git.GitHandler.run", side_effect=fetch_keys)
    ctx = make_ctx(tmp_path, pipeline)
    mocker.patch(
        "gorget.fetch.url.download_to", side_effect=lambda url, dest: dest.write_bytes(original)
    )

    def vendor(module_dir, *args, **kwargs):
        assert (module_dir / "Cargo.lock").read_text() == "upstream lockfile\n"
        (module_dir / "Cargo.lock").write_text("isolated change\n")
        result = module_dir / "vendor"
        result.mkdir()
        (result / "dependency.txt").write_text("vendored dependency\n")
        return result

    mocker.patch("gorget.transform.vendor.cargo.CargoVendor.vendor", side_effect=vendor)
    report = PipelineRunner(ctx, resolve_pipeline_spec(ctx)).run()
    assert all(stage.status in {"success", "skipped"} for stage in report.stages)
    assert (ctx.output_dir / "foo-1.2.3.tar.gz").read_bytes() == original
    with tarfile.open(ctx.output_dir / "foo-vendor.tar.gz") as tar:
        assert tar.extractfile("vendor/dependency.txt").read() == b"vendored dependency\n"


def test_vendor_source_switch_rejects_uncommitted_source_changes(tmp_path, mocker):
    from gorget.config.schema import VendorStep
    from gorget.exceptions import GorgetConfigError
    from gorget.pipeline.stages.transform import _VendorStepAdapter

    ctx = mocker.Mock(dry_run=False)
    state = mocker.Mock()
    from gorget.pipeline.source import SourceWorkspace

    state.source = SourceWorkspace(path=tmp_path, dirty=True)
    state.artifacts = [mocker.Mock(output_name="source.tar.gz")]
    with pytest.raises(GorgetConfigError, match="uncommitted changes"):
        _VendorStepAdapter().run(VendorStep(ecosystem="cargo", source="source.tar.gz"), ctx, state)
