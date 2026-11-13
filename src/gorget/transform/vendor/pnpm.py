"""Generate pnpm vendor trees."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC
from email.utils import parsedate_to_datetime
from hashlib import sha256
from os import walk
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from gorget.config.schema import _DEFAULT_NPM_PLATFORMS, ToolchainEntry, VendorPlatform
from gorget.dependencies.lockfiles import PACKAGE_NAME_RE as _PACKAGE_NAME_RE
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.package_manager import PackageManager
from gorget.pnpm import install_pnpm_cli, resolve_pnpm_version
from gorget.util.archive import pack_files
from gorget.util.subprocess_run import run


def _resolve_pnpm_version(
    manifest: dict[str, object], manifest_path: Path, module_dir: Path,
    toolchain: Sequence[ToolchainEntry],
) -> str:
    return resolve_pnpm_version(manifest, manifest_path, module_dir, toolchain, runner=run)


class PnpmVendor:
    def source_files(self, *, sync_go_modules: bool = False) -> tuple[str, ...]:
        return ()

    def vendor(
        self,
        module_dir: Path,
        toolchain: Sequence[ToolchainEntry] = (),
        package_dir: Path | None = None,
        use_workspace: bool = True,
        platforms: Sequence[VendorPlatform] = (),
        task: str = "build",
    ) -> Path:
        resolved = platforms or _DEFAULT_NPM_PLATFORMS
        store_dir = Path(tempfile.mkdtemp(prefix="gorget-pnpm-store-"))
        try:
            with _preserve_node_modules(module_dir) as clean_node_modules:
                for platform in resolved:
                    cmd = [
                        "pnpm",
                        "fetch",
                        "--ignore-scripts",
                        "--store-dir",
                        str(store_dir),
                    ]
                    result = PackageManager(module_dir, toolchain, runner=run).run(
                        cmd,
                        env={
                            "CI": "true",
                            "npm_config_cpu": platform.cpu,
                            "npm_config_os": platform.os,
                            "npm_config_libc": platform.libc,
                        },
                    )
                    if result.returncode != 0:
                        raise GorgetTransientError(
                            f"pnpm fetch failed for {platform.cpu}/{platform.os} "
                            f"in {module_dir}: {result.stderr.strip()}"
                        )
                    clean_node_modules()
            _normalize_store(store_dir)
            return store_dir
        except BaseException:
            shutil.rmtree(store_dir, ignore_errors=True)
            raise

    def cleanup(self, store_dir: Path) -> None:
        """Remove the temporary store after the common archiver has consumed it."""
        shutil.rmtree(store_dir, ignore_errors=True)

    def archive_root_files(self, module_dir: Path) -> list[Path]:
        return []

    def offline_cache(
        self,
        module_dir: Path,
        archive_path: Path,
        toolchain: Sequence[ToolchainEntry] = (),
        platforms: Sequence[VendorPlatform] = (),
        metadata_packages: Sequence[str] = (),
        additional_modules: Sequence[Path] = (),
    ) -> None:
        """Build an offline bundle with the module's pinned pnpm CLI, store,
        and registry metadata. Work from a scratch copy so fetch never edits
        the upstream checkout.
        """
        manifest_path = module_dir / "package.json"
        lockfile_path = module_dir / "pnpm-lock.yaml"
        if not manifest_path.is_file() or not lockfile_path.is_file():
            raise GorgetConfigError(
                f"pnpm offline cache requires package.json and pnpm-lock.yaml in {module_dir}"
            )
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise GorgetConfigError(f"Could not read {manifest_path}: {exc}") from exc
        if not isinstance(manifest, dict):
            raise GorgetConfigError(f"Expected an object in {manifest_path}")
        pnpm_version = _resolve_pnpm_version(manifest, manifest_path, module_dir, toolchain)
        for other in additional_modules:
            other_manifest = other / "package.json"
            if not (other / "pnpm-lock.yaml").is_file():
                raise GorgetConfigError(f"pnpm offline cache requires pnpm-lock.yaml in {other}")
            version = _resolve_pnpm_version(
                json.loads(other_manifest.read_text()), other_manifest, other, toolchain,
            )
            if version != pnpm_version:
                raise GorgetConfigError(
                    "A shared pnpm offline cache requires the same pnpm version for all modules; "
                    "use separate vendor steps for different versions"
                )
        major, minor = (int(part) for part in pnpm_version.split(".", 2)[:2])

        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="_pnpm_offline_cache_", dir=archive_path.parent
        ) as tmp:
            root = Path(tmp)
            scratch_modules = []
            for index, source in enumerate((module_dir, *additional_modules)):
                scratch = root / f"module-{index}"
                shutil.copytree(
                    source, scratch,
                    ignore=shutil.ignore_patterns(
                        ".git", "node_modules", ".pnpm-store", ".pnpm-cache",
                    ),
                )
                scratch_modules.append(scratch)
            scratch_module = scratch_modules[0]
            pnpm_root = root / ".pnpm"
            pnpm_command = install_pnpm_cli(
                pnpm_root, scratch_module, pnpm_version, toolchain, runner=run,
            )

            store_dir = root / ".pnpm-store"
            store_dir.mkdir()
            cache_dir = root / ".pnpm-cache"
            cache_dir.mkdir()
            # Older pnpm versions lack platform flags. --force fetches all optional packages.
            supports_platform_flags = (major, minor) >= (10, 14)
            install_platforms = (
                platforms or _DEFAULT_NPM_PLATFORMS if supports_platform_flags else (None,)
            )
            for scratch_module in scratch_modules:
                for platform in install_platforms:
                    platform_args = (
                        ["--cpu", platform.cpu, "--os", platform.os, "--libc", platform.libc]
                        if platform is not None
                        else []
                    )
                    install_result = PackageManager(scratch_module, toolchain, runner=run).run(
                        [
                            *pnpm_command,
                            "install",
                            "--force",
                            "--ignore-scripts",
                            "--frozen-lockfile",
                            "--store-dir",
                            str(store_dir),
                            *platform_args,
                        ],
                        env={"CI": "true", "XDG_CACHE_HOME": str(cache_dir)},
                    )
                    if install_result.returncode != 0:
                        target = f"{platform.cpu}/{platform.os}" if platform else "all platforms"
                        raise GorgetTransientError(
                            f"pnpm install failed for {target} "
                            f"in {scratch_module}: {install_result.stderr.strip()}"
                        )
                    node_modules = scratch_module / "node_modules"
                    if node_modules.exists():
                        shutil.rmtree(node_modules)

                self._complete_metadata_cache(
                    metadata_packages,
                    cache_dir,
                    scratch_module,
                    toolchain,
                    pnpm_version,
                )
            _remove_project_links(store_dir)
            pack_files(
                [
                    (pnpm_root, ".pnpm"),
                    (store_dir, ".pnpm-store"),
                    (cache_dir, ".pnpm-cache"),
                ],
                archive_path,
            )

    def _complete_metadata_cache(
        self,
        packages: Sequence[str],
        cache_dir: Path,
        module_dir: Path,
        toolchain: Sequence[ToolchainEntry],
        pnpm_version: str,
    ) -> None:
        """Fill full packument entries missing from pnpm's generated cache.

        Some offline builds need full packuments that pnpm did not persist.
        Add only the package names declared by the pipeline and skip entries
        that the install already cached.
        """
        if not packages:
            return
        major, minor = (int(part) for part in pnpm_version.split(".", 2)[:2])
        if major not in (11, 12):
            raise GorgetConfigError(
                f"metadata-packages requires pnpm 11 or 12; found pnpm {pnpm_version}"
            )
        # pnpm 11 and 12 share the v11 metadata cache directory.
        metadata_root = cache_dir / "pnpm" / "v11" / "metadata-full"

        registries: dict[str, str] = {}
        for package_name in sorted(set(packages)):
            if not _PACKAGE_NAME_RE.fullmatch(package_name):
                raise GorgetConfigError(
                    f"Invalid npm package name in metadata-packages: {package_name!r}"
                )
            scope = package_name.split("/", 1)[0] if package_name.startswith("@") else ""
            registry = registries.get(scope)
            if registry is None:
                registry = self._registry_for(module_dir, scope, toolchain)
                registries[scope] = registry
            metadata_path = self._metadata_path(
                metadata_root, registry, package_name, (major, minor) >= (12, 4)
            )
            if metadata_path.is_file():
                continue
            self._download_packument(registry, package_name, metadata_path)

    @staticmethod
    def _registry_for(module_dir: Path, scope: str, toolchain: Sequence[ToolchainEntry]) -> str:
        key = f"{scope}:registry" if scope else "registry"
        result = PackageManager(module_dir, toolchain, runner=run).run(
            ["npm", "config", "get", key]
        )
        registry = result.stdout.strip()
        if scope and (result.returncode != 0 or not registry.startswith(("http://", "https://"))):
            result = PackageManager(module_dir, toolchain, runner=run).run(
                ["npm", "config", "get", "registry"]
            )
            registry = result.stdout.strip()
        if result.returncode != 0 or not registry.startswith(("http://", "https://")):
            raise GorgetConfigError(f"Could not resolve npm registry for {key}: {registry!r}")
        return registry.rstrip("/")

    @staticmethod
    def _metadata_path(
        metadata_root: Path, registry: str, package_name: str, path_aware: bool
    ) -> Path:
        parsed = urlparse(registry)
        if not parsed.hostname:
            raise GorgetConfigError(f"Invalid npm registry URL: {registry!r}")
        if path_aware:
            registry_key = f"{parsed.scheme}%3A+{parsed.hostname}"
            port = parsed.port
            if port is not None and (parsed.scheme, port) not in {("http", 80), ("https", 443)}:
                registry_key += f"+{port}"
            path = parsed.path.strip("/")
            if path:
                parts = [quote(part, safe="-._").replace("~", "%7E") for part in path.split("/")]
                registry_key += "%2F" + "+".join(parts)
                if path.lower() != path:
                    registry_key += f"%5F{sha256(path.encode()).hexdigest()}"
            if registry_key.endswith("."):
                registry_key = f"{registry_key[:-1]}%2E"
            if len(registry_key) > 255:
                registry_key = sha256(registry_key.encode()).hexdigest()
        else:
            registry_key = parsed.netloc
        encoded_name = package_name
        if path_aware and package_name.lower() != package_name:
            encoded_name += f"_{sha256(package_name.encode()).hexdigest()}"
        return metadata_root / registry_key / f"{encoded_name}.jsonl"

    @staticmethod
    def _download_packument(registry: str, package_name: str, dest: Path) -> None:
        url = f"{registry}/{quote(package_name, safe='@')}"
        request = Request(url, headers={"Accept": "application/json"})
        for attempt in range(3):
            try:
                with urlopen(request, timeout=60) as response:
                    body = response.read()
                    etag = response.headers.get("ETag")
                    last_modified = response.headers.get("Last-Modified")
                packument = json.loads(body)
                if (
                    not isinstance(packument, dict)
                    or packument.get("name") != package_name
                    or not isinstance(packument.get("versions"), dict)
                ):
                    raise GorgetTransientError(
                        f"Invalid registry metadata for {package_name} from {url}"
                    )
                headers: dict[str, str] = {}
                if etag:
                    headers["etag"] = etag
                if last_modified:
                    modified = parsedate_to_datetime(last_modified)
                    headers["modified"] = (
                        modified.astimezone(UTC).isoformat().removesuffix("+00:00") + "Z"
                    )
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(json.dumps(headers).encode() + b"\n" + body + b"\n")
                return
            except (
                URLError,
                TimeoutError,
                json.JSONDecodeError,
                OSError,
                ValueError,
            ) as exc:
                if attempt == 2:
                    raise GorgetTransientError(
                        f"Could not download registry metadata for {package_name}: {exc}"
                    ) from exc
                time.sleep(2**attempt)


def _node_modules_dirs(module_dir: Path) -> list[Path]:
    found: list[Path] = []
    for root, dirs, _files in walk(module_dir):
        if "node_modules" in dirs:
            path = Path(root) / "node_modules"
            found.append(path)
            dirs.remove("node_modules")
    return found


def _remove_project_links(store_dir: Path) -> None:
    for projects_dir in store_dir.glob("v*/projects"):
        shutil.rmtree(projects_dir, ignore_errors=True)


def _normalize_store(store_dir: Path) -> None:
    """Remove checkout-specific metadata and timestamps from pnpm's store."""
    _remove_project_links(store_dir)

    for database in store_dir.glob("v*/index.db"):
        with sqlite3.connect(database) as connection:
            rows = connection.execute("SELECT key, data FROM package_index ORDER BY key").fetchall()
            for key, data in rows:
                normalized = bytearray(data)
                start = 0
                # pnpm encodes each file's `checkedAt` value as a MessagePack
                # float64. These are the only float64 values in the package
                # index and contain the fetch wall-clock time.
                while (index := data.find(b"\xcb", start)) >= 0:
                    value_start = index + 1
                    normalized[value_start : value_start + 8] = b"\0" * 8
                    start = value_start + 8
                normalized_data = bytes(normalized)
                if normalized_data != data:
                    connection.execute(
                        "UPDATE package_index SET data = ? WHERE key = ?",
                        (normalized_data, key),
                    )
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("ANALYZE")
            connection.execute("VACUUM")
        database.with_name(f"{database.name}-wal").unlink(missing_ok=True)
        database.with_name(f"{database.name}-shm").unlink(missing_ok=True)


@contextmanager
def _preserve_node_modules(module_dir: Path) -> Iterator[Callable[[], None]]:
    """Remove pnpm installs while restoring any directories supplied upstream."""
    with tempfile.TemporaryDirectory(prefix="gorget-pnpm-modules-") as backup_root_name:
        backup_root = Path(backup_root_name)
        originals = _node_modules_dirs(module_dir)
        for index, original in enumerate(originals):
            shutil.copytree(original, backup_root / str(index), symlinks=True)

        def clean() -> None:
            for path in _node_modules_dirs(module_dir):
                shutil.rmtree(path)
            for index, original in enumerate(originals):
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(backup_root / str(index), original, symlinks=True)

        try:
            yield clean
        finally:
            clean()
