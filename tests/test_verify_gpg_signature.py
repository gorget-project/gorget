"""Real, non-mocked GPG signature verification tests: generate an ephemeral
GPG keypair, sign a file for real, and verify it through the actual
GpgSignatureHandler. Self-contained (no network needed), so this runs as a
real test rather than a mock -- skipped automatically if `gpg` isn't on PATH.
"""

import shutil
import subprocess

import pytest

from gorget.config.schema import GpgSignatureStep
from gorget.config.substitution import SubstitutionVars
from gorget.context import RunContext
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.fetch.base import FetchedArtifact
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.state import StageState
from gorget.verify.gpg_signature import GpgSignatureHandler

requires_gpg = pytest.mark.skipif(shutil.which("gpg") is None, reason="gpg not installed")


def _run(args):
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result


@pytest.fixture
def gpg_keypair(tmp_path):
    gen_home = tmp_path / "gen-home"
    gen_home.mkdir(mode=0o700)
    _run(
        [
            "gpg", "--homedir", str(gen_home), "--batch", "--passphrase", "",
            "--quick-generate-key", "Test Key <test@example.com>", "default", "default", "never",
        ]
    )
    return gen_home, "test@example.com"


def make_ctx(package_dir, gpg_keys_dir):
    return RunContext(
        package_dir=package_dir,
        pipeline_file=package_dir / "pipeline.yaml",
        gpg_keys_dir=gpg_keys_dir,
        output_dir=package_dir / "output",
        dry_run=False,
        spec_path=package_dir / "foo.spec",
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
    )


def make_state(work_dir, artifacts):
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    return StageState(work_dir=work_dir, spec=None, report=report, artifacts=list(artifacts))


def make_artifact(path, name):
    return FetchedArtifact(path=path, output_name=name, source_description=name, checksum="x")


def _export_keyring(gen_home, email, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["gpg", "--homedir", str(gen_home), "--batch", "--export", email],
        capture_output=True, check=True,
    )
    dest.write_bytes(result.stdout)


@pytest.mark.integration
@requires_gpg
def test_gpg_signature_passes_for_a_real_valid_signature(tmp_path, gpg_keypair):
    gen_home, email = gpg_keypair
    gpg_keys_dir = tmp_path / "gpg-keys"
    keyring_path = gpg_keys_dir / "example-project.gpg"
    _export_keyring(gen_home, email, keyring_path)

    target_path = tmp_path / "foo-1.2.3.tar.gz"
    target_path.write_text("tarball contents")
    sig_path = tmp_path / "foo-1.2.3.tar.gz.asc"
    _run(
        [
            "gpg", "--homedir", str(gen_home), "--batch", "--local-user", email,
            "--detach-sign", "-o", str(sig_path), str(target_path),
        ]
    )

    ctx = make_ctx(tmp_path, gpg_keys_dir)
    state = make_state(
        tmp_path,
        [
            make_artifact(target_path, "foo-1.2.3.tar.gz"),
            make_artifact(sig_path, "foo-1.2.3.tar.gz.asc"),
        ],
    )
    step = GpgSignatureStep(
        target="foo-1.2.3.tar.gz",
        signature="foo-1.2.3.tar.gz.asc",
        keyring="example-project.gpg",
    )

    result = GpgSignatureHandler().run(step, ctx, state)
    assert result.status == "passed"
    assert result.type == "gpg-signature"


@pytest.mark.integration
@requires_gpg
def test_gpg_signature_fails_for_tampered_content(tmp_path, gpg_keypair):
    gen_home, email = gpg_keypair
    gpg_keys_dir = tmp_path / "gpg-keys"
    keyring_path = gpg_keys_dir / "example-project.gpg"
    _export_keyring(gen_home, email, keyring_path)

    target_path = tmp_path / "foo.tar.gz"
    target_path.write_text("original contents")
    sig_path = tmp_path / "foo.tar.gz.asc"
    _run(
        [
            "gpg", "--homedir", str(gen_home), "--batch", "--local-user", email,
            "--detach-sign", "-o", str(sig_path), str(target_path),
        ]
    )

    # Tamper with the target *after* signing.
    target_path.write_text("tampered contents")

    ctx = make_ctx(tmp_path, gpg_keys_dir)
    state = make_state(
        tmp_path,
        [make_artifact(target_path, "foo.tar.gz"), make_artifact(sig_path, "foo.tar.gz.asc")],
    )
    step = GpgSignatureStep(
        target="foo.tar.gz", signature="foo.tar.gz.asc", keyring="example-project.gpg"
    )

    result = GpgSignatureHandler().run(step, ctx, state)
    assert result.status == "failed"
    assert "gpg verification failed" in result.reason


@pytest.mark.integration
@requires_gpg
def test_gpg_signature_fails_for_wrong_keyring(tmp_path, gpg_keypair):
    gen_home, email = gpg_keypair

    # A second, unrelated keypair -- its export is the "wrong" keyring.
    other_home = tmp_path / "other-home"
    other_home.mkdir(mode=0o700)
    _run(
        [
            "gpg", "--homedir", str(other_home), "--batch", "--passphrase", "",
            "--quick-generate-key", "Other Key <other@example.com>", "default", "default", "never",
        ]
    )
    gpg_keys_dir = tmp_path / "gpg-keys"
    keyring_path = gpg_keys_dir / "wrong.gpg"
    _export_keyring(other_home, "other@example.com", keyring_path)

    target_path = tmp_path / "foo.tar.gz"
    target_path.write_text("contents")
    sig_path = tmp_path / "foo.tar.gz.asc"
    _run(
        [
            "gpg", "--homedir", str(gen_home), "--batch", "--local-user", email,
            "--detach-sign", "-o", str(sig_path), str(target_path),
        ]
    )

    ctx = make_ctx(tmp_path, gpg_keys_dir)
    state = make_state(
        tmp_path,
        [make_artifact(target_path, "foo.tar.gz"), make_artifact(sig_path, "foo.tar.gz.asc")],
    )
    step = GpgSignatureStep(target="foo.tar.gz", signature="foo.tar.gz.asc", keyring="wrong.gpg")

    result = GpgSignatureHandler().run(step, ctx, state)
    assert result.status == "failed"


def test_gpg_signature_missing_keyring_raises_config_error(tmp_path):
    ctx = make_ctx(tmp_path, tmp_path / "gpg-keys")
    state = make_state(
        tmp_path,
        [
            make_artifact(tmp_path / "foo.tar.gz", "foo.tar.gz"),
            make_artifact(tmp_path / "foo.tar.gz.asc", "foo.tar.gz.asc"),
        ],
    )
    step = GpgSignatureStep(
        target="foo.tar.gz", signature="foo.tar.gz.asc", keyring="missing.gpg"
    )
    with pytest.raises(GorgetConfigError, match="GPG keyring not found"):
        GpgSignatureHandler().run(step, ctx, state)


def test_gpg_signature_import_failure_raises_transient_error(tmp_path, mocker):
    gpg_keys_dir = tmp_path / "gpg-keys"
    gpg_keys_dir.mkdir()
    (gpg_keys_dir / "bad.gpg").write_text("not a real keyring")
    mocker.patch(
        "gorget.verify.gpg_signature.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="bad data"
        ),
    )
    ctx = make_ctx(tmp_path, gpg_keys_dir)
    state = make_state(
        tmp_path,
        [
            make_artifact(tmp_path / "foo.tar.gz", "foo.tar.gz"),
            make_artifact(tmp_path / "foo.tar.gz.asc", "foo.tar.gz.asc"),
        ],
    )
    step = GpgSignatureStep(target="foo.tar.gz", signature="foo.tar.gz.asc", keyring="bad.gpg")
    with pytest.raises(GorgetTransientError, match="gpg --import failed"):
        GpgSignatureHandler().run(step, ctx, state)
