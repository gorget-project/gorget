# How-to: fetch a source whose URL you don't know until runtime

Sometimes a package needs an additional source whose exact URL depends on
something you can only discover by looking inside a source you've already
fetched -- e.g. a bundled library's version, read from a file inside the main
tarball, which then determines which release of that library to download.
gorget's `fetch:` list can't express this directly: every URL there must be
resolvable from `${VERSION}`-style substitution variables before anything
runs. `transform: run:`'s `target:` and `discovered-outputs:` fields are the
way around that.

## The problem, concretely

Say your package's main tarball bundles a copy of some library, and your spec
needs a second source -- that library's own data package -- fetched from a
URL that includes the bundled library's version:

```
https://example.com/releases/download/release-${LIBRARY_VERSION}/extra-data.zip
```

`${LIBRARY_VERSION}` isn't `${VERSION}` (your package's own version) -- it's
whatever version of the library happens to be bundled in *this* release,
discoverable only by extracting the main tarball and reading a file inside
it. There's no gorget substitution variable for that, and there can't be:
it doesn't exist until the tarball is fetched.

## 1. Fetch the artifact you'll need to inspect

```yaml
fetch:
  - type: url
    url: "https://example.com/dist/example-${VERSION}.tar.gz"
  - type: url
    url: "https://example.com/dist/SHASUMS256.txt"
```

Two artifacts are now fetched. This matters for the next step: with more than
one fetched artifact, `transform: run:` no longer has an unambiguous "the
sole artifact" to extract on its own.

## 2. Select it explicitly with `target:`

```yaml
transform:
  - type: run
    target: "example-${VERSION}.tar.gz"
    command: ["./discover-and-fetch-extra-data.sh"]
    discovered-outputs: "discovered.tsv"
```

`target:` names the fetched artifact (by `output_name`) to extract as this
step's working directory -- required here since there are two fetched
artifacts and gorget has no way to guess which one the script needs. Without
it, the step would fail immediately with a "no 'git' fetch step ran and
there isn't exactly one fetched artifact" error.

## 3. Write the discovery script

The script's job: find the version, fetch the URL it implies, and tell
gorget what it produced by writing a manifest -- one `<output_name>\t<path>`
pair per line, path relative to the script's own cwd:

```bash
#!/bin/sh
set -eu
library_version="$(grep -oP 'version"\s*:\s*"\K[0-9.]+' path/to/version-file.json)"
url="https://example.com/releases/download/release-${library_version}/extra-data.zip"

curl -fsSL -o extra-data.zip "$url"

printf 'extra-data-%s.zip\textra-data.zip\n' "$library_version" > discovered.tsv
```

The manifest's declared `output_name` (`extra-data-<version>.zip`, matching
whatever your spec's `Source:` line expects) becomes the final artifact's
name -- gorget doesn't rename or derive it, the script is the one source of
truth for what it discovered.

## 4. Know the difference from `outputs:`

`outputs:` (the older, still-supported field) archives files/directories
whose name you already know when you write the YAML -- most `run:` steps
still just need this. Reach for `discovered-outputs:` specifically when the
final name can't be known until the command runs. Both can be declared on
the same step if you have some outputs of each kind.

`discovered-outputs:` only handles plain files, not directories -- if a
discovered output needs to be a directory, `tar` it yourself in the script
and list the resulting archive's path in the manifest instead.

## 5. Test it

```bash
gorget --version <current-version> \
  --package-dir /path/to/your/package \
  --pipeline-file /path/to/your/package/pipeline.yaml \
  --output-dir /tmp/gorget-output \
  --debug
```

Check `report.json`'s `artifacts` list (or the `--debug` trace) for the
discovered output_name(s) -- if the manifest is missing, malformed, or
references a file the script didn't actually produce, gorget fails closed
with a specific error naming the manifest line at fault, rather than
silently skipping it.
