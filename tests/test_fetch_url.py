from unittest.mock import Mock

from gorget.config.schema import UrlStep
from gorget.config.substitution import SubstitutionVars
from gorget.fetch.base import FetchContext
from gorget.fetch.url import UrlHandler


def make_ctx(work_dir, dry_run=False):
    return FetchContext(
        work_dir=work_dir,
        package_dir=work_dir,
        spec=Mock(),
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
        dry_run=dry_run,
    )


def _write_fake_download(url, dest):
    dest.write_bytes(b"fake-bytes")


def test_url_handler_derives_filename_from_url(tmp_path, mocker):
    download_to = mocker.patch("gorget.fetch.url.download_to", side_effect=_write_fake_download)
    step = UrlStep(url="https://example.com/path/thing-1.2.3.tar.gz")
    artifacts = UrlHandler().run(step, make_ctx(tmp_path))
    assert artifacts[0].output_name == "thing-1.2.3.tar.gz"
    download_to.assert_called_once_with(
        "https://example.com/path/thing-1.2.3.tar.gz", tmp_path / "thing-1.2.3.tar.gz"
    )


def test_url_handler_explicit_filename_override(tmp_path, mocker):
    mocker.patch("gorget.fetch.url.download_to", side_effect=_write_fake_download)
    step = UrlStep(url="https://example.com/thing.tar.gz", filename="renamed.tar.gz")
    artifacts = UrlHandler().run(step, make_ctx(tmp_path))
    assert artifacts[0].output_name == "renamed.tar.gz"


def test_url_handler_dry_run_skips_download(tmp_path, mocker):
    download_to = mocker.patch("gorget.fetch.url.download_to")
    step = UrlStep(url="https://example.com/thing.tar.gz")
    artifacts = UrlHandler().run(step, make_ctx(tmp_path, dry_run=True))
    download_to.assert_not_called()
    assert artifacts[0].checksum is None
