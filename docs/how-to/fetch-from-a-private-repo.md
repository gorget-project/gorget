# How-to: fetch from a private git repo

Your pipeline's `fetch: git` step's `repo:` points at a private repo, and
`gorget` fails with something like:

```
error: git clone --branch v1.2.3 failed for https://example.com/private/repo.git:
fatal: could not read Username for 'https://example.com': terminal prompts disabled
```

This isn't a gorget bug or a config mistake in your pipeline YAML -- gorget's
`git` step deliberately doesn't manage credentials itself (see the README's
[`fetch:` section](../../README.md#fetch)). It shells out to a plain `git
clone`/`git checkout` and inherits whatever ambient git configuration the
*process invoking gorget* already has, the same as if you'd run those
commands yourself. There's no `--git-token`/`--ssh-key` flag and no
credential field anywhere in the pipeline schema. Fix the environment gorget
runs in, not the YAML.

## 1. Local/manual runs: use whatever you already authenticate with

If `git clone <repo>` already works for you outside of gorget -- an SSH key
loaded in your agent, a GitHub/GitLab CLI credential helper, a `.netrc`
entry -- gorget's subprocess clone inherits it automatically, no extra setup
needed. Confirm with the exact command gorget would run:

```bash
git clone --depth 1 --branch v1.2.3 <repo> /tmp/probe-clone
```

If that works, gorget's `git` step will too. If it doesn't, fix *that*
first -- there's nothing gorget-specific left to debug once plain `git
clone` succeeds.

## 2. CI/scheduled runs: no ambient credential helper exists

A CI job typically has no interactive credential helper and no persistent
SSH agent, so gorget's `git clone` fails closed even for a repo you're
otherwise fully authorized to read. The fix is to inject credentials into
the environment gorget's subprocess sees, scoped as narrowly as you can
manage -- for example, an HTTPS token rewrite via `url.<rewritten>.insteadOf`,
passed through env rather than a mutated global `~/.gitconfig` so it doesn't
leak into unrelated commands in the same job:

```bash
export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0="url.https://oauth2:${TOKEN}@example.com/.insteadOf"
export GIT_CONFIG_VALUE_0="https://example.com/"

gorget --version 1.2.3 \
  --package-dir . \
  --pipeline-file pipeline.yaml \
  --output-dir /tmp/output
```

`git`'s own `GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_n`/`GIT_CONFIG_VALUE_n`
environment variables (git >= 2.31) apply config for just that process tree,
not the whole machine -- a public `repo:` under a different host is
unaffected and still clones anonymously. Build the token/env var mapping
your own automation needs (which host, which env var holds the token) around
this same shape; gorget has no opinion on where the token comes from.

## 3. SSH instead of HTTPS

Point `repo:` at an SSH URL (`git@example.com:org/repo.git`) and make sure
an SSH agent with the right key is running and forwarded into wherever
gorget executes -- gorget's clone uses plain `git`, so agent forwarding that
already works for a manual `git clone` over SSH works here unchanged.

## 4. Confirm it worked

```bash
gorget --version 1.2.3 \
  --package-dir . \
  --pipeline-file pipeline.yaml \
  --output-dir /tmp/output \
  --debug
```

`--debug` prints the exact `git clone`/`git checkout` argv gorget ran (see
[Debug a failing pipeline locally](debug-a-failing-pipeline.md)) -- useful
for confirming which URL it actually tried, especially once an
`insteadOf` rewrite is involved and the URL on the wire no longer matches
what's written in the pipeline YAML.
