from gorget.config.compat import move_fetch_vendor_steps


def test_moves_legacy_vendors_before_declared_transforms_without_mutating_input():
    raw = {
        "fetch": [
            {"type": "git", "repo": "example", "ref": "main"},
            {"type": "vendor", "ecosystem": "go"},
            {"type": "url", "url": "https://example.test/checksums"},
            {"type": "vendor", "ecosystem": "cargo"},
        ],
        "transform": [{"type": "pack", "files": ["helper"], "output": "helper.tgz"}],
    }

    normalized, moved = move_fetch_vendor_steps(raw)

    assert moved == 2
    assert normalized["fetch"] == [raw["fetch"][0], raw["fetch"][2]]
    assert normalized["transform"] == [
        raw["fetch"][1],
        raw["fetch"][3],
        raw["transform"][0],
    ]
    assert len(raw["fetch"]) == 4
    assert len(raw["transform"]) == 1


def test_returns_unchanged_config_when_no_legacy_vendor_exists():
    raw = {"fetch": [{"type": "git", "repo": "example", "ref": "main"}]}

    normalized, moved = move_fetch_vendor_steps(raw)

    assert normalized is raw
    assert moved == 0
