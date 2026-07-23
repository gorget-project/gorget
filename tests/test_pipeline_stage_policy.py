import json
import subprocess

import pytest

from gorget.config.schema import (
    LicenseComplianceSection,
    PipelineSpec,
    PolicySection,
    VendorConstraintEntry,
    VendorModule,
    VendorStep,
)
from gorget.config.substitution import SubstitutionVars
from gorget.context import RunContext
from gorget.exceptions import GorgetPolicyViolation
from gorget.pipeline.result import PipelineReport
from gorget.pipeline.stages.policy import PolicyStage
from gorget.pipeline.state import StageState


def make_ctx(package_dir, dry_run=False):
    return RunContext(
        package_dir=package_dir,
        pipeline_file=package_dir / "pipeline.yaml",
        gpg_keys_dir=package_dir / "gpg-keys",
        output_dir=package_dir / "output",
        dry_run=dry_run,
        spec_path=package_dir / "foo.spec",
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
    )


def make_state(work_dir, source_dir=None):
    report = PipelineReport(package="foo", version="1.2.3", old_version=None, dry_run=False)
    return StageState(work_dir=work_dir, spec=None, report=report, source_dir=source_dir)


def write_npm_package(source_dir, package, license_value, version="2.17.5"):
    pkg_dir = source_dir / "node_modules" / package
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.json").write_text(
        json.dumps({"name": package, "version": version, "license": license_value})
    )


def test_dry_run_skips_entirely(tmp_path):
    ctx = make_ctx(tmp_path, dry_run=True)
    state = make_state(tmp_path)
    spec = PipelineSpec(policy=PolicySection(audit=True))
    result = PolicyStage().run(ctx, spec, state)
    assert result.status == "skipped"
    assert result.reason == "dry-run"


def test_no_policy_configured_skips_with_warning(tmp_path):
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    result = PolicyStage().run(ctx, PipelineSpec(), state)
    assert result.status == "skipped"
    assert result.reason == "no policy configured"


def test_vendor_constraints_success(tmp_path):
    write_npm_package(tmp_path, "sanitize-html", "MIT", version="2.17.5")
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, source_dir=tmp_path)
    spec = PipelineSpec(
        fetch=[VendorStep(ecosystem="npm", modules=[VendorModule(path=".")])],
        policy=PolicySection(
            vendor_constraints=[
                VendorConstraintEntry(
                    package="sanitize-html", ecosystem="npm", version="2.17.5", reason="CVE fix"
                )
            ]
        ),
    )
    result = PolicyStage().run(ctx, spec, state)
    assert result.status == "success"
    assert result.details == [
        {
            "type": "vendor-constraints",
            "target": "sanitize-html",
            "status": "passed",
            "reason": None,
        }
    ]


def test_vendor_constraints_failure_raises_policy_violation(tmp_path):
    write_npm_package(tmp_path, "sanitize-html", "MIT", version="2.16.0")
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, source_dir=tmp_path)
    spec = PipelineSpec(
        fetch=[VendorStep(ecosystem="npm", modules=[VendorModule(path=".")])],
        policy=PolicySection(
            vendor_constraints=[
                VendorConstraintEntry(
                    package="sanitize-html", ecosystem="npm", version="2.17.5", reason="CVE fix"
                )
            ]
        ),
    )
    with pytest.raises(GorgetPolicyViolation, match="Policy violation"):
        PolicyStage().run(ctx, spec, state)


def test_audit_go_mod_verify_fails_closed(tmp_path, mocker):
    mocker.patch(
        "gorget.policy.audit.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="checksum mismatch"
        ),
    )
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, source_dir=tmp_path)
    spec = PipelineSpec(
        fetch=[VendorStep(ecosystem="go", modules=[VendorModule(path=".")])],
        policy=PolicySection(audit=True),
    )
    with pytest.raises(GorgetPolicyViolation, match="checksum mismatch"):
        PolicyStage().run(ctx, spec, state)


def test_audit_npm_warning_does_not_raise(tmp_path, mocker):
    audit_stdout = json.dumps({"metadata": {"vulnerabilities": {"high": 1}}})
    mocker.patch(
        "gorget.policy.audit.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout=audit_stdout, stderr=""
        ),
    )
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, source_dir=tmp_path)
    spec = PipelineSpec(
        fetch=[VendorStep(ecosystem="npm", modules=[VendorModule(path=".")])],
        policy=PolicySection(audit=True),
    )
    result = PolicyStage().run(ctx, spec, state)
    assert result.status == "success"
    assert result.details[0]["status"] == "warning"


def test_license_compliance_failure_raises(tmp_path):
    write_npm_package(tmp_path, "bad-pkg", "GPL-3.0-only")
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, source_dir=tmp_path)
    spec = PipelineSpec(
        fetch=[VendorStep(ecosystem="npm", modules=[VendorModule(path=".")])],
        policy=PolicySection(
            license_compliance=LicenseComplianceSection(disallowed=["GPL-3.0-only"])
        ),
    )
    with pytest.raises(GorgetPolicyViolation, match="license-compliance"):
        PolicyStage().run(ctx, spec, state)


def test_multiple_failures_are_all_reported_together(tmp_path):
    write_npm_package(tmp_path, "sanitize-html", "MIT", version="2.16.0")
    write_npm_package(tmp_path, "bad-pkg", "GPL-3.0-only")
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path, source_dir=tmp_path)
    spec = PipelineSpec(
        fetch=[VendorStep(ecosystem="npm", modules=[VendorModule(path=".")])],
        policy=PolicySection(
            vendor_constraints=[
                VendorConstraintEntry(
                    package="sanitize-html", ecosystem="npm", version="2.17.5", reason="CVE fix"
                )
            ],
            license_compliance=LicenseComplianceSection(disallowed=["GPL-3.0-only"]),
        ),
    )
    with pytest.raises(GorgetPolicyViolation) as exc_info:
        PolicyStage().run(ctx, spec, state)
    message = str(exc_info.value)
    assert "sanitize-html" in message
    assert "bad-pkg" in message
    assert "2 check(s)" in message
