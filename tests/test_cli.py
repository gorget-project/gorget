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
    assert stage_names == ["fetch", "transform", "verify", "policy", "emit"]
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


def test_main_requires_version_argument():
    try:
        main([])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit from argparse for missing --version")
