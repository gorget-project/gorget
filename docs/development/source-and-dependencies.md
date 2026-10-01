# Source workspaces and dependencies

## Source ownership

`SourceWorkspace` owns the active source tree, its backing artifact, and its
publication state. `TransformContext.source_dir` is a read-only view of that
workspace. It does not store a second source path.

Use `SourceWorkspace.select` to materialize or switch a source archive. A source
switch rejects unpublished changes. Each selection uses a separate extraction
directory. Explicit `run` targets use detached trees and preserve the active
source selection.

Use `edit_metadata` for dependency updates. This transaction copies the complete
source tree, including sibling modules, into an isolated directory. It publishes
only declared metadata files after every update and validation succeeds. Failed
updates leave the original source tree unchanged. Identical metadata does not
mark the source dirty.

Vendor adapters declare their source metadata through `source_files`. The vendor
handler returns `SourceChange` values with the archive artifacts. The pipeline
applies these values through the workspace. It does not infer source changes from
an ecosystem name or a configuration flag. The workspace repacks Source0 only
when file content changes or a file is deleted.

## Dependency inventory

`read_inventory` returns resolved dependency copies with their versions,
locations, dependency references, and production scope. Lockfile formats remain
private to this module. Go and Maven use package-manager queries for the requested
dependency names. Vendored modules retain their toolchain and workspace scope for
later checks.

Dependency updates, version policy, and Node bundled Provides use this inventory.
Version checks inspect every matching copy. Reports identify the locations of
copies that violate a constraint. Prefix constraints also check newer copies
outside the permitted version series.

The inventory retains unreferenced lock entries for version policy and the `all`
Provides scope. Production Provides follow the existing dependency graph rules.
Classic Yarn treats all locked dependencies as production dependencies.

## Dependency updates

`update_dependencies` accepts the complete pin set for one module. Each ecosystem
adapter declares its metadata files and implements `apply_many`. Go and the Node
managers apply all requirements before one resolution command. Cargo and Maven
retain sequential commands where their existing update mechanisms require them.
The updater validates the complete pin set after resolution, including pins that
already met their constraints before the update.

`VendorBumpHandler` supplies the source transaction and module paths. It contains
no package-manager commands or lockfile parsing.

## Command execution

`PackageManager` owns toolchain wrapping, bundled Yarn selection, Go workspace
isolation, and external Yarn install state for lockfile updates. Callers declare
the command and its execution settings. They can inject a command runner for tests.
Offline settings support Go, Cargo, Node managers, and Maven. Ecosystem adapters
still choose their commands, platform flags, and vendor cache layout.

## Contract tests

Run `python -m pytest -q`, `ruff check src tests`, and `mypy src`.

The shared vendor contract tests exercise all eight adapters through the transform
stage with simulated package-manager output. They check source publication,
unchanged input bytes, cache separation, and repeated archive checksums. Workspace
tests check failed updates, file deletions, and sibling dependencies. Inventory
tests check duplicate copies, workspace scope, and agreement with policy and
bundled Provides. Existing integration tests use real tools when available.
