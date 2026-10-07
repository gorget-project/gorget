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


def test_stream_failure_is_transient_and_removes_partial_download(tmp_path, mocker):
    import pytest
    import requests

    from gorget.exceptions import GorgetTransientError

    response = mocker.MagicMock()
    response.__enter__.return_value = response

    def interrupted_stream(**kwargs):
        yield b"partial archive"
        raise requests.ConnectionError("stream timed out")

    response.iter_content.side_effect = interrupted_stream
    mocker.patch("gorget.util.download.requests.get", return_value=response)
    dest = tmp_path / "source.tar.gz"
    with pytest.raises(GorgetTransientError, match="stream timed out"):
        download_to("https://example.com/source.tar.gz", dest)
    assert not dest.exists()
    response.__exit__.assert_called_once()
