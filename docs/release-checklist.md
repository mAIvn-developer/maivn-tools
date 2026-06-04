# Release checklist

A release of `maivn-tools` cannot ship until every box below is checked.

## Package

- [ ] `pyproject.toml` version matches `src/maivn_tools/__version__.py`.
- [ ] `CHANGELOG.md` has an entry for the release with **Added**,
      **Changed**, **Deprecated**, **Removed**, **Fixed**, **Security**
      sections as applicable.
- [ ] `pyproject.toml` classifiers list every supported Python minor
      version and no others.
- [ ] Optional dependencies and extras are declared explicitly and the
      docs reference the correct install command.
- [ ] License files (`LICENSE`, `NOTICE`) ship in the sdist and wheel.

## Tests

- [ ] `uv run --frozen pytest` is green.
- [ ] `uv run --frozen ruff check src tests` is clean.
- [ ] `uv run --frozen pyright src/maivn_tools` is clean.
- [ ] Coverage on `src/maivn_tools/connectors/` has no untested public
      tool callable.
- [ ] Live-provider tests (see `docs/testing.md`) are either skipped by
      default or gated on environment variables.

## Documentation

- [ ] Every new connector has a docs page under `docs/connectors/`.
- [ ] `docs/index.md` lists each docs page.
- [ ] Provider docs follow `docs/templates/provider.md`.
- [ ] Public API additions are reflected in `docs/api-policy.md` if they
      introduce new stable surface.
- [ ] Security-relevant additions update `docs/security.md`.

## API stability

- [ ] No public symbol was renamed or removed without a deprecation in a
      prior minor release (per `docs/api-policy.md`).
- [ ] Optional dependencies that were removed appear in the changelog as
      breaking changes and bump the major version.
- [ ] Pinned minimum versions for required dependencies are still met by
      the tested matrix.

## Security

- [ ] No secret material appears in audit-event detail payloads, tool
      schemas, exception messages, or log statements.
- [ ] Destructive tools have `destructive=True` and an explicit
      `PermissionSet` covering the work they perform.
- [ ] Sandboxes (file connectors, SQL execution) reject path or query
      traversal in the unit tests.

## Compatibility

- [ ] Type hints resolve under `pyright` at the supported Python
      versions.
- [ ] The package imports without optional dependencies present.

## Tag and publish

- [ ] Git tag `vX.Y.Z` matches the version in `pyproject.toml`.
- [ ] Release notes mirror the changelog entry for the version.
- [ ] PyPI upload succeeds and `pip install maivn-tools==X.Y.Z` works in
      a clean virtualenv.
