# Gorget

**Gorget** is a containerized source-pipeline tool for RPM package supply-chain
trust. It fetches upstream source tarballs directly from their origin (rather
than an intermediate lookaside cache), applies transforms, verifies integrity,
enforces dependency policy, and emits lookaside-ready artifacts.

Each package gets a declarative `<package>.source-pipeline.yaml` describing
exactly how its sources are produced. When no pipeline YAML exists, gorget
falls back to fetching every `Source` URL declared in the package's spec file.

This is an early-stage implementation covering the **Fetch** and **Transform**
stages and the core framework (config parsing, variable substitution, the
stage pipeline, and a minimal Emit). Verify and Policy are stubs pending
later work.

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

## Pipeline steps

### `fetch:`

| Step | Purpose |
|---|---|
| `spec-update` | Bump `Version:`/reset `Release:`/apply declared substitutions, before Source URLs resolve |
| `spec-source` | Download the spec's `Source0`/`SourceN` URLs (macro-resolved), by index or all |
| `url` | Download an explicit URL not declared in the spec |
| `git` | Clone a repo at a tag/branch/commit, archive the checkout (or a subdir) |
| `vendor` | Generate a Go/npm/Cargo/Composer vendor archive (multi-submodule aware) |

### `transform:`

Runs after `fetch:`, in declared order, against what was already fetched.

| Step | Purpose |
|---|---|
| `strip-tarball` | Remove paths (glob patterns) from a fetched tarball and repack it |
| `vendor-pin` | Bump a vendored dependency to a minimum version (Go/npm/Cargo) by editing its lockfile/manifest, before a later `vendor` step re-vendors |
| `vendor` | Same step as `fetch:`'s `vendor` (reused) -- lets `vendor-pin` run before vendoring, since `fetch:` always runs before `transform:` |
| `build-ui` | Run `npm`/`yarn run <script>` and archive the build output directory |
| `run` | Escape hatch: an arbitrary command, with declared output paths archived as new artifacts afterward |

`vendor-pin`/`vendor`/`build-ui`/`run` all operate against a shared working
source tree: a `git` fetch step's checkout if one ran, otherwise the sole
fetched artifact gets extracted on first use (an error if there's more than
one and no way to tell which to use).

### `toolchain:`

```yaml
toolchain:
  - name: go        # one of: go, node, npm, cargo, rustc, python
    version: 1.22.0
```

Declares per-package tool version requirements for `vendor`/`vendor-pin`/
`build-ui`/`run` steps. **This currently only validates -- it never fetches
or switches versions.** Before any stage runs (even under `--dry-run`),
gorget checks the declared version against whatever's already installed
(e.g. `go version`), matching component-wise (`1.22` matches an installed
`1.22.3`), and fails closed on a mismatch or a missing tool. There is no
mechanism to actually *activate* a non-default version yet.

An earlier design shelled out to [`mise`](https://mise.jdx.dev/) to activate
an already-installed version on demand, but that was rejected: mise's job is
downloading toolchain binaries directly from their own upstream release
channels at runtime, which reintroduces exactly the kind of untrusted-source
problem gorget exists to eliminate for source tarballs, just one layer up.
The real mechanism needs to be RPM-native with zero mid-pipeline network
dependency (e.g. distinctly-named versioned binaries, the same pattern
Fedora already uses for `python3.9`/`python3.11`/`python3.12`) -- see
HUM-4990/HUM-4789 for the ongoing discussion.

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
| `--debug` | Trace every stage/step transition and subprocess command run (argv, cwd, exit code, stdout/stderr) to stderr |

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
