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

## Public surface

The documented public surface includes the modules below. This excludes
private identifiers described in the next section. The current package is
experimental: the [Tools overview](index.md) warns that connector request
shapes and public methods can change between releases. Treat the compatibility
rules below as the intended policy, not a claim of live-provider validation.

- `maivn_tools.core` — protocols, metadata, permissions, dry-run, registration.
- `maivn_tools.auth` — auth strategies, secret resolvers, OAuth flow layer.
- `maivn_tools.runtime` — HTTP client, retries, rate limits, pagination,
  errors.
- `maivn_tools.events` — audit events and webhook helpers.
- `maivn_tools.files` — MIME, attachments, extractors, transfers.
- `maivn_tools.testing` — mock transport and helpers.
- `maivn_tools.connectors.*` — every shipped connector and its tools.

For surfaces released as stable, the compatibility policy is:

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

Postgres and PDF extraction have optional drivers (`psycopg` and `pypdf`).
Office and artifact rendering dependencies, including `python-docx`, are required
by the current package. Compatibility extras remain available:

```bash
pip install maivn-tools[postgres,pdf,docx]
```

A new extra is added in a minor release. Removing an extra requires a
major bump.

## Python support

The current package requires Python 3.12 or newer, as declared by
`requires-python` in `pyproject.toml`. That minimum is not evidence that every
newer interpreter has been tested.

## Connector additions and removals

- Adding a new connector is always a minor change.
- Removing a connector is a major change. Connectors that are being
  superseded are deprecated for at least one major version before removal.

## Reporting incompatibilities

If a release breaks an import that this policy promises is stable, file
an issue at https://github.com/mAIvn-developer/maivn-tools/issues. The
fix is to restore the symbol in a patch release and re-deprecate it if
necessary.
