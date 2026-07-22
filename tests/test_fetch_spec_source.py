from unittest.mock import Mock

import pytest

from gorget.config.schema import SpecSourceStep
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import FetchContext
from gorget.fetch.spec_source import SpecSourceHandler
from gorget.specfile import SpecSourceEntry


def make_ctx(spec, work_dir, dry_run=False):
    return FetchContext(
        work_dir=work_dir,
        package_dir=work_dir,
        spec=spec,
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
        dry_run=dry_run,
    )


def _write_fake_download(url, dest):
    dest.write_bytes(b"fake-bytes")


def test_fetches_all_sources_when_index_is_none(tmp_path, mocker):
    spec = Mock()
    spec.sources.return_value = [
        SpecSourceEntry(index=0, url="https://example.com/foo-1.2.3.tar.gz"),
        SpecSourceEntry(index=1, url="https://example.com/extra.tar.gz"),
    ]
    download_to = mocker.patch(
        "gorget.fetch.spec_source.download_to", side_effect=_write_fake_download
    )
    ctx = make_ctx(spec, tmp_path)
    artifacts = SpecSourceHandler().run(SpecSourceStep(index=None), ctx)
    assert [a.output_name for a in artifacts] == ["foo-1.2.3.tar.gz", "extra.tar.gz"]
    assert download_to.call_count == 2


def test_fetches_only_requested_index(tmp_path, mocker):
    spec = Mock()
    spec.sources.return_value = [
        SpecSourceEntry(index=0, url="https://example.com/foo-1.2.3.tar.gz"),
        SpecSourceEntry(index=1, url="https://example.com/extra.tar.gz"),
    ]
    mocker.patch("gorget.fetch.spec_source.download_to", side_effect=_write_fake_download)
    ctx = make_ctx(spec, tmp_path)
    artifacts = SpecSourceHandler().run(SpecSourceStep(index=1), ctx)
    assert [a.output_name for a in artifacts] == ["extra.tar.gz"]


def test_missing_index_raises_config_error(tmp_path, mocker):
    spec = Mock()
    spec.sources.return_value = [SpecSourceEntry(index=0, url="https://example.com/foo.tar.gz")]
    mocker.patch("gorget.fetch.spec_source.download_to")
    ctx = make_ctx(spec, tmp_path)
    with pytest.raises(GorgetConfigError, match="No Source5"):
        SpecSourceHandler().run(SpecSourceStep(index=5), ctx)


def test_rename_applies_only_when_single_target(tmp_path, mocker):
    spec = Mock()
    spec.sources.return_value = [SpecSourceEntry(index=0, url="https://example.com/foo.tar.gz")]
    mocker.patch("gorget.fetch.spec_source.download_to", side_effect=_write_fake_download)
    ctx = make_ctx(spec, tmp_path)
    artifacts = SpecSourceHandler().run(SpecSourceStep(index=0, rename="renamed.tar.gz"), ctx)
    assert artifacts[0].output_name == "renamed.tar.gz"


def test_dry_run_skips_download_and_checksum(tmp_path, mocker):
    spec = Mock()
    spec.sources.return_value = [SpecSourceEntry(index=0, url="https://example.com/foo.tar.gz")]
    download_to = mocker.patch("gorget.fetch.spec_source.download_to")
    ctx = make_ctx(spec, tmp_path, dry_run=True)
    artifacts = SpecSourceHandler().run(SpecSourceStep(index=None), ctx)
    download_to.assert_not_called()
    assert artifacts[0].checksum is None
