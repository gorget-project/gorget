# Example: minimal native package (git + Cargo vendor)

Every other example here starts from a package that already has a real
`Source0` tarball URL -- something to fetch, add a signature check to, or
fall back to entirely. A **native** package (no Fedora dist-git history) has
none of that: there's no upstream tarball URL to declare in the first place,
because nobody has ever cut one. `fetch: git` + `fetch: vendor` aren't one
option among several here -- they're the entire pipeline, and gorget's own
output is the only place the source/vendor archives ever exist.

This is that minimal case, stripped to just the two steps it actually needs
-- no `spec-source`, no `verify:`, no `transform:`. See
[`go-pipeline-demo`](../go-pipeline-demo/) once you need more than this; this
example is deliberately the floor, not the ceiling, and uses Cargo rather
than Go to cover the one vendor ecosystem none of the other examples touch.

Requires `git` and `cargo` on `PATH`, plus network access (a real `cargo
vendor` against crates.io).

## 1. Set up the demo repo (once)

```bash
./setup-demo-repo.sh
```

Creates `demo-repo/`: a tiny real Cargo project depending on `itoa`, tagged
`v1.0.0` -- standing in for a native package's actual upstream repo.

## 2. Run gorget

```bash
cd examples/native-cargo-demo
source ../../.venv/bin/activate  # skip if gorget is already installed/on PATH

gorget --version 1.0.0 \
  --package-dir . \
  --pipeline-file demo.source-pipeline.yaml \
  --output-dir /tmp/gorget-native-cargo-output \
  --debug
```

## 3. Inspect the result

```bash
ls /tmp/gorget-native-cargo-output

# fetch: git -- a real clone of the v1.0.0 tag, archived
tar tzf /tmp/gorget-native-cargo-output/demo-1.0.0.tar.gz

# fetch: vendor -- a real `cargo vendor` of itoa, archived
tar tJf /tmp/gorget-native-cargo-output/demo-1.0.0-vendor.tar.xz | head

cat /tmp/gorget-native-cargo-output/report.json
```

## 4. The two gotchas this example exists to show

**Default `archive_name` differs between `git` and `vendor`, and neither
default includes what you probably want.** `demo.source-pipeline.yaml`
comments this inline, but concretely:

| Step | Default `archive_name` | What this example sets instead |
|---|---|---|
| `fetch: git` | `${PACKAGE}-${VERSION}.tar.gz` | Same -- spelled out here just to show it's the default |
| `fetch: vendor` | `${PACKAGE}-vendor.tar.gz` (no version, always gzip) | `${PACKAGE}-${VERSION}-vendor.tar.xz` |

Nothing validates that your `archive_name` choices agree with what the spec
file's `Source0`/`SourceN` declare -- get it wrong and the mismatch doesn't
surface until `%prep` fails to find the file it expected, several steps away
from the pipeline YAML that actually caused it. There's also no repo-wide
convention enforced for the vendor archive's compression (`.tar.gz` vs
`.tar.bz2` vs `.tar.xz` are all valid, see `gorget/util/archive.py`) -- pick
one and be consistent within your own package.

**`%autosetup -n` must match the *archive's* internal directory, not the
upstream repo's.** `demo.spec`'s `%prep` uses `%{name}-%{version}`
(`demo-1.0.0`) because that's what `fetch: git`'s `archive_name` produces
(the archive's internal top-level directory is always its own filename minus
the compression suffix) -- it has nothing to do with `demo-repo/`'s own
directory name, or what casing/naming convention the upstream project
happens to use for its own release tags. Run `tar tzf
/tmp/gorget-native-cargo-output/demo-1.0.0.tar.gz | head -1` and compare
against `demo.spec`'s `%autosetup -n` line to see them agree.

Re-run `./setup-demo-repo.sh` to reset `demo-repo/` before trying again.

## Next steps

- Fetching from a real (non-local) upstream, especially a private one? See
  [Fetch from a private git repo](../../docs/how-to/fetch-from-a-private-repo.md).
- Need to bump a vendored dependency by hand, or enforce it doesn't regress?
  See [Hand-patch a vendored dependency, and stop it from regressing](../../docs/how-to/hand-patch-and-enforce-a-dependency-version.md).
- Want a signature/checksum check even though there's no traditional tarball
  URL? `verify:` still works against whatever `fetch: git` archives -- see
  [Add source verification for a new upstream](../../docs/how-to/verify-a-new-upstream.md).
