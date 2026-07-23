import hashlib

import pytest

from gorget.config.schema import (
    AcceptedChecksumEntry,
    AcceptedChecksumsSection,
    ChecksumFileStep,
    PipelineSpec,
    VerifySection,
)
from gorget.config.substitution import SubstitutionVars
from gorget.context import RunContext
from gorget.exceptions import GorgetPolicyViolation
from gorget.fetch.base import FetchedArtifact
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.stages.verify import VerifyStage
from gorget.pipeline.state import StageState


def make_ctx(package_dir, dry_run=False):
    return RunContext(
        package_dir=package_dir,
        pipeline_file=package_dir / "pipeline.yaml",
        gpg_keys_dir=package_dir / "gpg-keys",
        output_dir=package_dir / "output",
        dry_run=dry_run,
        spec_path=package_dir / "foo.spec",
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
    )


def make_state(work_dir, artifacts=()):
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    return StageState(work_dir=work_dir, spec=None, report=report, artifacts=list(artifacts))


def make_artifact(path, name, checksum="x"):
    return FetchedArtifact(path=path, output_name=name, source_description=name, checksum=checksum)


def test_dry_run_skips_entirely(tmp_path):
    ctx = make_ctx(tmp_path, dry_run=True)
    state = make_state(tmp_path)
    result = VerifyStage().run(ctx, PipelineSpec(), state)
    assert result.status == "skipped"
    assert result.reason == "dry-run"


def test_no_verification_configured_skips_with_warning(tmp_path, caplog):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, [make_artifact(tmp_path / "foo.tar.gz", "foo.tar.gz")])
    result = VerifyStage().run(ctx, PipelineSpec(), state)
    assert result.status == "skipped"
    assert result.reason == "no verification configured"


def test_success_with_no_findings_when_sources_matches(tmp_path):
    content = b"hello world"
    digest = hashlib.sha512(content).hexdigest()
    (tmp_path / "sources").write_text(f"SHA512 (foo.tar.gz) = {digest}\n")
    artifact_path = tmp_path / "foo.tar.gz"
    artifact_path.write_bytes(content)

    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, [make_artifact(artifact_path, "foo.tar.gz", digest)])
    result = VerifyStage().run(ctx, PipelineSpec(), state)

    assert result.status == "success"
    assert result.details == []


def test_republication_mismatch_raises_policy_violation(tmp_path):
    (tmp_path / "sources").write_text("SHA512 (foo.tar.gz) = " + "a" * 128 + "\n")
    artifact_path = tmp_path / "foo.tar.gz"
    artifact_path.write_bytes(b"different content")
    new_digest = hashlib.sha512(b"different content").hexdigest()

    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, [make_artifact(artifact_path, "foo.tar.gz", new_digest)])
    with pytest.raises(GorgetPolicyViolation, match="Verification failed"):
        VerifyStage().run(ctx, PipelineSpec(), state)


def test_republication_mismatch_accepted_via_override_succeeds(tmp_path):
    (tmp_path / "sources").write_text("SHA512 (foo.tar.gz) = " + "a" * 128 + "\n")
    artifact_path = tmp_path / "foo.tar.gz"
    artifact_path.write_bytes(b"different content")
    new_digest = hashlib.sha512(b"different content").hexdigest()

    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, [make_artifact(artifact_path, "foo.tar.gz", new_digest)])
    spec = PipelineSpec(
        accepted_checksums=AcceptedChecksumsSection(
            entries=[AcceptedChecksumEntry(file="foo.tar.gz", checksum=new_digest, reason="ok")]
        )
    )
    result = VerifyStage().run(ctx, spec, state)
    assert result.status == "success"
    assert result.details[0]["status"] == "accepted"


def test_checksum_file_step_dispatches_and_succeeds(tmp_path):
    target_path = tmp_path / "foo.tar.gz"
    target_path.write_bytes(b"hello world")
    digest = hashlib.sha256(b"hello world").hexdigest()
    checksums_path = tmp_path / "SHASUMS256.txt"
    checksums_path.write_text(f"{digest}  foo.tar.gz\n")

    ctx = make_ctx(tmp_path)
    state = make_state(
        tmp_path,
        [make_artifact(target_path, "foo.tar.gz"), make_artifact(checksums_path, "SHASUMS256.txt")],
    )
    spec = PipelineSpec(
        verify=VerifySection(
            steps=[ChecksumFileStep(target="foo.tar.gz", checksums_file="SHASUMS256.txt")]
        )
    )
    result = VerifyStage().run(ctx, spec, state)
    assert result.status == "success"
    assert result.details == [
        {"type": "checksum-file", "target": "foo.tar.gz", "status": "passed", "reason": None}
    ]


def test_checksum_file_step_failure_raises_policy_violation(tmp_path):
    target_path = tmp_path / "foo.tar.gz"
    target_path.write_bytes(b"hello world")
    checksums_path = tmp_path / "SHASUMS256.txt"
    checksums_path.write_text("0" * 64 + "  foo.tar.gz\n")

    ctx = make_ctx(tmp_path)
    state = make_state(
        tmp_path,
        [make_artifact(target_path, "foo.tar.gz"), make_artifact(checksums_path, "SHASUMS256.txt")],
    )
    spec = PipelineSpec(
        verify=VerifySection(
            steps=[ChecksumFileStep(target="foo.tar.gz", checksums_file="SHASUMS256.txt")]
        )
    )
    with pytest.raises(GorgetPolicyViolation, match="checksum-file"):
        VerifyStage().run(ctx, spec, state)


def test_multiple_failures_are_all_reported_together(tmp_path):
    (tmp_path / "sources").write_text("SHA512 (foo.tar.gz) = " + "a" * 128 + "\n")
    foo_path = tmp_path / "foo.tar.gz"
    foo_path.write_bytes(b"changed")

    bar_path = tmp_path / "bar.tar.gz"
    bar_path.write_bytes(b"hello world")
    checksums_path = tmp_path / "SHASUMS256.txt"
    checksums_path.write_text("0" * 64 + "  bar.tar.gz\n")

    ctx = make_ctx(tmp_path)
    state = make_state(
        tmp_path,
        [
            make_artifact(foo_path, "foo.tar.gz", hashlib.sha512(b"changed").hexdigest()),
            make_artifact(bar_path, "bar.tar.gz"),
            make_artifact(checksums_path, "SHASUMS256.txt"),
        ],
    )
    spec = PipelineSpec(
        verify=VerifySection(
            steps=[ChecksumFileStep(target="bar.tar.gz", checksums_file="SHASUMS256.txt")]
        )
    )
    with pytest.raises(GorgetPolicyViolation) as exc_info:
        VerifyStage().run(ctx, spec, state)
    message = str(exc_info.value)
    assert "foo.tar.gz" in message
    assert "bar.tar.gz" in message
    assert "2 check(s)" in message
