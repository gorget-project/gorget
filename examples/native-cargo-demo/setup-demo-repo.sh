#!/usr/bin/env bash
# Creates demo-repo/: a tiny real Cargo project, tagged v1.0.0, standing in
# for a native package's upstream git history -- unlike every other example
# here, there is no tarball URL anywhere to fall back to or fetch a signature
# for. This demo's pipeline (see demo.source-pipeline.yaml) needs nothing
# beyond `fetch: git` + `fetch: vendor`, though a real native package can
# still add transform:/verify:/policy:/post: on top like any other.
set -euo pipefail
cd "$(dirname "$0")"

rm -rf demo-repo
mkdir demo-repo
cd demo-repo

cat > Cargo.toml <<'EOF'
[package]
name = "demo"
version = "1.0.0"
edition = "2021"

[dependencies]
itoa = "1.0"
EOF

mkdir -p src
cat > src/main.rs <<'EOF'
fn main() {
    let mut buf = itoa::Buffer::new();
    println!("{}", buf.format(42));
}
EOF

git init -q -b main
git config user.email "demo@example.com"
git config user.name "Demo"
git add .
git commit -q -m "initial"
git tag v1.0.0

echo "Demo repo created at $(pwd), tagged v1.0.0"
