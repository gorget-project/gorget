# Example: `report.json` is written even when a stage fails

Tiny, runnable example demonstrating one specific behavior: when a pipeline
stage fails partway through, `report.json` still gets written (or printed
under `--dry-run`), showing exactly which stages completed and why the
pipeline stopped -- rather than the failure being silent beyond a one-line
stderr message.

`demo.source-pipeline.yaml` is deliberately broken: its `verify:` step
references a signature file (`hello-2.12.1.tar.gz.sig`) that no `fetch:` step
ever produces. `fetch` succeeds for real (a real GNU Hello tarball), then
`verify` fails closed.

Requires network access to `ftp.gnu.org`.

## Run

```bash
cd examples/emit-on-failure-demo
source ../../.venv/bin/activate

gorget --version 2.12.1 \
  --package-dir . \
  --pipeline-file demo.source-pipeline.yaml \
  --output-dir /tmp/gorget-emit-failure-output
echo "exit code: $?"
```

```
error: No fetched artifact named 'hello-2.12.1.tar.gz.sig'
exit code: 1
```

## Inspect

```bash
ls /tmp/gorget-emit-failure-output
# report.json -- and nothing else. No tarball, no sources manifest: only
# report.json gets written on failure, never a partial-looking /output.

cat /tmp/gorget-emit-failure-output/report.json
```

```json
{
  "stages": [
    { "name": "fetch", "status": "success", "reason": null },
    { "name": "transform", "status": "skipped", "reason": "no transform steps declared" },
    { "name": "verify", "status": "failed", "reason": "No fetched artifact named 'hello-2.12.1.tar.gz.sig'" }
  ]
}
```

## Same thing under `--dry-run`

`verify:`/`policy:` both skip entirely under `--dry-run` (nothing was really
fetched to check), so `demo.source-pipeline.yaml` above can't actually fail
in that mode. `dry-run-failure.source-pipeline.yaml` demonstrates the
dry-run case instead, using a toolchain mismatch -- that check always runs,
before any stage does, dry-run or not:

```bash
gorget --version 2.12.1 \
  --package-dir . \
  --pipeline-file dry-run-failure.source-pipeline.yaml \
  --output-dir /tmp/gorget-emit-failure-output \
  --dry-run
echo "exit code: $?"

ls /tmp/gorget-emit-failure-output 2>&1   # <- does not exist; printed to stdout instead
```

Emit (and therefore `/output`) is always skipped under `--dry-run` -- on
failure, the report prints to stdout instead of being written to disk:

```json
{
  "stages": [
    { "name": "toolchain", "status": "failed", "reason": "Required toolchain go@999.999.999 does not match the installed version (...)" }
  ]
}
```
