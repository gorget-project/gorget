import json

from gorget.config.schema import LicenseComplianceSection
from gorget.policy.base import VendoredModule
from gorget.policy.license_compliance import check_license_compliance


def write_npm_package(node_modules, name, license_value):
    pkg_dir = node_modules / name
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.json").write_text(json.dumps({"name": name, "license": license_value}))


def write_cargo_crate(vendor_dir, dirname, license_value):
    crate_dir = vendor_dir / dirname
    crate_dir.mkdir(parents=True)
    (crate_dir / "Cargo.toml").write_text(f'[package]\nname = "x"\nlicense = "{license_value}"\n')


def test_npm_disallowed_license_fails(tmp_path):
    write_npm_package(tmp_path / "node_modules", "bad-pkg", "GPL-3.0-only")
    section = LicenseComplianceSection(disallowed=["GPL-3.0-only"])
    modules = [VendoredModule(ecosystem="npm", path=tmp_path)]
    results = check_license_compliance(section, modules)
    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].target == "bad-pkg"


def test_npm_allowed_license_passes_silently(tmp_path):
    write_npm_package(tmp_path / "node_modules", "good-pkg", "MIT")
    section = LicenseComplianceSection(disallowed=["GPL-3.0-only"])
    modules = [VendoredModule(ecosystem="npm", path=tmp_path)]
    assert check_license_compliance(section, modules) == []


def test_npm_scoped_package_name_reported_correctly(tmp_path):
    node_modules = tmp_path / "node_modules"
    write_npm_package(node_modules / "@scope", "pkg", "AGPL-3.0-only")
    section = LicenseComplianceSection(disallowed=["AGPL-3.0-only"])
    modules = [VendoredModule(ecosystem="npm", path=tmp_path)]
    results = check_license_compliance(section, modules)
    assert results[0].target == "@scope/pkg"


def test_npm_legacy_license_object_form(tmp_path):
    pkg_dir = tmp_path / "node_modules" / "old-pkg"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.json").write_text(json.dumps({"license": {"type": "GPL-3.0-only"}}))
    section = LicenseComplianceSection(disallowed=["GPL-3.0-only"])
    modules = [VendoredModule(ecosystem="npm", path=tmp_path)]
    results = check_license_compliance(section, modules)
    assert results[0].status == "failed"


def test_cargo_disallowed_license_fails(tmp_path):
    write_cargo_crate(tmp_path / "vendor", "badcrate-1.0.0", "GPL-3.0-only")
    section = LicenseComplianceSection(disallowed=["GPL-3.0-only"])
    modules = [VendoredModule(ecosystem="cargo", path=tmp_path)]
    results = check_license_compliance(section, modules)
    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].target == "badcrate-1.0.0"


def test_cargo_allowed_license_passes_silently(tmp_path):
    write_cargo_crate(tmp_path / "vendor", "goodcrate-1.0.0", "MIT")
    section = LicenseComplianceSection(disallowed=["GPL-3.0-only"])
    modules = [VendoredModule(ecosystem="cargo", path=tmp_path)]
    assert check_license_compliance(section, modules) == []


def test_go_modules_get_single_unsupported_warning(tmp_path):
    section = LicenseComplianceSection(disallowed=["GPL-3.0-only"])
    modules = [
        VendoredModule(ecosystem="go", path=tmp_path / "a"),
        VendoredModule(ecosystem="go", path=tmp_path / "b"),
    ]
    results = check_license_compliance(section, modules)
    assert len(results) == 1
    assert results[0].status == "warning"
    assert "unsupported" in results[0].reason


def test_no_disallowed_list_still_checks_but_finds_nothing(tmp_path):
    write_npm_package(tmp_path / "node_modules", "any-pkg", "GPL-3.0-only")
    section = LicenseComplianceSection(disallowed=[])
    modules = [VendoredModule(ecosystem="npm", path=tmp_path)]
    assert check_license_compliance(section, modules) == []


def test_missing_node_modules_directory_is_a_noop(tmp_path):
    section = LicenseComplianceSection(disallowed=["GPL-3.0-only"])
    modules = [VendoredModule(ecosystem="npm", path=tmp_path)]
    assert check_license_compliance(section, modules) == []
