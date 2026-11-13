# Update Grafana dependencies with native steps

Declare each security target once. Yarn resolves its transitive dependencies;
Gorget derives required parent co-updates when a forced child major conflicts
with a parent's dependency requirement.

```yaml
transform:
  - type: vendor-bump
    ecosystem: yarn
    pins:
      - dependency: serialize-javascript
        version: "~7.1.4"
      - dependency: joi@^17
        version: "~17.13.9"
      - dependency: joi@^18
        version: "~18.3.1"
```

Range-qualified targets select matching resolved copies, including scoped names
such as `@scope/package@^2`. Gorget expands the lockfile descriptors, preserves
unrelated branches, and validates the result. An absent branch stays absent.

For a forced child-major update, Gorget queries the parent's latest same-major
release using `yarn npm info`, honoring Yarn's registry/authentication settings.
It checks that release accepts the child before adding the parent update;
otherwise it fails rather than crossing the parent's major version.

Go targets remain minimum versions: newer upstream requirements are preserved.
Use the existing Go/Yarn vendor steps to generate archives and synchronize source
metadata. A Yarn module named `.yarn/cache` gives its archive the RPM cache path.

Use the existing `bundled-provides` post step with `scope: production`. Its default
output, `bundled-npm-provides.inc`, is a tracked local Source in the RPM spec:

```spec
Source4: bundled-npm-provides.inc
%include %{SOURCE4}
```

Retire legacy dependency patches directly when migrating Source0. No recurring
spec-update step or custom frontend/Provides generator is needed.
