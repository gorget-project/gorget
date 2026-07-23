import hashlib

import pytest

from gorget.config.schema import ChecksumFileStep
from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import FetchedArtifact
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.state import StageState
from gorget.verify.checksum_file import ChecksumFileHandler


def make_state(tmp_path, artifacts):
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    return StageState(work_dir=tmp_path, spec=None, report=report, artifacts=list(artifacts))


def make_artifact(path, name):
    return FetchedArtifact(path=path, output_name=name, source_description=name, checksum="x")


def make_two_artifacts(target_path, target_name, checksums_path, checksums_name):
    return [
        make_artifact(target_path, target_name),
        make_artifact(checksums_path, checksums_name),
    ]


def test_checksum_file_passes_on_match(tmp_path):
    target_path = tmp_path / "foo-1.2.3.tar.gz"
    target_path.write_bytes(b"hello world")
    digest = hashlib.sha256(b"hello world").hexdigest()

    checksums_path = tmp_path / "SHASUMS256.txt"
    checksums_path.write_text(f"{digest}  foo-1.2.3.tar.gz\nother  other.tar.gz\n")

    artifacts = [
        make_artifact(target_path, "foo-1.2.3.tar.gz"),
        make_artifact(checksums_path, "SHASUMS256.txt"),
    ]
    state = make_state(tmp_path, artifacts)
    step = ChecksumFileStep(target="foo-1.2.3.tar.gz", checksums_file="SHASUMS256.txt")

    result = ChecksumFileHandler().run(step, None, state)

    assert result.status == "passed"
    assert result.type == "checksum-file"


def test_checksum_file_handles_binary_mode_marker(tmp_path):
    target_path = tmp_path / "foo.tar.gz"
    target_path.write_bytes(b"hello world")
    digest = hashlib.sha256(b"hello world").hexdigest()

    checksums_path = tmp_path / "SHASUMS256.txt"
    checksums_path.write_text(f"{digest} *foo.tar.gz\n")

    artifacts = make_two_artifacts(target_path, "foo.tar.gz", checksums_path, "SHASUMS256.txt")
    state = make_state(tmp_path, artifacts)
    step = ChecksumFileStep(target="foo.tar.gz", checksums_file="SHASUMS256.txt")

    result = ChecksumFileHandler().run(step, None, state)
    assert result.status == "passed"


def test_checksum_file_fails_on_mismatch(tmp_path):
    target_path = tmp_path / "foo.tar.gz"
    target_path.write_bytes(b"hello world")

    checksums_path = tmp_path / "SHASUMS256.txt"
    checksums_path.write_text("0" * 64 + "  foo.tar.gz\n")

    artifacts = make_two_artifacts(target_path, "foo.tar.gz", checksums_path, "SHASUMS256.txt")
    state = make_state(tmp_path, artifacts)
    step = ChecksumFileStep(target="foo.tar.gz", checksums_file="SHASUMS256.txt")

    result = ChecksumFileHandler().run(step, None, state)
    assert result.status == "failed"
    assert "expected sha256" in result.reason


def test_checksum_file_missing_entry_raises_config_error(tmp_path):
    target_path = tmp_path / "foo.tar.gz"
    target_path.write_bytes(b"hello world")

    checksums_path = tmp_path / "SHASUMS256.txt"
    checksums_path.write_text("abc123  other-file.tar.gz\n")

    artifacts = make_two_artifacts(target_path, "foo.tar.gz", checksums_path, "SHASUMS256.txt")
    state = make_state(tmp_path, artifacts)
    step = ChecksumFileStep(target="foo.tar.gz", checksums_file="SHASUMS256.txt")

    with pytest.raises(GorgetConfigError, match="No checksum entry"):
        ChecksumFileHandler().run(step, None, state)


def test_checksum_file_uses_declared_algorithm(tmp_path):
    target_path = tmp_path / "foo.tar.gz"
    target_path.write_bytes(b"hello world")
    digest = hashlib.sha512(b"hello world").hexdigest()

    checksums_path = tmp_path / "SHASUMS512.txt"
    checksums_path.write_text(f"{digest}  foo.tar.gz\n")

    artifacts = make_two_artifacts(target_path, "foo.tar.gz", checksums_path, "SHASUMS512.txt")
    state = make_state(tmp_path, artifacts)
    step = ChecksumFileStep(
        target="foo.tar.gz", checksums_file="SHASUMS512.txt", algorithm="sha512"
    )

    result = ChecksumFileHandler().run(step, None, state)
    assert result.status == "passed"
