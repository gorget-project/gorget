from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from collections.abc import Sequence
from datetime import UTC
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from gorget.config.schema import _DEFAULT_NPM_PLATFORMS, ToolchainEntry, VendorPlatform
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.fetch.vendor.lockfile import PACKAGE_NAME_RE as _PACKAGE_NAME_RE
from gorget.toolchain import wrap_command
from gorget.util.archive import pack_files
from gorget.util.subprocess_run import run

_PACKAGE_MANAGER_RE = re.compile(
    r"^pnpm@(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)(?:\+.*)?$"
)
_PNPM_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def _resolve_pnpm_version(
    manifest: dict[str, object], manifest_path: Path,
    module_dir: Path, toolchain: Sequence[ToolchainEntry],
) -> str:
    declared_manager = manifest.get("packageManager")
    if declared_manager is not None:
        match = _PACKAGE_MANAGER_RE.fullmatch(str(declared_manager))
        if not match:
            raise GorgetConfigError(
                f"Invalid pnpm packageManager declaration in {manifest_path}: "
                f"{declared_manager!r}"
            )
        return match.group("version")

    dev_engines = manifest.get("devEngines")
    dev_manager = dev_engines.get("packageManager") if isinstance(dev_engines, dict) else None
    dev_version = (
        dev_manager.get("version")
        if isinstance(dev_manager, dict) and dev_manager.get("name") == "pnpm"
        else None
    )
    if isinstance(dev_version, str) and _PNPM_VERSION_RE.fullmatch(dev_version):
        return dev_version

    result = run(wrap_command(["pnpm", "--version"], toolchain), cwd=module_dir)
    version = result.stdout.strip()
    if result.returncode != 0 or not _PNPM_VERSION_RE.fullmatch(version):
        raise GorgetConfigError(
            f"Could not determine pnpm version for {manifest_path}: "
            f"{(result.stdout + result.stderr).strip()}"
        )
    return version


class PnpmVendor:
    def vendor(
        self,
        module_dir: Path,
        toolchain: Sequence[ToolchainEntry] = (),
        package_dir: Path | None = None,
        use_workspace: bool = True,
        platforms: Sequence[VendorPlatform] = (),
    ) -> Path:
        resolved = platforms or _DEFAULT_NPM_PLATFORMS
        store_dir = module_dir / ".pnpm-store"
        store_dir.mkdir(exist_ok=True)
        for platform in resolved:
            cmd = [
                "pnpm", "install",
                "--ignore-scripts", "--frozen-lockfile",
                "--store-dir", str(store_dir),
                "--cpu", platform.cpu,
                "--os", platform.os,
            ]
            result = run(
                wrap_command(cmd, toolchain), cwd=module_dir, env={"CI": "true"}
            )
            if result.returncode != 0:
                raise GorgetTransientError(
                    f"pnpm install failed for {platform.cpu}/{platform.os} "
                    f"in {module_dir}: {result.stderr.strip()}"
                )
            node_modules = module_dir / "node_modules"
            if node_modules.exists():
                shutil.rmtree(node_modules)
        return store_dir

    def archive_root_files(self, module_dir: Path) -> list[Path]:
        return []

    def offline_cache(
        self,
        module_dir: Path,
        archive_path: Path,
        toolchain: Sequence[ToolchainEntry] = (),
        platforms: Sequence[VendorPlatform] = (),
        metadata_packages: Sequence[str] = (),
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
        major, minor = (int(part) for part in pnpm_version.split(".", 2)[:2])

        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="_pnpm_offline_cache_", dir=archive_path.parent
        ) as tmp:
            root = Path(tmp)
            scratch_module = root / "module"
            shutil.copytree(
                module_dir,
                scratch_module,
                ignore=shutil.ignore_patterns(
                    ".git", "node_modules", ".pnpm-store", ".pnpm-cache"
                ),
            )
            pnpm_root = root / ".pnpm"
            pnpm_root.mkdir()
            install_packages = [f"pnpm@{pnpm_version}"]
            if major >= 12:
                # npm filters pnpm's optional native executable to the host
                # architecture. Hummingbird builds both x64 and arm64 RPMs.
                install_packages += [
                    f"@pnpm/exe.linux-x64@{pnpm_version}",
                    f"@pnpm/exe.linux-arm64@{pnpm_version}",
                ]
            npm_result = run(
                wrap_command(
                    [
                        "npm", "install", "--prefix", str(pnpm_root),
                        "--ignore-scripts", "--force", *install_packages,
                    ],
                    toolchain,
                ),
                cwd=scratch_module,
                env={"CI": "true"},
            )
            if npm_result.returncode != 0:
                raise GorgetTransientError(
                    f"Could not install pnpm@{pnpm_version}: {npm_result.stderr.strip()}"
                )

            pnpm_mjs = pnpm_root / "node_modules/pnpm/bin/pnpm.mjs"
            pnpm_wrapper = pnpm_root / "node_modules/.bin/pnpm"
            if pnpm_mjs.is_file():
                # The pnpm package's install hook normally repairs this npm
                # shim. Install pnpm with scripts disabled, then create a
                # working shim for project scripts that invoke pnpm again.
                pnpm_wrapper.unlink(missing_ok=True)
                pnpm_wrapper.write_text(
                    "#!/bin/sh\n"
                    'exec node "$(dirname "$0")/../pnpm/bin/pnpm.mjs" "$@"\n'
                )
                pnpm_wrapper.chmod(0o755)
                pnpm_command = ["node", str(pnpm_mjs)]
            elif pnpm_wrapper.is_file():
                pnpm_command = [str(pnpm_wrapper)]
            else:
                raise GorgetConfigError(
                    f"pnpm entry point not found: {pnpm_mjs} or {pnpm_wrapper}"
                )

            version_result = run(wrap_command([*pnpm_command, "--version"], toolchain))
            active_version = version_result.stdout.strip().removeprefix("v")
            if version_result.returncode != 0 or active_version != pnpm_version:
                raise GorgetConfigError(
                    f"Bundled pnpm version does not match {pnpm_version}: "
                    f"{(version_result.stdout + version_result.stderr).strip()}"
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
            for platform in install_platforms:
                platform_args = (
                    ["--cpu", platform.cpu, "--os", platform.os, "--libc", platform.libc]
                    if platform is not None else []
                )
                install_result = run(
                    wrap_command(
                        [
                            *pnpm_command, "install", "--force", "--ignore-scripts",
                            "--frozen-lockfile", "--store-dir", str(store_dir),
                            *platform_args,
                        ],
                        toolchain,
                    ),
                    cwd=scratch_module,
                    env={"CI": "true", "XDG_CACHE_HOME": str(cache_dir)},
                )
                if install_result.returncode != 0:
                    target = f"{platform.cpu}/{platform.os}" if platform else "all platforms"
                    raise GorgetTransientError(
                        f"pnpm install failed for {target} "
                        f"in {module_dir}: {install_result.stderr.strip()}"
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
    def _registry_for(
        module_dir: Path, scope: str, toolchain: Sequence[ToolchainEntry]
    ) -> str:
        key = f"{scope}:registry" if scope else "registry"
        result = run(wrap_command(["npm", "config", "get", key], toolchain), cwd=module_dir)
        registry = result.stdout.strip()
        if scope and (
            result.returncode != 0 or not registry.startswith(("http://", "https://"))
        ):
            result = run(
                wrap_command(["npm", "config", "get", "registry"], toolchain),
                cwd=module_dir,
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
            if port is not None and (parsed.scheme, port) not in {
                ("http", 80), ("https", 443)
            }:
                registry_key += f"+{port}"
            path = parsed.path.strip("/")
            if path:
                parts = [
                    quote(part, safe="-._").replace("~", "%7E")
                    for part in path.split("/")
                ]
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
                        modified.astimezone(UTC).isoformat().removesuffix("+00:00")
                        + "Z"
                    )
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(
                    json.dumps(headers).encode()
                    + b"\n"
                    + body
                    + b"\n"
                )
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
