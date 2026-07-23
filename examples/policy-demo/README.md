# Example: Policy stage (`vendor-constraints`)

Runnable, non-pytest example of gorget's Policy stage, reproducing the shape of
a real incident: [gitlab.com/redhat/hummingbird/rpms!3036](https://gitlab.com/redhat/hummingbird/rpms/-/merge_requests/3036)
hand-patched a vendored `sanitize-html` dependency to fix two CVEs, with
nothing codified to stop the fix from silently disappearing on the next
automated update. Robert Sturla flagged it directly: *"Next update, unless
upstream also makes this change, we will revert back to the old lockfiles and
the CVE will be falsely marked as fixed."*

`policy: vendor-constraints` is the fix: it re-confirms a vendored
dependency's version on **every** pipeline run, not just the run where a human
hand-edited a lockfile -- so a regression fails the build (exit code 2)
instead of shipping quietly. This example uses a small, real, stable npm
package (`ms`) instead of `sanitize-html` for speed, but the mechanism is
identical for any `go`/`npm`/`cargo` dependency.

Requires `git` and `npm` on `PATH`, plus network access (a real
`npm install` against the npm registry).

## 1. Set up the demo repo (once)

```bash
./setup-demo-repo.sh
```

Creates `demo-repo/`: a tiny real git repo with a `package.json` depending on
`ms@2.0.0`.

## 2. Run gorget -- constraint passes

```bash
cd examples/policy-demo
source ../../.venv/bin/activate

gorget --version 1.0.0 \
  --package-dir . \
  --pipeline-file demo.source-pipeline.yaml \
  --output-dir /tmp/gorget-policy-output
```

```bash
cat /tmp/gorget-policy-output/report.json
```

The `policy` stage's `details` show a real, passing check -- `ms`'s actual
vendored version (read from `node_modules/ms/package.json` after a real
`npm install`) meets the declared minimum:

```json
{
  "type": "vendor-constraints",
  "target": "ms",
  "status": "passed",
  "reason": null
}
```

## 3. Simulate the regression -- fails closed

The real incident: a dependency version requirement quietly reverting on a
later run. Simulate it by requiring a version higher than what's actually
vendored:

```bash
cp demo.source-pipeline.yaml /tmp/demo-regressed.yaml
sed -i 's/version: "2.0.0"/version: "3.0.0"/' /tmp/demo-regressed.yaml

gorget --version 1.0.0 \
  --package-dir . \
  --pipeline-file /tmp/demo-regressed.yaml \
  --output-dir /tmp/gorget-policy-output
echo "exit code: $?"
```

```
error: Policy violation (1 check(s)):
- [vendor-constraints] ms: ms is 2.0.0, need >= 3.0.0 (demo: pin confirmation)
exit code: 2
```

This is exactly the check that was missing in `!3036` -- run automatically,
every time, rather than relying on someone remembering to re-verify a
hand-patched lockfile survived the next update.

## 4. `audit:` and `license-compliance:`

`demo.source-pipeline.yaml` doesn't enable these, but both are real:

```yaml
policy:
  vendor-constraints: [...]
  audit: true                    # go mod verify (fails closed) / npm audit / cargo audit (warn-only)
  license-compliance:
    disallowed:
      - GPL-3.0-only
```

Add `audit: true` and re-run -- `npm audit`'s findings (if any) land in
`report.json` as `status: "warning"`, never as a build failure, since it
queries a live vulnerability database over the network (non-deterministic --
see the README's `policy:` section for why that's treated differently from
`vendor-constraints`).

Re-run `./setup-demo-repo.sh` to reset `demo-repo/` before trying again.
