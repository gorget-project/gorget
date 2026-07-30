# How-to: add a `post:` step to refresh generated metadata

Some packages need something in their spec file kept in sync with what was
actually fetched/vendored -- the canonical case is a generated `Provides:`
block listing bundled dependency versions, regenerated on every version
bump. `post:` is the stage for this: it runs last, after Fetch/Transform/
Verify/Policy have all validated the real inputs, and it's the one stage
that's allowed to write into `--package-dir` -- because the whole point is to
land a change in the tracked spec file.

## 1. Decide what needs regenerating, and mark it with BEGIN/END markers

A common, simple pattern: wrap the generated block in the spec file with
comment markers a script can find and replace between, leaving everything
else in the file untouched:

```spec
# BEGIN generated bundled Provides
# END generated bundled Provides
```

## 2. Write the script

The script's job is just: figure out the right content, and rewrite
everything between the markers. It runs with `--package-dir` as its working
directory, so it can read/write the spec file directly:

```bash
#!/bin/sh
# refresh-bundled-provides.sh <version>
set -eu
version="$1"
spec="example.spec"

awk -v version="$version" '
  /# BEGIN generated bundled Provides/ { print; print "Provides: bundled(example-lib) = " version; skip=1; next }
  /# END generated bundled Provides/   { skip=0 }
  !skip
' "$spec" > "$spec.tmp"
mv "$spec.tmp" "$spec"
```

Real scripts typically derive the version from something more specific --
e.g. a vendored dependency's own manifest -- rather than reusing the
package's own `${VERSION}` as this toy example does; the marker-replacement
mechanics stay the same either way.

## 3. Declare the `post:` step

```yaml
post:
  - type: run
    command: ["./refresh-bundled-provides.sh", "${VERSION}"]
```

Multiple steps run in declared order if you need more than one script.

## 4. Know the two things that make `post:` different from `transform: run:`

- **It writes to the real `--package-dir`**, not a scratch copy -- see the
  README's [`post:`](../../README.md#post) reference. Every other stage
  (including `transform: run:`) operates against a temporary working copy
  that's discarded when the pipeline finishes; `post:` is the one place a
  change actually lands where it'll get committed.
- **It's skipped entirely under `--dry-run`** -- on purpose, since dry-run's
  whole point is "touch nothing real." Don't rely on a dry run to validate a
  `post:` script's *output*; validate it by running the script directly
  first (see below), then confirm the pipeline picks it up with a real run.

## 5. Test it

Run the script directly first, against a scratch copy of the spec, before
wiring it into the pipeline at all -- this is the fastest way to iterate:

```bash
cp example.spec /tmp/example.spec.test
(cd /tmp && /path/to/refresh-bundled-provides.sh 1.2.3)
diff example.spec /tmp/example.spec.test
```

Once the script itself is right, run the full pipeline for real (not
`--dry-run`, since that skips `post:` entirely) and confirm the spec file in
`--package-dir` was updated as expected:

```bash
gorget --version 1.2.3 \
  --package-dir /path/to/your/package \
  --pipeline-file /path/to/your/package/pipeline.yaml \
  --output-dir /tmp/gorget-output

git -C /path/to/your/package diff example.spec
```
