# How-to: debug a failing pipeline locally

A gorget run failed -- in CI, or in a local test run -- and the one-line
`error: ...` on stderr isn't enough to tell you why. This walks through
getting more detail, in increasing order of effort.

## 1. Read the exit code first

```bash
gorget --version 1.2.3 --package-dir . --pipeline-file pipeline.yaml --output-dir /tmp/out
echo "exit code: $?"
```

| Exit code | Category | Typical cause |
|---|---|---|
| `0` | Success | -- |
| `1` | Config / transient (`GorgetConfigError`, `GorgetTransientError`) | Bad YAML, a missing referenced artifact, a download failure, a missing external tool, a subprocess that failed |
| `2` | Policy violation (`GorgetPolicyViolation`) | A `verify:`/`policy:` check actually ran and failed closed |

This alone usually tells you whether to look at your pipeline YAML (`1`) or
at the actual dependency/signature/version being checked (`2`). See the
README's [Exit codes](../../README.md#exit-codes) table.

## 2. Read `report.json` -- it's written even on failure

`report.json` records every stage that ran, in order, with its status
(`success`/`skipped`/`failed`) and a `reason` -- so you can see exactly which
stage got furthest before stopping, not just the single stderr line:

```bash
cat /tmp/out/report.json
```

```json
{
  "stages": [
    { "name": "fetch", "status": "success", "reason": null },
    { "name": "transform", "status": "skipped", "reason": "no transform steps declared" },
    { "name": "verify", "status": "failed", "reason": "No fetched artifact named 'example-1.2.3.tar.gz.sig'" }
  ]
}
```

Under `--dry-run`, `report.json` never touches disk (Emit is always skipped)
-- it's printed to stdout instead, failure or not. See
[`emit-on-failure-demo`](../../examples/emit-on-failure-demo/) for a
runnable version of both cases, including a toolchain-mismatch failure that
happens before any stage even starts.

## 3. Re-run with `--debug` for a full trace

```bash
gorget --version 1.2.3 --package-dir . --pipeline-file pipeline.yaml \
  --output-dir /tmp/out --debug
```

Every stage/step transition and subprocess command gets traced to stderr,
prefixed `[gorget debug]`:

```
[gorget debug] gorget.pipeline: stage fetch: starting
[gorget debug] gorget.fetch: fetch step: GitStep(repo='https://example.com/example.git', ...)
[gorget debug] gorget.util.subprocess_run: + git clone --depth 1 --branch v1.2.3 https://example.com/example.git .  (cwd=/tmp/gorget-XXXXXX)
[gorget debug] gorget.util.subprocess_run:   -> exit 0
[gorget debug] gorget.pipeline: stage fetch: success
[gorget debug] gorget.pipeline: stage transform: starting
...
```

This is the most useful level for anything involving an external command
(`git`, `go`, `npm`, `gpg`, a `transform: run:`/`post: run:` script) --
you'll see the exact argv, working directory, exit code, and captured
stdout/stderr for every subprocess gorget ran, in order, right up to the one
that failed.

## 4. Narrow it down by stage

- **`fetch` failed**: almost always a real network/URL/ref problem, or a
  spec macro (`${VERSION}`, `%{version}`) not resolving the way you expected
  -- `--debug` shows the exact resolved URL/command.
- **`transform`/`post` failed**: a `run:` step's script exited non-zero --
  `--debug` captures its stdout/stderr even though the top-level error
  message only includes stderr.
- **`verify` failed**: either a declared check (wrong `target`/`signature`/
  `checksums-file` filename is the most common mistake) or re-publication
  detection catching a checksum mismatch against the package's `sources`
  file -- see
  [Add source verification for a new upstream](verify-a-new-upstream.md).
- **`policy` failed**: a real constraint violation -- read the printed
  `reason`, it names the exact package and versions involved.
- **`toolchain` failed**: shows up as the sole `report.json` stage, named
  `toolchain` -- an installed tool version doesn't match a `toolchain:`
  entry's declared version, checked once up front before `fetch` even
  starts (even under `--dry-run`).

## 5. Reproduce narrowly

Once you know which stage/step, you don't need to re-run the whole pipeline
to iterate -- comment out later `fetch:`/`transform:` steps in a scratch copy
of the YAML, or run the failing `run:`/`post:` script's command by hand from
`--package-dir` to iterate on it directly without waiting on the stages
before it.
