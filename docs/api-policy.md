# Public API policy

`maivn-tools` follows semantic versioning. This page is the contract
between the package and its users about what is stable, what is not, and
how breaking changes are introduced.

## Versioning

Releases use **MAJOR.MINOR.PATCH** semantics:

- **MAJOR** — incompatible public-API changes.
- **MINOR** — new public surface and new connectors that do not break
  existing imports.
- **PATCH** — bug fixes and internal changes.

## Stable surface

Anything reachable from `maivn_tools.*` is part of the stable surface.
Specifically:

- `maivn_tools.core` — protocols, metadata, permissions, dry-run, registration.
- `maivn_tools.auth` — auth strategies, secret resolvers, OAuth flow layer.
- `maivn_tools.runtime` — HTTP client, retries, rate limits, pagination,
  errors.
- `maivn_tools.events` — audit events and webhook helpers.
- `maivn_tools.files` — MIME, attachments, extractors, transfers.
- `maivn_tools.testing` — mock transport and helpers.
- `maivn_tools.connectors.*` — every shipped connector and its tools.

Stable means:

- Module paths do not move between minor releases.
- Constructor argument names and types follow semver.
- Tool function names and keyword arguments follow semver.
- Public dataclass fields can be added but not removed or renamed without a
  major bump.
- Exceptions raised by public functions stay within the documented
  hierarchy.

## Internal surface

Anything matching the following patterns is internal and may change at any
time:

- Identifiers prefixed with `_` (e.g. `_SharedCursor`).
- Anything under `maivn_tools._internal` (currently unused, reserved).
- Module-level constants prefixed with `_`.

## Deprecation policy

When a public symbol is replaced:

1. The new symbol ships alongside the old in a minor release.
2. The old symbol emits a `DeprecationWarning` from the same release.
3. The old symbol is removed no sooner than the next major release.

Deprecations are recorded in `CHANGELOG.md` under the affected version.

## Optional dependencies

Connectors that need third-party drivers (e.g. `psycopg`, `pypdf`,
`python-docx`) declare them through pip extras:

```bash
pip install maivn-tools[postgres,pdf,docx]
```

A new extra is added in a minor release. Removing an extra requires a
major bump.

## Python support

The package supports the three most recent CPython minor versions. The
classifier list in `pyproject.toml` is authoritative.

## Connector additions and removals

- Adding a new connector is always a minor change.
- Removing a connector is a major change. Connectors that are being
  superseded are deprecated for at least one major version before removal.

## Reporting incompatibilities

If a release breaks an import that this policy promises is stable, file
an issue at https://github.com/mAIvn-developer/maivn-tools/issues. The
fix is to restore the symbol in a patch release and re-deprecate it if
necessary.
