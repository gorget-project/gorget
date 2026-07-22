import argparse
from pathlib import Path

import pytest

from gorget.context import build_run_context
from gorget.exceptions import GorgetConfigError


def make_args(tmp_path: Path, **overrides) -> argparse.Namespace:
    defaults = dict(
        pkg_version="1.2.3",
        old_version="1.2.2",
        dry_run=False,
        package_dir=str(tmp_path),
        pipeline_file=str(tmp_path / "pipeline.yaml"),
        gpg_keys_dir=str(tmp_path / "gpg-keys"),
        output_dir=str(tmp_path / "output"),
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_build_run_context_discovers_spec_and_derives_vars(tmp_path):
    (tmp_path / "foo.spec").write_text("Name: foo\n")
    ctx = build_run_context(make_args(tmp_path))
    assert ctx.spec_path == tmp_path / "foo.spec"
    assert ctx.vars.package == "foo"
    assert ctx.vars.spec_file == "foo.spec"
    assert ctx.vars.version == "1.2.3"
    assert ctx.vars.old_version == "1.2.2"
    assert ctx.dry_run is False


def test_build_run_context_missing_package_dir_raises(tmp_path):
    args = make_args(tmp_path, package_dir=str(tmp_path / "nonexistent"))
    with pytest.raises(GorgetConfigError, match="does not exist"):
        build_run_context(args)


def test_build_run_context_no_spec_file_raises(tmp_path):
    with pytest.raises(GorgetConfigError, match="No .spec file"):
        build_run_context(make_args(tmp_path))


def test_build_run_context_multiple_spec_files_raises(tmp_path):
    (tmp_path / "foo.spec").write_text("Name: foo\n")
    (tmp_path / "bar.spec").write_text("Name: bar\n")
    with pytest.raises(GorgetConfigError, match="Multiple .spec files"):
        build_run_context(make_args(tmp_path))


def test_build_run_context_uses_default_container_paths_when_not_overridden(tmp_path):
    (tmp_path / "foo.spec").write_text("Name: foo\n")
    args = make_args(
        tmp_path,
        pipeline_file=None,
        gpg_keys_dir=None,
        output_dir=None,
    )
    ctx = build_run_context(args)
    assert str(ctx.pipeline_file) == "/pipeline.yaml"
    assert str(ctx.gpg_keys_dir) == "/gpg-keys"
    assert str(ctx.output_dir) == "/output"
