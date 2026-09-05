from pathlib import Path

from gorget.config.schema import VendorModule, VendorStep
from gorget.fetch.vendor.base import VendoredModule, resolve_vendored_modules


def test_resolve_default_vendored_module():
    modules = resolve_vendored_modules(VendorStep(ecosystem="go"), Path("/workspace"))
    assert modules == (
        VendoredModule(ecosystem="go", path=Path("/workspace")),
    )


def test_resolve_named_vendored_module():
    vendor_step = VendorStep(ecosystem="npm", modules=[VendorModule(path="ui")])
    modules = resolve_vendored_modules(vendor_step, Path("/workspace"))
    assert len(modules) == 1
    assert modules[0].ecosystem == "npm"
    assert modules[0].path == Path("/workspace/ui")


def test_resolve_multiple_vendored_modules():
    step = VendorStep(
        ecosystem="go",
        modules=[
            VendorModule(path="server"),
            VendorModule(path="etcdctl"),
            VendorModule(path="etcdutl"),
        ],
    )
    modules = resolve_vendored_modules(step, Path("/workspace"))
    assert [m.path for m in modules] == [
        Path("/workspace/server"),
        Path("/workspace/etcdctl"),
        Path("/workspace/etcdutl"),
    ]
    assert all(m.ecosystem == "go" for m in modules)
