import hashlib

from gorget.util.checksum import compute_digest, format_sources_manifest


def test_compute_digest_matches_hashlib(tmp_path):
    path = tmp_path / "file.txt"
    path.write_bytes(b"hello world")
    expected = hashlib.sha512(b"hello world").hexdigest()
    assert compute_digest(path, "sha512") == expected


def test_compute_digest_sha256(tmp_path):
    path = tmp_path / "file.txt"
    path.write_bytes(b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert compute_digest(path, "sha256") == expected


def test_format_sources_manifest_sorted_bsd_style():
    manifest = format_sources_manifest(
        [("b.tar.gz", "digestB"), ("a.tar.gz", "digestA")], "sha512"
    )
    assert manifest == "SHA512 (a.tar.gz) = digestA\nSHA512 (b.tar.gz) = digestB\n"


def test_format_sources_manifest_empty():
    assert format_sources_manifest([], "sha512") == ""
