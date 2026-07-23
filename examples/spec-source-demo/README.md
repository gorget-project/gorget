# Example: spec-driven fetch (`spec-update` + `spec-source` + `url`)

Runnable, non-pytest example of gorget's spec-driven Fetch steps -- the
alternative to the git-based flow in `../go-pipeline-demo`. Fetches GNU
Hello (the traditional "hello world" example used in virtually every RPM
packaging tutorial) directly from `ftp.gnu.org`, using the spec's own
`Source0` URL with real RPM macro resolution.

| Step | What it does here |
|---|---|
| `spec-update` | Resets `Release:` to `1` on a writable copy of the spec, before Source URLs resolve |
| `spec-source` | Downloads `Source0:`, with `%{version}` macro-resolved by `rpmspec` |
| `url` | Downloads an explicit URL not declared anywhere in the spec (the tarball's GPG signature) |

Requires `rpmspec` on `PATH` (part of `rpm-build`) and network access to
`ftp.gnu.org`.

## Run

```bash
cd examples/spec-source-demo
source ../../.venv/bin/activate  # skip if gorget is already installed/on PATH

gorget --version 2.12.1 \
  --package-dir . \
  --pipeline-file hello.source-pipeline.yaml \
  --output-dir /tmp/gorget-hello-output
```

## Inspect

```bash
ls /tmp/gorget-hello-output
cat /tmp/gorget-hello-output/report.json
```

## Try a different version

Change `--version` to another published GNU Hello release and re-run --
`spec-source` re-resolves `Source0`'s `%{version}` macro against whatever
`--version` you pass (`spec-update` writes it into the spec first), so it
fetches a completely different tarball with no YAML changes:

```bash
curl -s https://ftp.gnu.org/gnu/hello/ | grep -oE 'hello-[0-9.]+\.tar\.gz"'

gorget --version 2.12.3 \
  --package-dir . \
  --pipeline-file hello.source-pipeline.yaml \
  --output-dir /tmp/gorget-hello-output-2.12.3
```
