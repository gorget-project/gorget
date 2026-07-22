import tarfile

from gorget.config.schema import VendorModule
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
    assert any(name.endswith("modules.txt") for name in names)


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


def test_combine_falls_back_to_sanitized_path_when_name_missing(tmp_path):
    vendor_dir = _make_vendor_dir(tmp_path / "nested" / "path", "vendor", {"x.txt": "x"})
    archive_path = tmp_path / "out.tar.gz"
    combine_vendor_archives([(VendorModule(path="nested/path"), vendor_dir)], archive_path)

    with tarfile.open(archive_path) as tar:
        names = tar.getnames()
    assert any(name.startswith("nested_path") for name in names)
