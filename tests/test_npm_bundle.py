"""Exercise bundled updates with a local registry and real npm, without network access."""

import io
import json
import shutil
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_transform_vendor_bump import make_ctx, make_state

from gorget.config.loader import parse_pipeline_spec
from gorget.config.schema import VendorBumpEntry, VendorBumpStep, VendorModule
from gorget.dependencies.npm_bundle import _sync_lockfile, update_npm_bundle
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.transform.vendor_bump import VendorBumpHandler


@pytest.fixture
def registry(tmp_path, monkeypatch):
    requests = []
    routes = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            content = routes.get(self.path)
            self.send_response(200 if content else 404)
            self.end_headers()
            self.wfile.write(content or b"not found")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    records = {
        "leaf": {"1.0.0": {}, "1.0.1": {"dependencies": {"new-child": "1.0.0"}}},
        "parent": {"1.0.0": {"dependencies": {"leaf": "^1.0.0"}}},
        "stable": {"1.0.0": {"scripts": {"postinstall": "exit 99"}}, "1.0.1": {}},
        "new-child": {"1.0.0": {}},
    }
    for name, versions in records.items():
        metadata = {}
        for version, fields in versions.items():
            manifest = {"name": name, "version": version, **fields}
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                data = json.dumps(manifest).encode()
                entry = tarfile.TarInfo("package/package.json")
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
            tarpath = f"/{name}/-/{name}-{version}.tgz"
            routes[tarpath] = buffer.getvalue()
            metadata[version] = {**manifest, "dist": {"tarball": url + tarpath}}
        routes[f"/{name}"] = json.dumps({
            "name": name, "dist-tags": {"latest": list(versions)[-1]}, "versions": metadata,
        }).encode()
    monkeypatch.setenv("npm_config_registry", url)
    monkeypatch.setenv("npm_config_cache", str(tmp_path / "npm-cache"))
    monkeypatch.setenv("npm_config_fetch_retries", "0")
    try:
        yield requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _bundle(path, *, lock=False):
    manifest = {
        "name": "app", "version": "1.0.0", "bundleDependencies": ["parent", "stable"],
        "dependencies": {"parent": "^1.0.0", "stable": "^1.0.0", "external": "1.0.0"},
        "devDependencies": {"private-dev": "file:missing"},
        "scripts": {"prepare": "exit 99"}, "workspaces": ["missing/*"],
    }
    path.mkdir(parents=True, exist_ok=True)
    (path / "package.json").write_text(json.dumps(manifest))
    for name, extra in [("parent", {"dependencies": {"leaf": "^1.0.0"}}),
                        ("leaf", {}), ("stable", {})]:
        package = path / "node_modules" / name
        package.mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({
            "name": name, "version": "1.0.0", **extra,
        }))
    (path / "node_modules/stable/native.node").write_bytes(b"upstream native artifact")
    (path / "node_modules/stable/run").write_text("#!/bin/sh\n")
    (path / "node_modules/stable/run").chmod(0o755)
    (path / "node_modules/stable/link").symlink_to("run")
    if lock:
        packages = {"": manifest, "node_modules/external": {
            "version": "1.0.0", "resolved": "https://example.invalid/private.tgz",
        }}
        for p in (path / "node_modules").glob("*/package.json"):
            packages[p.parent.relative_to(path).as_posix()] = json.loads(p.read_text())
        (path / "package-lock.json").write_text(json.dumps({
            "lockfileVersion": 3, "packages": packages,
        }))
    return manifest


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("npm") is None, reason="requires npm")
@pytest.mark.parametrize("lock", [False, "package-lock.json", "npm-shrinkwrap.json"])
@pytest.mark.parametrize("nested", [False, True])
def test_partial_bundle_updates_nested_copy_and_keeps_external_dependencies_out(
    tmp_path, registry, lock, nested,
):
    project = tmp_path / "project"
    original = _bundle(project, lock=bool(lock))
    if lock == "npm-shrinkwrap.json":
        (project / "package-lock.json").rename(project / lock)
    if nested:
        child = project / "node_modules/parent/node_modules/leaf"
        child.mkdir(parents=True)
        (child / "package.json").write_text('{"name":"leaf","version":"1.0.0"}')
    pin = VendorBumpEntry(dependency="leaf", version="~1.0.1")
    update_npm_bundle(project, [pin])

    installed = project / "node_modules"
    assert json.loads((installed / "leaf/package.json").read_text())["version"] == "1.0.1"
    assert (installed / "new-child/package.json").is_file()
    for child in installed.rglob("leaf/package.json"):
        assert json.loads(child.read_text())["version"] == "1.0.1"
    assert not (installed / "external").exists()
    assert not any("external" in request or "private-dev" in request for request in registry)
    assert (installed / "stable/native.node").read_bytes() == b"upstream native artifact"
    assert (installed / "stable/run").stat().st_mode & 0o111
    assert (installed / "stable/link").is_symlink()
    assert not (installed / ".package-lock.json").exists()
    manifest = json.loads((project / "package.json").read_text())
    assert manifest == {**original, "overrides": {"leaf": "~1.0.1"}}
    if lock:
        packages = json.loads((project / lock).read_text())["packages"]
        assert packages["node_modules/external"]["resolved"] == "https://example.invalid/private.tgz"
        assert packages["node_modules/leaf"]["version"] == "1.0.1"
    else:
        assert not (project / "package-lock.json").exists()
    snapshot = (project / "package.json").read_bytes()
    request_count = len(registry)
    update_npm_bundle(project, [pin])
    assert (project / "package.json").read_bytes() == snapshot
    assert len(registry) == request_count  # Already-fixed bundles need no registry access.


def test_bundle_failure_does_not_publish_any_module(tmp_path, mocker):
    source = tmp_path / "source"
    _bundle(source / "one")
    _bundle(source / "two")
    ctx = make_ctx(tmp_path, source)
    state = make_state(tmp_path)
    state.source = ctx.source

    def update(module_dir, pins, toolchain):
        (module_dir / "node_modules/leaf/package.json").write_text('{"version":"changed"}')
        if module_dir.name == "two":
            raise GorgetTransientError("install failed")

    mocker.patch("gorget.transform.vendor_bump.update_npm_bundle", side_effect=update)
    with pytest.raises(GorgetTransientError, match="install failed"):
        VendorBumpHandler().run(VendorBumpStep(
            ecosystem="npm", bundled=True,
            modules=[VendorModule(path="one"), VendorModule(path="two")],
        ), ctx, state)
    assert state.source.path == source
    assert state.source.dirty is False
    for name in ("one", "two"):
        package = source / name / "node_modules/leaf/package.json"
        assert json.loads(package.read_text())["version"] == "1.0.0"


@pytest.mark.parametrize("value,ecosystem", [("true", "npm"), (True, "go")])
def test_bundle_option_rejects_invalid_usage(value, ecosystem):
    with pytest.raises(GorgetConfigError, match="bundled"):
        parse_pipeline_spec({"transform": [{
            "type": "vendor-bump", "ecosystem": ecosystem, "bundled": value,
        }]})


def test_bundle_option_parses():
    spec = parse_pipeline_spec({"transform": [{
        "type": "vendor-bump", "ecosystem": "npm", "bundled": True,
    }]})
    assert spec.transform.steps[0].bundled is True


def test_missing_bundle_target_fails_without_registry_access(tmp_path, mocker):
    _bundle(tmp_path)
    runner = mocker.patch("gorget.dependencies.npm_bundle.run")
    with pytest.raises(GorgetConfigError, match="not present"):
        update_npm_bundle(tmp_path, [VendorBumpEntry(dependency="external", version="2.0.0")])
    runner.assert_not_called()


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("npm") is None, reason="requires npm")
@pytest.mark.parametrize("field,value", [("bundleDependencies", True),
                                       ("bundledDependencies", ["parent", "stable"])])
def test_bundle_declarations_and_direct_root_update(tmp_path, registry, field, value):
    original = _bundle(tmp_path)
    original.pop("bundleDependencies")
    original["dependencies"].pop("external")
    original["dependencies"]["leaf"] = "^1.0.0"
    if isinstance(value, list):
        value = [*value, "leaf"]
    original[field] = value
    (tmp_path / "package.json").write_text(json.dumps(original))
    update_npm_bundle(tmp_path, [VendorBumpEntry(dependency="parent", version="~1.0.0"),
                               VendorBumpEntry(dependency="leaf", version="~1.0.1")])
    updated = json.loads((tmp_path / "package.json").read_text())
    assert updated[field] == value
    assert updated["dependencies"]["parent"] == "^1.0.0"  # Already satisfied; preserve its range.
    assert updated["dependencies"]["leaf"] == "~1.0.1"


def test_bundle_rejects_escaping_symlinks(tmp_path, mocker):
    _bundle(tmp_path)
    (tmp_path / "node_modules/linked").symlink_to(tmp_path, target_is_directory=True)
    runner = mocker.patch("gorget.dependencies.npm_bundle.run")
    with pytest.raises(GorgetConfigError, match="symlink"):
        update_npm_bundle(tmp_path, [VendorBumpEntry(dependency="leaf", version="~1.0.1")])
    runner.assert_not_called()


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("npm") is None, reason="requires npm")
def test_new_bundle_dependency_cannot_replace_an_external_lock_entry(tmp_path, registry):
    source = tmp_path / "source"
    _bundle(source, lock=True)
    lockfile = source / "package-lock.json"
    lock = json.loads(lockfile.read_text())
    lock["packages"]["node_modules/new-child"] = {"version": "0.9.0"}
    lockfile.write_text(json.dumps(lock))
    before = lockfile.read_bytes()
    ctx = make_ctx(tmp_path, source)
    state = make_state(tmp_path)
    state.source = ctx.source
    with pytest.raises(GorgetConfigError, match="unbundled lockfile entry"):
        VendorBumpHandler().run(VendorBumpStep(
            ecosystem="npm", bundled=True,
            pins=[VendorBumpEntry(dependency="leaf", version="~1.0.1")],
        ), ctx, state)
    assert state.source.path == source
    assert lockfile.read_bytes() == before
    assert json.loads((source / "node_modules/leaf/package.json").read_text())["version"] == "1.0.0"


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("npm") is None, reason="requires npm")
def test_existing_overrides_and_version_two_lock_are_retained(tmp_path, registry):
    manifest = _bundle(tmp_path, lock=True)
    manifest["overrides"] = {"stable": "$stable"}
    (tmp_path / "package.json").write_text(json.dumps(manifest))
    lockfile = tmp_path / "package-lock.json"
    lock = json.loads(lockfile.read_text())
    lock["lockfileVersion"] = 2
    lock["dependencies"] = {"leaf": {"version": "1.0.0"}}
    lockfile.write_text(json.dumps(lock))
    update_npm_bundle(tmp_path, [VendorBumpEntry(dependency="leaf", version="~1.0.1")])
    updated = json.loads((tmp_path / "package.json").read_text())
    assert updated["overrides"] == {"stable": "$stable", "leaf": "~1.0.1"}
    lock = json.loads(lockfile.read_text())
    assert lock["lockfileVersion"] == 3
    assert "dependencies" not in lock
    assert lock["packages"]["node_modules/stable"]["version"] == "1.0.0"


@pytest.mark.parametrize("integrity", [None, "sha512-upstream", "sha512-different"])
def test_shared_external_lock_entry_keeps_its_resolution_metadata(tmp_path, integrity):
    path = tmp_path / "package-lock.json"
    external = {"version": "1.0.0", "resolved": "https://example.invalid/private.tgz",
                "integrity": "sha512-upstream"}
    path.write_text(json.dumps({"lockfileVersion": 3, "packages": {
        "": {}, "node_modules/shared": external,
    }}))
    resolved = {"packages": {"node_modules/shared": {
        "version": "1.0.0", "resolved": "https://example.invalid/public.tgz",
        **({"integrity": integrity} if integrity else {}),
    }}}
    if integrity == "sha512-different":
        with pytest.raises(GorgetConfigError, match="unbundled lockfile entry"):
            _sync_lockfile(path, {}, {}, resolved)
        return
    _sync_lockfile(path, {}, {}, resolved)
    assert json.loads(path.read_text())["packages"]["node_modules/shared"] == {
        **external, "inBundle": True,
    }
