from pathlib import Path

from gorget.config.schema import (
    PipelineSpec,
    TransformSection,
    VendorModule,
    VendorStep,
)
from gorget.policy.base import discover_vendored_modules


def test_discover_vendored_modules_from_transform():
    vendor_step = VendorStep(ecosystem="npm", modules=[VendorModule(path="ui")])
    spec = PipelineSpec(transform=TransformSection(steps=[vendor_step]))
    modules = discover_vendored_modules(spec, Path("/src"))
    assert len(modules) == 1
    assert modules[0].ecosystem == "npm"
    assert modules[0].path == Path("/src/ui")


def test_discover_vendored_modules_multi_submodule():
    spec = PipelineSpec(
        transform=TransformSection(
            steps=[
                VendorStep(
                    ecosystem="go",
                    modules=[
                        VendorModule(path="server"),
                        VendorModule(path="etcdctl"),
                        VendorModule(path="etcdutl"),
                    ],
                )
            ]
        )
    )
    modules = discover_vendored_modules(spec, Path("/src"))
    assert [m.path for m in modules] == [
        Path("/src/server"),
        Path("/src/etcdctl"),
        Path("/src/etcdutl"),
    ]
    assert all(m.ecosystem == "go" for m in modules)


def test_discover_vendored_modules_none_when_no_vendor_step():
    spec = PipelineSpec()
    assert discover_vendored_modules(spec, Path("/src")) == []
