from unittest.mock import Mock

from gorget.config.schema import MacroSubstitution, SpecUpdateStep
from gorget.config.substitution import SubstitutionVars
from gorget.fetch.base import FetchContext
from gorget.fetch.spec_update import SpecUpdateHandler


def make_ctx(spec):
    return FetchContext(
        work_dir=Mock(),
        package_dir=Mock(),
        spec=spec,
        vars=SubstitutionVars(
            version="2.0.0", old_version="1.0.0", package="foo", spec_file="foo.spec"
        ),
        dry_run=False,
    )


def test_spec_update_calls_set_version_and_reset_release():
    spec = Mock()
    step = SpecUpdateStep(set_version=True, reset_release="1")
    artifacts = SpecUpdateHandler().run(step, make_ctx(spec))
    assert artifacts == []
    spec.set_version.assert_called_once_with("2.0.0")
    spec.reset_release.assert_called_once_with("1")


def test_spec_update_skips_version_and_release_when_disabled():
    spec = Mock()
    step = SpecUpdateStep(set_version=False, reset_release=None)
    SpecUpdateHandler().run(step, make_ctx(spec))
    spec.set_version.assert_not_called()
    spec.reset_release.assert_not_called()


def test_spec_update_applies_substitutions_in_order():
    spec = Mock()
    subs = [
        MacroSubstitution(pattern="a", replacement="1"),
        MacroSubstitution(pattern="b", replacement="2"),
    ]
    step = SpecUpdateStep(set_version=False, reset_release=None, substitutions=subs)
    ctx = make_ctx(spec)
    SpecUpdateHandler().run(step, ctx)
    assert spec.apply_substitution.call_count == 2
    spec.apply_substitution.assert_any_call(subs[0], ctx.vars)
    spec.apply_substitution.assert_any_call(subs[1], ctx.vars)
