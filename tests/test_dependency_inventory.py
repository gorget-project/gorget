"""Dependency-copy contracts shared by updates, policy, and Provides."""

import json
from pathlib import Path

import pytest

from gorget.config.schema import VendorConstraintEntry, VendorModule
from gorget.dependencies import (
    DependencyCopy,
    DependencyInventory,
    bundled_provides,
    read_inventory,
)
from gorget.policy.base import VendoredModule
from gorget.policy.vendor_constraints import check_vendor_constraints


@pytest.mark.parametrize("ecosystem", ["npm", "pnpm", "yarn", "cargo"])
def test_inventory_preserves_old_copies_and_locations(tmp_path, ecosystem):
    if ecosystem == "npm":
        (tmp_path / "package-lock.json").write_text(
            json.dumps(
                {
                    "packages": {
                        "node_modules/foo": {"version": "2.0.0"},
                        "node_modules/parent/node_modules/foo": {"version": "1.0.0", "dev": True},
                    }
                }
            )
        )
    elif ecosystem == "pnpm":
        (tmp_path / "pnpm-lock.yaml").write_text(
            "snapshots:\n  foo@2.0.0: {}\n  foo@1.0.0: {}\n"
            "importers:\n  .:\n    dependencies:\n      foo:\n        version: 2.0.0\n"
        )
    elif ecosystem == "yarn":
        (tmp_path / "yarn.lock").write_text(
            '__metadata:\n  version: 8\n"foo@npm:^2":\n  version: 2.0.0\n'
            '  resolution: "foo@npm:2.0.0"\n"foo@npm:^1":\n  version: 1.0.0\n'
            '  resolution: "foo@npm:1.0.0"\n'
        )
    else:
        (tmp_path / "Cargo.lock").write_text(
            '[[package]]\nname="foo"\nversion="2.0.0"\n[[package]]\nname="foo"\nversion="1.0.0"\n'
        )
    inventory = read_inventory(ecosystem, tmp_path)
    assert {copy.version for copy in inventory.find("foo")} == {"1.0.0", "2.0.0"}
    failures = inventory.violations("foo", "2.0.0")
    assert len(failures) == 1
    assert failures[0].location
    results = check_vendor_constraints(
        [VendorConstraintEntry(ecosystem=ecosystem, package="foo", version="2.0.0", reason="CVE")],
        [VendoredModule(ecosystem=ecosystem, path=tmp_path)],
    )
    assert results[0].status == "failed"
    assert failures[0].location in results[0].reason
    if ecosystem != "cargo":
        provides = bundled_provides(ecosystem, tmp_path, [VendorModule(path=".")])
        assert set(provides["all"]) == inventory.provides()


def test_prefix_constraints_check_newer_copies_as_well_as_the_oldest():
    inventory = DependencyInventory(
        "npm",
        Path("."),
        (DependencyCopy("foo", "1.2.3", "first"), DependencyCopy("foo", "2.0.0", "second")),
    )
    assert inventory.violations("foo", "~1.2")[0].location == "second"


def test_classic_yarn_retains_two_descriptors_with_the_same_version(tmp_path):
    (tmp_path / "yarn.lock").write_text(
        'foo@^1.0:\n  version "1.2.3"\nfoo@~1.2:\n  version "1.2.3"\n'
    )
    copies = read_inventory("yarn", tmp_path).find("foo")
    assert len(copies) == 2
    assert copies[0].location != copies[1].location


def test_go_inventory_respects_the_declared_workspace_scope(tmp_path):
    import subprocess
    from unittest.mock import Mock

    (tmp_path / "go.work").touch()
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, "example.org/foo v2.0.0", ""))
    read_inventory("go", tmp_path, ["example.org/foo"], runner=runner, use_workspace=True)
    assert "env" not in runner.call_args.kwargs
    read_inventory("go", tmp_path, ["example.org/foo"], runner=runner, use_workspace=False)
    assert runner.call_args.kwargs["env"] == {"GOWORK": "off"}


def test_maven_inventory_checks_each_resolved_copy(tmp_path):
    import subprocess
    from unittest.mock import Mock

    runner = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, " org.example:foo:jar:2.0.0:compile\n org.example:foo:jar:1.0.0:compile", ""
        )
    )
    inventory = read_inventory("maven", tmp_path, ["org.example:foo"], runner=runner)
    assert len(inventory.find("org.example:foo")) == 2
    assert inventory.violations("org.example:foo", "2.0.0")[0].version == "1.0.0"
