import json
import subprocess

from gorget.cli import main


def _mock_rpmspec(mocker, sources_text=""):
    return mocker.patch(
        "gorget.specfile.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout=sources_text, stderr=""
        ),
    )


def test_main_dry_run_prints_report_and_returns_zero(tmp_path, mocker, capsys):
    (tmp_path / "foo.spec").write_text("Name: foo\nVersion: 1.2.3\nRelease: 1\n")
    _mock_rpmspec(mocker, sources_text="Source0: https://example.com/foo-1.2.3.tar.gz\n")

    exit_code = main(
        [
            "--version",
            "1.2.3",
            "--package-dir",
            str(tmp_path),
            "--pipeline-file",
            str(tmp_path / "pipeline.yaml"),
            "--output-dir",
            str(tmp_path / "output"),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True
    assert report["artifacts"][0]["output_name"] == "foo-1.2.3.tar.gz"
    assert report["artifacts"][0]["checksum"] is None
    stage_names = [s["name"] for s in report["stages"]]
    assert stage_names == ["fetch", "transform", "verify", "policy", "post", "emit"]
    assert not (tmp_path / "output").exists()


def test_main_real_run_writes_output_and_returns_zero(tmp_path, mocker):
    (tmp_path / "foo.spec").write_text("Name: foo\nVersion: 1.2.3\nRelease: 1\n")
    _mock_rpmspec(mocker, sources_text="Source0: https://example.com/foo-1.2.3.tar.gz\n")
    mocker.patch(
        "gorget.fetch.spec_source.download_to",
        side_effect=lambda url, dest: dest.write_bytes(b"data"),
    )

    output_dir = tmp_path / "output"
    exit_code = main(
        [
            "--version",
            "1.2.3",
            "--package-dir",
            str(tmp_path),
            "--pipeline-file",
            str(tmp_path / "pipeline.yaml"),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "foo-1.2.3.tar.gz").read_bytes() == b"data"
    assert (output_dir / "sources").exists()
    assert (output_dir / "report.json").exists()


def test_main_returns_exit_code_1_on_config_error(tmp_path, capsys):
    exit_code = main(
        [
            "--version",
            "1.2.3",
            "--package-dir",
            str(tmp_path / "nonexistent"),
        ]
    )
    assert exit_code == 1
    assert "error:" in capsys.readouterr().err


# A verify: step referencing a signature artifact that was never fetched --
# fetch/transform succeed for real, then verify fails closed deterministically,
# with no network/gpg binary needed. Used below to exercise the "report.json
# is still written/printed even when a stage fails" requirement.
_FAILING_PIPELINE_YAML = """
fetch:
  - type: spec-source
    index: 0
verify:
  - type: gpg-signature
    target: "foo-1.2.3.tar.gz"
    signature: "does-not-exist.asc"
    keyring: "somekey.asc"
"""


def test_main_stage_failure_writes_report_json(tmp_path, mocker, capsys):
    (tmp_path / "foo.spec").write_text("Name: foo\nVersion: 1.2.3\nRelease: 1\n")
    _mock_rpmspec(mocker, sources_text="Source0: https://example.com/foo-1.2.3.tar.gz\n")
    mocker.patch(
        "gorget.fetch.spec_source.download_to",
        side_effect=lambda url, dest: dest.write_bytes(b"data"),
    )
    (tmp_path / "pipeline.yaml").write_text(_FAILING_PIPELINE_YAML)

    output_dir = tmp_path / "output"
    exit_code = main(
        [
            "--version",
            "1.2.3",
            "--package-dir",
            str(tmp_path),
            "--pipeline-file",
            str(tmp_path / "pipeline.yaml"),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 1
    assert "error:" in capsys.readouterr().err

    report = json.loads((output_dir / "report.json").read_text())
    stage_status = {s["name"]: s["status"] for s in report["stages"]}
    assert stage_status["fetch"] == "success"
    assert stage_status["verify"] == "failed"
    # Fail-closed: no partial tarballs/sources manifest, only the report.
    assert not (output_dir / "foo-1.2.3.tar.gz").exists()
    assert not (output_dir / "sources").exists()


def test_main_stage_failure_under_dry_run_prints_report(tmp_path, capsys):
    # verify:/policy: both skip entirely under --dry-run (nothing was really
    # fetched to check), so use a toolchain mismatch instead -- that check
    # runs unconditionally, dry-run or not, and needs no mocking to fail
    # deterministically. Uses python, not go/node/etc: python3 is guaranteed
    # present in any environment capable of running this test suite at all
    # (unlike other toolchains, which may be absent in a minimal build root).
    (tmp_path / "foo.spec").write_text("Name: foo\nVersion: 1.2.3\nRelease: 1\n")
    (tmp_path / "pipeline.yaml").write_text(
        "toolchain:\n  - name: python\n    version: 999.999.999\n"
    )

    exit_code = main(
        [
            "--version",
            "1.2.3",
            "--package-dir",
            str(tmp_path),
            "--pipeline-file",
            str(tmp_path / "pipeline.yaml"),
            "--output-dir",
            str(tmp_path / "output"),
            "--dry-run",
        ]
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err
    report = json.loads(captured.out)
    stage_status = {s["name"]: s["status"] for s in report["stages"]}
    assert stage_status["toolchain"] == "failed"
    assert not (tmp_path / "output").exists()


def test_main_requires_version_argument():
    try:
        main([])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit from argparse for missing --version")
