# Architecture

Every connector — whether it talks to Slack or to your own internal API —
needs the same plumbing: a way to authenticate, an HTTP client that
retries and respects rate limits, an audit trail, and a way to test it
without hitting the network. `maivn-tools` factors all of that into one
shared kernel so each new connector is mostly a thin description of an
API, not a re-implementation of the same infrastructure. This page shows
how those pieces stack and where you would plug in your own.

`maivn-tools` is organized into small, single-purpose layers. Each layer can
be imported and tested in isolation. Provider-specific connectors compose
them rather than re-implementing infrastructure.

```
+--------------------------------------------------------+
|                Provider connectors (Tier 1+)           |
|  Gmail · Slack · GitHub · Postgres · ...               |
+--------------------------------------------------------+
|                 Generic adapters (Tier 1)              |
|  GenericHttpConnector · OpenAPIConnector ·             |
|  GraphQLConnector · WebhookListener · MCPBridge        |
+--------------------------------------------------------+
|                 Connector kernel (Tier 0)              |
|  core/ · auth/ · runtime/ · events/ · files/ ·         |
|  testing/                                              |
+--------------------------------------------------------+
|                       maivn SDK                        |
|  Agent · Swarm · MCPServer · events · hooks            |
+--------------------------------------------------------+
```

## Layers

### `core`

Stable data models and protocols every connector relies on.

- `ProviderMetadata` — provider identity, supported auth modes, capability
  flags, and public scope catalog.
- `ConnectionMetadata` and `TokenMetadata` — public, secret-free
  descriptions of a configured connection.
- `PermissionSet` / `PermissionFlag` — least-privilege flags for each tool.
- `DryRunOutcome` / `DryRunPlan` — the dry-run contract for write tools.
- `Connector`, `ToolProvider`, and `register_*` helpers.

### `auth`

Auth strategies and secret resolvers. Strategies mutate request dictionaries
in place; resolvers translate `SecretRef` values into the underlying string
material.

Built-in strategies cover API keys (header or query), bearer tokens, HTTP
Basic, and OAuth2 bearer tokens fed from a caller-supplied
`OAuth2TokenProvider`. Built-in resolvers cover environment variables, a
static in-memory map, and a chained resolver that walks a list.

### `runtime`

The portable HTTP client. Includes:

- `HttpTransport` and the stdlib `UrllibTransport`.
- `HttpClient` with retries, rate limits, default headers, correlation IDs,
  idempotency keys, and stable error normalization.
- `RetryPolicy` (exponential backoff with full jitter).
- `TokenBucket` for cooperative rate limiting.
- Pagination helpers for cursor, offset, page-token, and delta-token
  patterns.
- A stable exception hierarchy mapped from HTTP status codes.

### `events`

Audit events and webhook helpers.

- `AuditEvent` and `AuditSink` model normalized audit trails.
- `WebhookVerifier` and `verify_hmac_signature` validate provider webhook
  signatures.

### `files`

Provider-agnostic file primitives.

- `Attachment` and `AttachmentSource` for normalized file references.
- MIME detection (`detect_mime_type`, `guess_mime_type`, `classify_kind`).
- `TextExtractor` plus a dependency-free UTF-8 extractor and a registry for
  optional extractors.
- `TransferProgress` and `TransferOutcome` for bulk transfers.

### `testing`

`MockTransport` plugs into `HttpClient` and records every request the
connector makes. Helpers `json_response` and `text_response` build canned
responses for assertions.

### `connectors`

Concrete connectors built on the kernel:

- `connectors.generic_api` — `GenericHttpConnector`, `OpenAPIConnector`,
  `GraphQLConnector`, `WebhookListener`.
- `connectors.mcp_bridge` — declarative wrappers that build
  `maivn.MCPServer` instances at registration time.
- `connectors.files` — sandboxed, read-only local-filesystem tools.

## Design principles

- **Public stability before breadth.** A new provider must reuse the kernel
  rather than fork it.
- **Secrets never leak.** Strategies, metadata, and audit events all surface
  redacted or hashed material only.
- **Read-only by default.** Destructive operations must declare themselves
  through permission flags and the `destructive` marker.
- **No required heavyweight dependencies.** The kernel uses only the
  standard library; extra dependencies live in optional extras or external
  packages.
- **Composable with the SDK.** Tools register through `Agent.add_tool` /
  `Swarm.add_tool` like any other callable; no custom runtime is required.
