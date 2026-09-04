import tarfile

import pytest

from gorget.config.schema import VendorModule
from gorget.exceptions import GorgetConfigError
from gorget.fetch.vendor.combine import combine_vendor_archives


def _make_vendor_dir(base, name, files):
    d = base / name
    d.mkdir(parents=True)
    for filename, content in files.items():
        (d / filename).write_text(content)
    return d


def test_combine_single_module_uses_sanitized_path_as_label(tmp_path):
    vendor_dir = _make_vendor_dir(tmp_path, "vendor", {"modules.txt": "example.com/x v1.0.0"})
    archive_path = tmp_path / "out.tar.gz"
    combine_vendor_archives([(VendorModule(path="."), vendor_dir)], archive_path)

    with tarfile.open(archive_path) as tar:
        names = tar.getnames()
    assert any(name == "vendor" or name.startswith("vendor/") for name in names)
    assert any(name.endswith("modules.txt") for name in names)


def test_combine_single_module_honors_explicit_name_override(tmp_path):
    vendor_dir = _make_vendor_dir(tmp_path, "vendor", {"modules.txt": "example.com/x v1.0.0"})
    archive_path = tmp_path / "out.tar.gz"
    combine_vendor_archives(
        [(VendorModule(path=".", name="something-else"), vendor_dir)], archive_path
    )

    with tarfile.open(archive_path) as tar:
        names = tar.getnames()
    assert any(name == "something-else" or name.startswith("something-else/") for name in names)
    assert not any(name == "vendor" or name.startswith("vendor/") for name in names)


def test_combine_multi_submodule_uses_one_directory_per_module(tmp_path):
    server_vendor = _make_vendor_dir(tmp_path / "server", "vendor", {"a.go": "package a"})
    etcdctl_vendor = _make_vendor_dir(tmp_path / "etcdctl", "vendor", {"b.go": "package b"})

    archive_path = tmp_path / "etcd-vendor.tar.gz"
    combine_vendor_archives(
        [
            (VendorModule(path="server", name="server"), server_vendor),
            (VendorModule(path="etcdctl", name="etcdctl"), etcdctl_vendor),
        ],
        archive_path,
    )

    with tarfile.open(archive_path) as tar:
        names = set(tar.getnames())
    assert any(name == "server" or name.startswith("server/") for name in names)
    assert any(name == "etcdctl" or name.startswith("etcdctl/") for name in names)
    assert any(name.endswith("server/a.go") for name in names)
    assert any(name.endswith("etcdctl/b.go") for name in names)


def test_combine_single_module_uses_bare_vendor_regardless_of_path(tmp_path):
    """Regression test: found via etcd, which vendors server/etcdctl/etcdutl
    as three *independent* `vendor:` steps -- each with exactly one module at
    a non-trivial path (e.g. "server") -- each producing its own archive.
    %prep extracts each with `-C server` (etc.), so the archive itself must
    already be bare "vendor/" -- a "server/vendor/" wrapper would double the
    "server/" nesting after extraction. A lone module with no explicit name
    has nothing to disambiguate against, so its path shouldn't affect the
    archive layout at all.
    """
    vendor_dir = _make_vendor_dir(tmp_path / "nested" / "path", "vendor", {"x.txt": "x"})
    archive_path = tmp_path / "out.tar.gz"
    combine_vendor_archives([(VendorModule(path="nested/path"), vendor_dir)], archive_path)

    with tarfile.open(archive_path) as tar:
        names = tar.getnames()
    assert any(name == "vendor" or name.startswith("vendor/") for name in names)
    assert not any(name.startswith("nested_path") for name in names)


def test_combine_places_root_files_alongside_bare_vendor(tmp_path):
    """Regression test: found migrating grafana13.1 -- a vendor archive
    containing only "vendor/" has a single common top-level directory, which
    `go_vendor_license --use-archive` treats as an independently-wrapped
    sibling archive rather than nesting it inside the source tree, so %check
    can never find the vendored license files it's looking for. go.mod/go.sum
    alongside "vendor/" (matching go-vendor-tools' own archive convention)
    breaks that single-top-level-directory heuristic.
    """
    vendor_dir = _make_vendor_dir(tmp_path, "vendor", {"modules.txt": "example.com/x v1.0.0"})
    go_mod = tmp_path / "go.mod"
    go_mod.write_text("module example.com/x")
    archive_path = tmp_path / "out.tar.gz"
    combine_vendor_archives(
        [(VendorModule(path="."), vendor_dir)], archive_path, root_files=[go_mod]
    )

    with tarfile.open(archive_path) as tar:
        names = tar.getnames()
    assert "go.mod" in names
    assert any(name == "vendor" or name.startswith("vendor/") for name in names)


def test_combine_ignores_root_files_for_multi_module_archives(tmp_path):
    """root_files has no clean placement in the multi-module/labeled case --
    each labeled directory already stands in for an independent module root
    verified elsewhere via go-vendor-tools.toml's go_mod_dir (see this
    module's docstring) -- so passing root_files here must be a no-op rather
    than silently misplacing them at the combined archive's top level.
    """
    server_vendor = _make_vendor_dir(tmp_path / "server", "vendor", {"a.go": "package a"})
    etcdctl_vendor = _make_vendor_dir(tmp_path / "etcdctl", "vendor", {"b.go": "package b"})
    stray_go_mod = tmp_path / "go.mod"
    stray_go_mod.write_text("module example.com/x")
    archive_path = tmp_path / "etcd-vendor.tar.gz"

    combine_vendor_archives(
        [
            (VendorModule(path="server", name="server"), server_vendor),
            (VendorModule(path="etcdctl", name="etcdctl"), etcdctl_vendor),
        ],
        archive_path,
        root_files=[stray_go_mod],
    )

    with tarfile.open(archive_path) as tar:
        names = tar.getnames()
    assert "go.mod" not in names


def test_combine_honors_tar_bz2_extension_and_actually_bzip2_compresses(tmp_path):
    vendor_dir = _make_vendor_dir(tmp_path, "vendor", {"modules.txt": "example.com/x v1.0.0"})
    archive_path = tmp_path / "out.tar.bz2"
    combine_vendor_archives([(VendorModule(path="."), vendor_dir)], archive_path)

    assert archive_path.read_bytes()[:3] == b"BZh"
    with tarfile.open(archive_path, "r:bz2") as tar:
        names = tar.getnames()
    assert any(name.endswith("modules.txt") for name in names)


def test_combine_rejects_unrecognized_archive_extension(tmp_path):
    vendor_dir = _make_vendor_dir(tmp_path, "vendor", {"modules.txt": "example.com/x v1.0.0"})
    archive_path = tmp_path / "out.zip"
    with pytest.raises(GorgetConfigError, match=r"out\.zip"):
        combine_vendor_archives([(VendorModule(path="."), vendor_dir)], archive_path)
