#!/usr/bin/env bash
# Creates demo-repo/: a tiny real git repo with an npm package.json pinned to
# an old (but real, published) dependency version -- the same shape as the
# real incident this example reproduces (gitlab.com/redhat/hummingbird/rpms!3036:
# a vendored `sanitize-html` CVE fix with no codified check behind it, flagged
# as likely to silently regress on the next automated update).
set -euo pipefail
cd "$(dirname "$0")"

rm -rf demo-repo
mkdir demo-repo
cd demo-repo

cat > package.json <<'EOF'
{
  "name": "demo",
  "version": "1.0.0",
  "dependencies": {
    "ms": "2.0.0"
  }
}
EOF

git init -q
git config user.email "demo@example.com"
git config user.name "Demo"
git add .
git commit -q -m "initial"
git tag v1.0.0
