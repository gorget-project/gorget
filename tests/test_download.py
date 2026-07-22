import responses

from gorget.util.download import download_to


@responses.activate
def test_download_to_writes_file(tmp_path):
    responses.add(
        responses.GET,
        "https://example.com/file.tar.gz",
        body=b"tarball-bytes",
        status=200,
    )
    dest = tmp_path / "nested" / "file.tar.gz"
    download_to("https://example.com/file.tar.gz", dest)
    assert dest.read_bytes() == b"tarball-bytes"


@responses.activate
def test_download_to_raises_transient_error_on_http_failure(tmp_path):
    responses.add(responses.GET, "https://example.com/missing.tar.gz", status=404)
    dest = tmp_path / "missing.tar.gz"
    from gorget.exceptions import GorgetTransientError

    try:
        download_to("https://example.com/missing.tar.gz", dest)
    except GorgetTransientError:
        pass
    else:
        raise AssertionError("expected GorgetTransientError")
    assert not dest.exists()
