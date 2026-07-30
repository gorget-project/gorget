"""End-to-end: git (fetch) -> post (run) through the real PipelineRunner, with
a mocked git clone -- confirms the full pipeline (not just PostStage in
isolation) actually writes the post step's effect into the real
`--package-dir`, not the pipeline's scratch work_dir which is cleaned up by
the time `PipelineRunner.run()` returns.
"""

import argparse
import subprocess
from pathlib import Path

from gorget.cli import resolve_pipeline_spec
from gorget.context import build_run_context
from gorget.pipeline.runner import PipelineRunner

PIPELINE_YAML = """
fetch:
  - type: git
    repo: "https://example.com/example.git"
    ref: "v${VERSION}"
post:
  - type: run
    command: ["sh", "-c", "echo ${VERSION} > post-marker.txt"]
"""


def make_ctx(tmp_path, pipeline_yaml, dry_run=False):
    (tmp_path / "foo.spec").write_text("Name: foo\nVersion: 1.2.3\nRelease: 1\n")
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


def _fake_git_clone(calls):
    def run(args, cwd=None, env=None):
        calls.append((args, cwd))
        if args[:2] == ["git", "clone"]:
            dest = Path(args[-1])
            dest.mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    return run


def test_git_fetch_then_post_writes_into_real_package_dir(tmp_path, mocker):
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    calls = []
    mocker.patch("gorget.fetch.git.run", side_effect=_fake_git_clone(calls))

    ctx = make_ctx(tmp_path, PIPELINE_YAML)
    spec = resolve_pipeline_spec(ctx)
    report = PipelineRunner(ctx, spec).run()

    fetch_result = next(s for s in report.stages if s.name == "fetch")
    post_result = next(s for s in report.stages if s.name == "post")
    assert fetch_result.status == "success"
    assert post_result.status == "success"

    # The marker lands in the real --package-dir, not the pipeline's scratch
    # work_dir (already cleaned up by the time PipelineRunner.run() returns).
    assert (tmp_path / "post-marker.txt").read_text() == "1.2.3\n"


ARTIFACT_PIPELINE_YAML = """
fetch:
  - type: git
    repo: "https://example.com/example.git"
    ref: "v${VERSION}"
    archive_name: "foo-${VERSION}.tar.gz"
post:
  - type: run
    artifacts: ["foo-${VERSION}.tar.gz"]
    command: ["sh", "-c", "cat foo-${VERSION}.tar.gz > post-read.txt"]
"""


def test_post_artifacts_field_materializes_fetched_artifact_via_real_runner(tmp_path, mocker):
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    calls = []
    mocker.patch("gorget.fetch.git.run", side_effect=_fake_git_clone(calls))

    ctx = make_ctx(tmp_path, ARTIFACT_PIPELINE_YAML)
    spec = resolve_pipeline_spec(ctx)
    report = PipelineRunner(ctx, spec).run()

    post_result = next(s for s in report.stages if s.name == "post")
    assert post_result.status == "success"

    # The fetched archive itself, and the post step's read of it, both land
    # in the real --package-dir -- the archive only exists in gorget's
    # scratch work_dir otherwise, which is gone by the time run() returns.
    assert (tmp_path / "foo-1.2.3.tar.gz").exists()
    assert (tmp_path / "post-read.txt").read_bytes() == (tmp_path / "foo-1.2.3.tar.gz").read_bytes()


def test_dry_run_skips_post_and_leaves_package_dir_untouched(tmp_path, mocker):
    mocker.patch("gorget.fetch.git.commit_timestamp", return_value=1700000000)
    calls = []
    mocker.patch("gorget.fetch.git.run", side_effect=_fake_git_clone(calls))

    ctx = make_ctx(tmp_path, PIPELINE_YAML, dry_run=True)
    spec = resolve_pipeline_spec(ctx)
    report = PipelineRunner(ctx, spec).run()

    post_result = next(s for s in report.stages if s.name == "post")
    assert post_result.status == "skipped"
    assert not (tmp_path / "post-marker.txt").exists()
