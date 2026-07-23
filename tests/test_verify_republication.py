import hashlib

import pytest

from gorget.config.schema import AcceptedChecksumEntry
from gorget.config.substitution import SubstitutionVars
from gorget.context import RunContext
from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import FetchedArtifact
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.state import StageState
from gorget.verify.republication import check_republication, parse_sources_manifest


def make_ctx(package_dir):
    return RunContext(
        package_dir=package_dir,
        pipeline_file=package_dir / "pipeline.yaml",
        gpg_keys_dir=package_dir / "gpg-keys",
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


def make_artifact(path, name, checksum):
    return FetchedArtifact(path=path, output_name=name, source_description=name, checksum=checksum)


# --- parse_sources_manifest ---


def test_parse_modern_format():
    text = "SHA512 (foo-1.2.3.tar.gz) = abc123\n"
    assert parse_sources_manifest(text) == {"foo-1.2.3.tar.gz": ("sha512", "abc123")}


def test_parse_legacy_format():
    text = "d41d8cd98f00b204e9800998ecf8427e  foo-1.2.3.tar.gz\n"
    assert parse_sources_manifest(text) == {
        "foo-1.2.3.tar.gz": ("md5", "d41d8cd98f00b204e9800998ecf8427e")
    }


def test_parse_mixed_and_blank_lines():
    text = "\nSHA512 (a.tar.gz) = aaa\n\nbbb  b.tar.gz\n"
    assert parse_sources_manifest(text) == {
        "a.tar.gz": ("sha512", "aaa"),
        "b.tar.gz": ("md5", "bbb"),
    }


# --- check_republication ---


def test_no_sources_file_means_no_checks(tmp_path):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, [make_artifact(tmp_path / "x.tar.gz", "x.tar.gz", "abc")])
    assert check_republication(ctx, state, []) == []


def test_new_filename_not_in_existing_manifest_is_skipped(tmp_path):
    (tmp_path / "sources").write_text("SHA512 (old-1.0.0.tar.gz) = aaa\n")
    ctx = make_ctx(tmp_path)
    artifact = make_artifact(tmp_path / "new-1.1.0.tar.gz", "new-1.1.0.tar.gz", "abc")
    state = make_state(tmp_path, [artifact])
    assert check_republication(ctx, state, []) == []


def test_matching_checksum_is_not_a_republication(tmp_path):
    content = b"hello world"
    digest = hashlib.sha512(content).hexdigest()
    (tmp_path / "sources").write_text(f"SHA512 (foo.tar.gz) = {digest}\n")
    artifact_path = tmp_path / "foo.tar.gz"
    artifact_path.write_bytes(content)

    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, [make_artifact(artifact_path, "foo.tar.gz", digest)])
    assert check_republication(ctx, state, []) == []


def test_mismatched_checksum_fails_without_acceptance(tmp_path):
    (tmp_path / "sources").write_text("SHA512 (foo.tar.gz) = " + "a" * 128 + "\n")
    artifact_path = tmp_path / "foo.tar.gz"
    artifact_path.write_bytes(b"different content")
    new_digest = hashlib.sha512(b"different content").hexdigest()

    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, [make_artifact(artifact_path, "foo.tar.gz", new_digest)])
    results = check_republication(ctx, state, [])

    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].target == "foo.tar.gz"
    assert "accepted-checksums" in results[0].reason
    assert new_digest in results[0].reason


def test_mismatched_checksum_accepted_via_override(tmp_path):
    (tmp_path / "sources").write_text("SHA512 (foo.tar.gz) = " + "a" * 128 + "\n")
    artifact_path = tmp_path / "foo.tar.gz"
    artifact_path.write_bytes(b"different content")
    new_digest = hashlib.sha512(b"different content").hexdigest()

    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, [make_artifact(artifact_path, "foo.tar.gz", new_digest)])
    accepted = [AcceptedChecksumEntry(file="foo.tar.gz", checksum=new_digest, reason="legit")]
    results = check_republication(ctx, state, accepted)

    assert len(results) == 1
    assert results[0].status == "accepted"


def test_legacy_md5_manifest_compares_at_md5(tmp_path):
    content = b"hello world"
    md5_digest = hashlib.md5(content).hexdigest()
    (tmp_path / "sources").write_text(f"{md5_digest}  foo.tar.gz\n")
    artifact_path = tmp_path / "foo.tar.gz"
    artifact_path.write_bytes(content)

    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, [make_artifact(artifact_path, "foo.tar.gz", "sha512-value")])
    assert check_republication(ctx, state, []) == []


def test_unsupported_algorithm_raises_config_error(tmp_path):
    (tmp_path / "sources").write_text("BOGUS (foo.tar.gz) = deadbeef\n")
    artifact_path = tmp_path / "foo.tar.gz"
    artifact_path.write_bytes(b"content")

    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, [make_artifact(artifact_path, "foo.tar.gz", "x")])
    with pytest.raises(GorgetConfigError, match="unsupported checksum algorithm"):
        check_republication(ctx, state, [])
