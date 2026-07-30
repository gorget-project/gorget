# How-to: add source verification for a new upstream

You're setting up (or hardening) a pipeline for a package and want to make
sure a fetched tarball is actually what upstream published, not something
tampered with in transit or silently swapped out. Two independent checks
cover this: `verify: gpg-signature`/`checksum-file` (opt-in, declared in the
pipeline YAML) and re-publication detection (always on, no YAML needed). See
[`verify-demo`](../../examples/verify-demo/) for a fully runnable version of
everything below, built on GNU Hello's real upstream signing key.

## 1. Check if upstream signs releases

If upstream publishes a detached GPG signature (`.sig`/`.asc`) alongside
their tarball, use `gpg-signature` -- it's the stronger check, since it
proves authorship, not just "the file wasn't corrupted."

Fetch both, then verify:

```yaml
fetch:
  - type: spec-source
    index: 0
  - type: url
    url: "https://example.com/example-${VERSION}.tar.gz.sig"
    filename: "example-${VERSION}.tar.gz.sig"

verify:
  - type: gpg-signature
    target: "example-${VERSION}.tar.gz"
    signature: "example-${VERSION}.tar.gz.sig"
    keyring: "example-project.asc"
```

`keyring` is a filename inside `--gpg-keys-dir` -- one armored public key
file per trusted upstream, checked in once. Get the maintainer's real public
key from a public keyserver (not upstream's own website, if avoidable --
you want a second source):

```bash
curl -s "https://keyserver.ubuntu.com/pks/lookup?op=get&options=mr&search=0x<FINGERPRINT>" \
  -o gpg-keys/example-project.asc
```

`gpg-signature` imports this into a fresh, throwaway GPG homedir per check --
nothing touches a shared keyring, and a wrong/missing key fails closed
(`GorgetPolicyViolation`, exit `2`), while a malformed keyring file itself is
a config problem (`GorgetTransientError`, exit `1`).

## 2. No signature? Use a checksums-listing file if upstream publishes one

Many projects publish a `SHASUMS256.txt`-style file instead of (or alongside)
signatures:

```yaml
fetch:
  - type: spec-source
    index: 0
  - type: url
    url: "https://example.com/SHASUMS256.txt"

verify:
  - type: checksum-file
    target: "example-${VERSION}.tar.gz"
    checksums-file: "SHASUMS256.txt"
    algorithm: sha256   # sha256 (default) | sha512 | sha1 | md5
```

This only proves the tarball matches what's in the listing file -- it
doesn't prove the listing file itself is authentic unless *it's* also
signature-verified. Prefer `gpg-signature` when both are available.

## 3. Neither available? You still get re-publication detection for free

If the package directory has a `sources` file (the dist-git-style manifest
recording already-fetched artifacts' checksums), gorget automatically
compares every freshly-fetched artifact against its recorded checksum --
**no `verify:` step needed to opt in**. This catches upstream silently
replacing a same-named file with different content between runs, which
neither `gpg-signature` nor `checksum-file` would catch on their own (they
verify against upstream's *current* claim, not against history).

A legitimate re-publication (upstream genuinely re-cut a release under the
same filename) is cured with an `accepted-checksums:` entry -- see the
README's [`accepted-checksums:`](../../README.md#accepted-checksums)
section; `verify-demo` walks through triggering and curing this exact case.

## 4. Test it

```bash
gorget --version <current-version> \
  --package-dir /path/to/your/package \
  --pipeline-file /path/to/your/package/pipeline.yaml \
  --gpg-keys-dir /path/to/your/package/gpg-keys \
  --output-dir /tmp/gorget-output \
  --dry-run
```

Check `report.json`'s `verify` stage `details` for a `"status": "passed"`
entry per check. A real failure here is exit `2` (policy violation); a setup
mistake (e.g. wrong `target`/`signature` filename, malformed keyring) is
exit `1` -- see the README's [Exit codes](../../README.md#exit-codes) table.
