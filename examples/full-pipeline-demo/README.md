# Example: the "uber" pipeline (every primitive, one pipeline)

Runnable, non-pytest example exercising every stage of gorget's pipeline
together, kept up to date as new primitives are added -- if you add a new
step type or check, add it here too. It's a superset of
`../go-pipeline-demo` (all six Transform step types) with a Verify check
and a Policy check layered on top.

| Stage | Step | What it does here |
|---|---|---|
| Fetch | `git` | Clones `demo-repo/`, a real Go module |
| Fetch | `url` (×2) | Downloads GNU Hello's real tarball + its real detached GPG signature |
| Transform | `strip-tarball` | Removes `docs/` from the Go source tarball |
| Transform | `vendor-bump` | Bumps `rsc.io/quote` from `v1.0.0` to `v1.5.2` |
| Transform | `vendor` | Vendors the now-bumped dependency |
| Transform | `build-ui` | Runs `npm run build` in `ui/`, archives `dist/` |
| Transform | `run` | Runs Go plus direct and `/usr/bin/env` Node version checks |
| Transform | `pack` | Packs `setup-demo-repo.sh` (already in `--package-dir`) into a deterministic archive |
| Verify | `gpg-signature` | Verifies GNU Hello's tarball against its real upstream maintainer key |
| Verify | *(implicit)* | Re-publication detection runs automatically since `sources` exists here |
| Policy | `vendor-constraints` | Confirms `vendor-bump`'s bump to `rsc.io/quote` actually took effect |

**Deliberately not included** (each already has its own focused, faster
example -- duplicating them here would just make this slower to run without
adding coverage): `spec-update`/`spec-source` fetch steps (see
`../spec-source-demo`), `checksum-file` verify (unit/dispatch-tested only,
no example yet), `audit:`/`license-compliance:` policy checks (see
`../policy-demo`).

Requires `git`, `go`, `gpg`, and parallel-installed `node-24`/`npm-24`, plus
network access (`proxy.golang.org`, `registry.npmjs.org`, `ftp.gnu.org`). The
Hummingbird GitLab CI image includes the Node.js 24 commands alongside its
default Node.js version.

## 1. Set up the demo repo (once)

```bash
./setup-demo-repo.sh
```

Creates `demo-repo/`: a tiny real Go module pinned to an old
`rsc.io/quote v1.0.0`, a `docs/` dir to be stripped, and a minimal `ui/` npm
project for `build-ui`.

## 2. Run gorget

```bash
cd examples/full-pipeline-demo   # relative paths in the pipeline YAML resolve from here
source ../../.venv/bin/activate  # skip if gorget is already installed/on PATH

gorget --version 1.0.0 \
  --package-dir . \
  --pipeline-file demo.source-pipeline.yaml \
  --gpg-keys-dir gpg-keys \
  --output-dir /tmp/gorget-full-output
```

## 3. Inspect the result

```bash
ls /tmp/gorget-full-output

# strip-tarball: docs/ is gone from the Go source tarball
tar tzf /tmp/gorget-full-output/demo-main.tar.gz | grep docs   # <- prints nothing

# vendor-bump + vendor: rsc.io/quote bumped and actually vendored
tar tzf /tmp/gorget-full-output/demo-vendor.tar.gz | grep quote

# build-ui: the built dist/ output, archived
tar tzf /tmp/gorget-full-output/demo-ui-assets.tar.gz

# run: the escape-hatch command's declared outputs, archived verbatim
cat /tmp/gorget-full-output/go-version.txt
cat /tmp/gorget-full-output/node-version.txt
cat /tmp/gorget-full-output/env-node-version.txt

# pack: setup-demo-repo.sh packed verbatim, at its own relative path
tar tzf /tmp/gorget-full-output/demo-packaging-scripts.tar.gz

# every stage's status, every check's result, every artifact's checksum
cat /tmp/gorget-full-output/report.json
```

`report.json`'s `verify` and `policy` stages both show real, passing checks:

```json
{ "type": "gpg-signature", "target": "hello-2.12.1.tar.gz", "status": "passed", "reason": null }
{ "type": "vendor-constraints", "target": "rsc.io/quote", "status": "passed", "reason": null }
```

Re-run `./setup-demo-repo.sh` to reset `demo-repo/` back to its original
state before trying again.

## 4. See it fail closed

Bump the Policy constraint above what's actually vendored, simulating the
`vendor-bump` regression this check exists to catch
(see `../policy-demo/README.md` for the real incident):

```bash
sed -i 's/version: "1.5.2"/version: "9.9.9"/' demo.source-pipeline.yaml

gorget --version 1.0.0 \
  --package-dir . \
  --pipeline-file demo.source-pipeline.yaml \
  --gpg-keys-dir gpg-keys \
  --output-dir /tmp/gorget-full-output
echo "exit code: $?"

git checkout demo.source-pipeline.yaml   # revert
```

Exit code 2, `error: Policy violation (1 check(s)): - [vendor-constraints]
rsc.io/quote: rsc.io/quote is v1.5.2, need >= 9.9.9 (...)`.

## 5. `toolchain:` -- activates an installed Node.js RPM

The pipeline declares Node.js 24 directly:

```yaml
toolchain:
  - name: node
    version: "24"
    minimum-version: "24.16"
```

`version` selects the Node.js 24 RPM stream, while `minimum-version` enforces
Jaeger's actual Node.js requirement. Gorget finds the trusted,
parallel-installed `node-24` RPM command and creates
temporary `node`, `npm`, and `npx` aliases for the complete pipeline. The
`build-ui` step therefore runs with Node.js 24. The `run` step records both a
direct `node --version` and `/usr/bin/env node --version`; both output files
show the same Node.js 24 release, demonstrating that child scripts inherit the
selection.

The host's default is unchanged. Running `node --version` before and after
Gorget still reports the system-default Node.js version. If `node-24` is not
installed, the pipeline fails closed before any stage runs:

```
error: Required toolchain node@24 does not match the active version (...).
No matching installed RPM toolchain could be activated; gorget never downloads
toolchains.
```

The versions are quoted because toolchain versions are strings. Gorget never
downloads a toolchain or changes system alternatives.
