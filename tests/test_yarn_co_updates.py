from unittest.mock import Mock

import pytest

from gorget.config.schema import VendorBumpEntry
from gorget.dependencies import DependencyCopy, DependencyInventory
from gorget.dependencies.js_updates import parent_updates
from gorget.exceptions import GorgetTransientError


def test_serialize_javascript_target_derives_compatible_terser_parent(tmp_path):
    inventory = DependencyInventory("yarn", tmp_path, (
        DependencyCopy("serialize-javascript", "6.0.2", "serialize-javascript@npm:^6"),
        DependencyCopy("terser-webpack-plugin", "5.3.16", "terser-webpack-plugin@npm:^5", (
            ("serialize-javascript", "npm:^6.0.2"),
        )),
    ))
    metadata = Mock(return_value={
        "version": "5.6.1", "dependencies": {"serialize-javascript": "^7.1.4"},
    })
    updates = parent_updates([
        VendorBumpEntry(dependency="serialize-javascript", version="~7.1.4"),
    ], inventory, metadata)
    assert updates == [VendorBumpEntry(dependency="terser-webpack-plugin@^5", version="5.6.1")]
    metadata.assert_called_once_with("terser-webpack-plugin", "^5")


def test_same_major_child_override_needs_no_registry_parent_query(tmp_path):
    inventory = DependencyInventory("yarn", tmp_path, (
        DependencyCopy("foo", "1.0.0", "foo@npm:1.0.0"),
        DependencyCopy("parent", "2.0.0", "parent@npm:^2", (("foo", "npm:1.0.0"),)),
    ))
    metadata = Mock()
    assert parent_updates([VendorBumpEntry(dependency="foo", version="1.0.1")],
                          inventory, metadata) == []
    metadata.assert_not_called()


@pytest.mark.parametrize("candidate", [
    {"version": "5.6.1", "dependencies": {"child": "^6"}},
    {"version": "6.0.0", "dependencies": {"child": "^7"}},
    {"version": "5.6.1", "optionalDependencies": {"child": "^6"}},
])
def test_parent_co_update_fails_closed_when_same_major_cannot_accept_child(tmp_path, candidate):
    inventory = DependencyInventory("yarn", tmp_path, (
        DependencyCopy("child", "6.0.0", "child@npm:^6"),
        DependencyCopy("parent", "5.0.0", "parent@npm:^5", (("child", "npm:^6"),)),
    ))
    with pytest.raises(GorgetTransientError, match="same-major parent"):
        parent_updates([VendorBumpEntry(dependency="child", version="7.0.0")],
                       inventory, Mock(return_value=candidate))


@pytest.mark.parametrize("target", ["~1", "~1.2", "v1.2.4"])
def test_existing_partial_and_v_prefixed_targets_remain_supported(tmp_path, target):
    inventory = DependencyInventory("yarn", tmp_path, (
        DependencyCopy("foo", "1.2.3", "foo@npm:^1"),
    ))
    metadata = Mock()
    assert parent_updates([VendorBumpEntry(dependency="foo", version=target)],
                          inventory, metadata) == []
    metadata.assert_not_called()


def test_parent_candidate_must_accept_every_requested_child_update(tmp_path):
    inventory = DependencyInventory("yarn", tmp_path, (
        DependencyCopy("a", "1.0.0", "a@npm:^1"),
        DependencyCopy("b", "1.0.0", "b@npm:^1"),
        DependencyCopy("parent", "3.0.0", "parent@npm:^3", (
            ("a", "npm:^1"), ("b", "npm:^1"),
        )),
    ))
    metadata = Mock(return_value={
        "version": "3.1.0", "dependencies": {"a": "^2", "b": "^1"},
    })
    with pytest.raises(GorgetTransientError, match="parent requires b"):
        parent_updates([
            VendorBumpEntry(dependency="a", version="2.0.0"),
            VendorBumpEntry(dependency="b", version="2.0.0"),
        ], inventory, metadata)
    metadata.assert_called_once_with("parent", "^3")
