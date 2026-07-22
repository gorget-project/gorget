from pathlib import Path

import pytest

from gorget.config.loader import build_pipeline_spec, load_yaml, parse_pipeline_spec
from gorget.config.schema import GitStep, SpecSourceStep, SpecUpdateStep, UrlStep, VendorStep
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetConfigError

FIXTURES = Path(__file__).parent / "fixtures" / "pipelines"


def make_vars():
    return SubstitutionVars(
        version="1.2.3", old_version="1.2.2", package="example", spec_file="example.spec"
    )


def test_load_yaml_malformed_raises_config_error():
    with pytest.raises(GorgetConfigError):
        load_yaml(FIXTURES / "malformed.yaml")


def test_build_pipeline_spec_full_schema_round_trips():
    spec = build_pipeline_spec(FIXTURES / "full-schema.yaml", substitution_vars=make_vars())
    assert spec.package == "example"
    assert len(spec.fetch) == 5
    assert isinstance(spec.fetch[0], SpecUpdateStep)
    assert spec.fetch[0].reset_release == "1"
    assert spec.fetch[0].substitutions[0].replacement == "%global forgeurl https://example.com/example"
    assert isinstance(spec.fetch[1], SpecSourceStep)
    assert isinstance(spec.fetch[2], UrlStep)
    assert spec.fetch[2].url == "https://example.com/example-1.2.3-extra.tar.gz"
    assert isinstance(spec.fetch[3], GitStep)
    assert spec.fetch[3].ref == "v1.2.3"
    assert isinstance(spec.fetch[4], VendorStep)
    assert spec.fetch[4].ecosystem == "go"

    # Inert sections still parse without error, as raw passthrough.
    assert len(spec.transform.steps) == 1
    assert len(spec.toolchain.entries) == 1
    assert len(spec.verify.steps) == 1
    assert spec.policy.rules["vendor-constraints"]["go"]["minimum"] == "1.20"
    assert len(spec.patches.entries) == 1
    assert len(spec.post.steps) == 1


def test_build_pipeline_spec_fetch_only():
    spec = build_pipeline_spec(FIXTURES / "fetch-only.yaml", substitution_vars=make_vars())
    assert spec.fetch == [SpecSourceStep(index=0)]


def test_build_pipeline_spec_vendor_multi_submodule():
    spec = build_pipeline_spec(
        FIXTURES / "vendor-multi-submodule.yaml", substitution_vars=make_vars()
    )
    vendor_step = spec.fetch[1]
    assert isinstance(vendor_step, VendorStep)
    assert [m.path for m in vendor_step.modules] == ["server", "etcdctl", "etcdutl"]
    assert vendor_step.archive_name == "example-vendor.tar.gz"


def test_unknown_fetch_type_raises_config_error():
    with pytest.raises(GorgetConfigError, match="Unknown fetch step type"):
        build_pipeline_spec(FIXTURES / "unknown-fetch-type.yaml", substitution_vars=make_vars())


def test_unknown_top_level_key_is_ignored_not_fatal():
    spec = parse_pipeline_spec({"totally-unknown-section": {"x": 1}})
    assert spec.fetch == []


def test_fetch_section_must_be_a_list():
    with pytest.raises(GorgetConfigError, match="'fetch' section must be a list"):
        parse_pipeline_spec({"fetch": {"type": "url"}})


def test_missing_pipeline_file_raises_config_error():
    with pytest.raises(GorgetConfigError):
        load_yaml(FIXTURES / "does-not-exist.yaml")
