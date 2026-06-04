# Security policy

`maivn-tools` runs in the same process as the host SDK and inherits the
host's trust boundary. The policies below define what the package
guarantees, what it does not, and what connector authors must do.

## Credential handling

- Secrets are never stored on dataclasses, in metadata, in connection
  metadata, in audit events, or in exception messages.
- `AuthStrategy.describe()` returns a JSON-safe view that omits all secret
  material. Connector authors must verify their custom strategies follow
  the same rule.
- `SecretResolver` implementations should fetch secrets lazily; resolving
  a value before it is needed widens the attack surface for no benefit.

## Logging

The bundled `HttpClient` does not log request bodies, response bodies, or
header values. Connectors must not log credentials, even at debug level.
If a connector needs to log request metadata for diagnostics, log only
the request method, URL host/path, correlation ID, and status code.

## Destructive actions

Every tool exposes two attributes the host can inspect before execution:

- `permissions` — a `PermissionSet` with the union of capability flags the
  tool may exercise.
- `destructive` — a boolean shortcut for tools whose effect cannot be
  trivially undone.

Hosts that gate execution should consult both. The `require_permissions`
helper checks the granted set against the tool's declared set and raises
`PermissionError` when the grant is insufficient.

### Default posture

- Read tools default to `PermissionSet(PermissionFlag.READ)`.
- Write tools opt in to `PermissionFlag.WRITE`.
- Delete / export / import / admin / impersonation tools opt in
  **explicitly** to those flags. They must also set `destructive=True`.

## Webhook signature verification

`WebhookVerifier` enforces:

- HMAC over the raw request body (not a stringified copy).
- Constant-time digest comparison via `hmac.compare_digest`.
- Optional timestamp tolerance to mitigate replay attacks. Connectors that
  carry a timestamp header should always configure `timestamp_header` and
  `tolerance_seconds`.

The default tolerance of 300 seconds matches the most common provider
defaults. Reduce it where the provider permits.

## Path safety

Filesystem connectors must sandbox to an explicit root and reject any
path that resolves outside it. `LocalFilesToolSet` is the reference
implementation. Symlink traversal is rejected by default; setting
`follow_symlinks=True` is only safe when the entire filesystem is
trusted.

## Dependency safety

Optional dependencies are loaded lazily inside the function that needs
them. A missing dependency must raise a clear `RuntimeError` that names
the pip extra required to install it (e.g. `"Install with: pip install
maivn-tools[pdf]"`).

## Reporting vulnerabilities

Email `security@maivn.io` with details. We will acknowledge within two
business days and aim to publish a fix within thirty days.

Do **not** open public issues for unpatched vulnerabilities.
