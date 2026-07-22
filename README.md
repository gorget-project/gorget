# Gorget

Gorget is a containerized source-pipeline tool for RPM package supply-chain
trust. It fetches upstream source tarballs directly from their origin (rather
than an intermediate lookaside cache), applies transforms, verifies integrity,
enforces dependency policy, and emits lookaside-ready artifacts.

Each package gets a declarative `<package>.source-pipeline.yaml` describing
exactly how its sources are produced. When no pipeline YAML exists, gorget
falls back to fetching every `Source` URL declared in the package's spec file.

This is an early-stage implementation covering the **Fetch** stage and the
core framework (config parsing, variable substitution, the stage pipeline,
and a minimal Emit). Transform, Verify, and Policy are stubs pending later
work.

## Container interface

```
podman run --rm \
  -v ./<package-dir>:/package:ro \
  -v ./pipeline.yaml:/pipeline.yaml:ro \
  -v ./gpg-keys:/gpg-keys:ro \
  -v ./output:/output \
  gorget:latest \
  --version <new-version> \
  [--old-version <old-version>] \
  [--dry-run]
```

| Mount | Purpose |
|---|---|
| `/package` (ro) | Package directory: spec file, patches, sources manifest |
| `/pipeline.yaml` (ro) | The package's pipeline definition (optional) |
| `/gpg-keys` (ro) | Centralized GPG keyring (unused until the Verify stage) |
| `/output` (rw) | Fetched tarballs, `sources` manifest, `report.json` |

## CLI flags

| Flag | Description |
|---|---|
| `--version` | New upstream version to fetch (required) |
| `--old-version` | Previous upstream version |
| `--dry-run` | Run through the Policy stage but skip Emit; prints the report to stdout instead |
| `--package-dir` | Override the `/package` mount, for local development |
| `--pipeline-file` | Override the `/pipeline.yaml` mount |
| `--gpg-keys-dir` | Override the `/gpg-keys` mount |
| `--output-dir` | Override the `/output` mount |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Transient error (download failure, missing tool, invalid config) |
| 2 | Policy violation |

## Variable substitution

`${VERSION}`, `${VERSION_MAJOR}`, `${VERSION_MINOR}`, `${VERSION_PATCH}`,
`${OLD_VERSION}`, `${PACKAGE}`, `${SPEC_FILE}` are available in any string
value in the pipeline YAML.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

gorget --version 1.2.3 \
  --package-dir ./rpms/curl \
  --pipeline-file ./metadata/curl.source-pipeline.yaml \
  --output-dir /tmp/output \
  --dry-run

pytest
ruff check src/ tests/
mypy src/gorget
```

Tests that shell out to a real `rpmspec` are marked `integration` and are
skipped automatically when `rpmspec` isn't on `PATH`.
