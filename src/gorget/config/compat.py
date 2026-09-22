"""Temporary adapters for deprecated pipeline syntax.

Delete this module and its call in ``config.loader.parse_pipeline_spec`` when
support for ``fetch: vendor`` ends.
"""

from __future__ import annotations


def move_fetch_vendor_steps(raw: dict) -> tuple[dict, int]:
    """Move legacy ``fetch: vendor`` entries before declared transforms.

    The function does not mutate ``raw``. Invalid section types pass through so
    the normal parser reports its usual configuration error.
    """
    raw_fetch = raw.get("fetch")
    if not isinstance(raw_fetch, list):
        return raw, 0

    vendor_steps = []
    fetch_steps = []
    for step in raw_fetch:
        if isinstance(step, dict) and step.get("type") == "vendor":
            vendor_steps.append(step)
        else:
            fetch_steps.append(step)
    if not vendor_steps:
        return raw, 0

    normalized = dict(raw)
    normalized["fetch"] = fetch_steps

    raw_transform = raw.get("transform", [])
    if isinstance(raw_transform, list):
        normalized["transform"] = [*vendor_steps, *raw_transform]

    return normalized, len(vendor_steps)
