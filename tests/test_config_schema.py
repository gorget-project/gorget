from gorget.config.schema import (
    GitStep,
    PipelineSpec,
    SpecSourceStep,
    SpecUpdateStep,
    UrlStep,
    VendorModule,
    VendorStep,
)


def test_pipeline_spec_defaults_are_empty():
    spec = PipelineSpec()
    assert spec.fetch == []
    assert spec.transform.steps == []
    assert spec.toolchain.entries == []
    assert spec.verify.steps == []
    assert spec.policy.rules == {}
    assert spec.patches.entries == []
    assert spec.post.steps == []


def test_spec_update_step_defaults():
    step = SpecUpdateStep()
    assert step.set_version is True
    assert step.reset_release == "1"
    assert step.substitutions == []


def test_spec_source_step_defaults_to_all_indices():
    step = SpecSourceStep()
    assert step.index is None
    assert step.rename is None


def test_url_step_requires_url():
    step = UrlStep(url="https://example.com/x.tar.gz")
    assert step.filename is None


def test_git_step_defaults():
    step = GitStep(repo="https://example.com/x.git", ref="v1.0.0")
    assert step.shallow is True
    assert step.subdir is None


def test_vendor_step_default_single_module():
    step = VendorStep(ecosystem="go")
    assert step.modules == [VendorModule(path=".")]
