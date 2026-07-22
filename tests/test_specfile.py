import shutil
import subprocess
from pathlib import Path

import pytest

from gorget.config.schema import MacroSubstitution
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.specfile import SpecFile

FIXTURES = Path(__file__).parent / "fixtures"
requires_rpmspec = pytest.mark.skipif(
    shutil.which("rpmspec") is None, reason="rpmspec not installed"
)


def fake_completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args=["rpmspec"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# --- mocked-subprocess unit tests (no rpmspec required) ---


def test_sources_parses_expanded_output(mocker):
    spec_path = FIXTURES / "specs" / "multi-source.spec"
    expanded = (FIXTURES / "rpmspec_output" / "multi-source.expanded.txt").read_text()
    mocker.patch("gorget.specfile.run", return_value=fake_completed(stdout=expanded))
    spec = SpecFile(spec_path)
    sources = spec.sources()
    assert [s.index for s in sources] == [0, 1, 2, 3]
    assert sources[0].url == "https://example.com/multisource/multisource-2.3.4.tar.gz"
    assert sources[2].url == "https://example.com/multisource/patches.tar.gz"
    assert sources[0].raw == "Source0:        https://example.com/%{name}/%{name}-%{version}.tar.gz"


def test_sources_raises_transient_error_on_rpmspec_failure(mocker):
    mocker.patch("gorget.specfile.run", return_value=fake_completed(stderr="boom", returncode=1))
    spec = SpecFile(FIXTURES / "specs" / "simple.spec")
    with pytest.raises(GorgetTransientError, match="boom"):
        spec.sources()


def test_sources_duplicate_index_raises_config_error(mocker):
    expanded = "Source0: https://a\nSource: https://b\n"
    mocker.patch("gorget.specfile.run", return_value=fake_completed(stdout=expanded))
    spec = SpecFile(FIXTURES / "specs" / "simple.spec")
    with pytest.raises(GorgetConfigError, match="Duplicate Source0"):
        spec.sources()


def test_name_version_release_strip_whitespace(mocker):
    mocker.patch("gorget.specfile.run", return_value=fake_completed(stdout="simple\n"))
    spec = SpecFile(FIXTURES / "specs" / "simple.spec")
    assert spec.name() == "simple"
    assert spec.version() == "simple"  # mock doesn't vary by queryformat; proves stripping only
    assert spec.release() == "simple"


def test_set_version_rewrites_in_place(tmp_path, mocker):
    spec_path = tmp_path / "foo.spec"
    spec_path.write_text("Name: foo\nVersion: 1.0.0\nRelease: 1%{?dist}\n")
    mock_run = mocker.patch("gorget.specfile.run", return_value=fake_completed(stdout="ok"))
    SpecFile(spec_path).set_version("2.0.0")
    assert "Version: 2.0.0" in spec_path.read_text()
    assert not (tmp_path / "foo.spec.gorget-tmp").exists()
    mock_run.assert_called_once()


def test_set_version_no_version_tag_raises(tmp_path, mocker):
    spec_path = tmp_path / "foo.spec"
    spec_path.write_text("Name: foo\n")
    mocker.patch("gorget.specfile.run", return_value=fake_completed())
    with pytest.raises(GorgetConfigError, match="No Version"):
        SpecFile(spec_path).set_version("2.0.0")


def test_reset_release_preserves_dist_suffix(tmp_path, mocker):
    spec_path = tmp_path / "foo.spec"
    spec_path.write_text("Name: foo\nRelease: 5%{?dist}\n")
    mocker.patch("gorget.specfile.run", return_value=fake_completed())
    SpecFile(spec_path).reset_release("1")
    assert "Release: 1%{?dist}" in spec_path.read_text()


def test_apply_substitution_uses_gorget_variables(tmp_path, mocker):
    spec_path = tmp_path / "foo.spec"
    spec_path.write_text("%global forgeurl https://old.example.com\n")
    mocker.patch("gorget.specfile.run", return_value=fake_completed())
    sub = MacroSubstitution(
        pattern=r"^%global forgeurl.*$",
        replacement="%global forgeurl https://${PACKAGE}.example.com",
    )
    variables = SubstitutionVars(
        version="1.0", old_version=None, package="foo", spec_file="foo.spec"
    )
    SpecFile(spec_path).apply_substitution(sub, variables)
    assert "%global forgeurl https://foo.example.com" in spec_path.read_text()


def test_apply_substitution_no_match_raises(tmp_path, mocker):
    spec_path = tmp_path / "foo.spec"
    spec_path.write_text("Name: foo\n")
    mocker.patch("gorget.specfile.run", return_value=fake_completed())
    sub = MacroSubstitution(pattern=r"^nonexistent$", replacement="x")
    variables = SubstitutionVars(
        version="1.0", old_version=None, package="foo", spec_file="foo.spec"
    )
    with pytest.raises(GorgetConfigError, match="matched nothing"):
        SpecFile(spec_path).apply_substitution(sub, variables)


def test_rewrite_and_validate_failure_leaves_original_untouched(tmp_path, mocker):
    spec_path = tmp_path / "foo.spec"
    spec_path.write_text("Name: foo\nVersion: 1.0.0\n")
    mocker.patch(
        "gorget.specfile.run", return_value=fake_completed(stderr="parse error", returncode=1)
    )
    with pytest.raises(GorgetTransientError, match="invalid spec"):
        SpecFile(spec_path).set_version("2.0.0")
    assert "Version: 1.0.0" in spec_path.read_text()
    assert (tmp_path / "foo.spec.gorget-tmp").exists()


# --- integration tests against a real rpmspec, skipped if not on PATH ---


@pytest.mark.integration
@requires_rpmspec
def test_sources_real_rpmspec_multi_source():
    sources = SpecFile(FIXTURES / "specs" / "multi-source.spec").sources()
    assert [s.index for s in sources] == [0, 1, 2, 3]
    assert sources[0].url == "https://example.com/multisource/multisource-2.3.4.tar.gz"
    assert sources[3].url == "https://example.com/multisource/vendor-2.3.4.tar.gz"


@pytest.mark.integration
@requires_rpmspec
def test_sources_real_rpmspec_conditional_bcond():
    sources = SpecFile(FIXTURES / "specs" / "conditional.spec").sources()
    assert [s.index for s in sources] == [0, 1]


@pytest.mark.integration
@requires_rpmspec
def test_name_version_real_rpmspec():
    spec = SpecFile(FIXTURES / "specs" / "simple.spec")
    assert spec.name() == "simple"
    assert spec.version() == "1.0.0"
    assert spec.release().startswith("1")


@pytest.mark.integration
@requires_rpmspec
def test_set_version_real_rpmspec_round_trip(tmp_path):
    spec_path = tmp_path / "simple.spec"
    spec_path.write_text((FIXTURES / "specs" / "simple.spec").read_text())
    spec = SpecFile(spec_path)
    spec.set_version("9.9.9")
    assert spec.version() == "9.9.9"
    assert not (tmp_path / "simple.spec.gorget-tmp").exists()
