"""End-to-end: fetch (two artifacts) -> transform: run: with target: and
discovered-outputs: through the real PipelineRunner. Confirms `target:`
correctly selects one specific fetched artifact to extract when more than one
was fetched (previously impossible -- `ensure_source_dir()` would raise), and
that `discovered-outputs:` picks up artifacts whose name isn't known until the
command runs.
"""

import argparse
import io
import tarfile

from gorget.cli import resolve_pipeline_spec
from gorget.context import build_run_context
from gorget.pipeline.runner import PipelineRunner

PIPELINE_YAML = """
fetch:
  - type: url
    url: "https://example.com/tarball-${VERSION}.tar.gz"
  - type: url
    url: "https://example.com/SHASUMS256.txt"
transform:
  - type: run
    target: "tarball-${VERSION}.tar.gz"
    command:
      - "sh"
      - "-c"
      - |
        echo b-bytes > b.zip
        echo l-bytes > l.zip
        printf 'discovered-b.zip\\tb.zip\\ndiscovered-l.zip\\tl.zip\\n' > manifest.tsv
    discovered-outputs: "manifest.tsv"
"""


def _make_tar_gz_bytes(arcname: str, filename: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name=f"{arcname}/{filename}")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def make_ctx(tmp_path, pipeline_yaml):
    (tmp_path / "foo.spec").write_text("Name: foo\nVersion: 1.2.3\nRelease: 1\n")
    pipeline_file = tmp_path / "pipeline.yaml"
    pipeline_file.write_text(pipeline_yaml)
    args = argparse.Namespace(
        pkg_version="1.2.3",
        old_version=None,
        dry_run=False,
        package_dir=str(tmp_path),
        pipeline_file=str(pipeline_file),
        gpg_keys_dir=str(tmp_path / "gpg-keys"),
        output_dir=str(tmp_path / "output"),
        upstream_repo=None,
    )
    return build_run_context(args)


def test_target_and_discovered_outputs_through_real_runner(tmp_path, mocker):
    tarball_bytes = _make_tar_gz_bytes("extracted", "marker.txt", b"tarball contents")

    def fake_download(url, dest):
        if url.endswith("SHASUMS256.txt"):
            dest.write_text("not a tarball, just a checksums listing\n")
        else:
            dest.write_bytes(tarball_bytes)

    mocker.patch("gorget.fetch.url.download_to", side_effect=fake_download)

    ctx = make_ctx(tmp_path, PIPELINE_YAML)
    spec = resolve_pipeline_spec(ctx)
    report = PipelineRunner(ctx, spec).run()

    stage_status = {s.name: s.status for s in report.stages}
    assert stage_status["fetch"] == "success"
    assert stage_status["transform"] == "success"
    assert stage_status["emit"] == "success"

    output_names = {a.output_name for a in report.artifacts}
    assert output_names == {
        "tarball-1.2.3.tar.gz",
        "SHASUMS256.txt",
        "discovered-b.zip",
        "discovered-l.zip",
    }
