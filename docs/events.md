# Events and audit

When an Agent uses a tool to write to Salesforce or delete a file, you want a
record of it — who did what, to which object, and whether it succeeded. And
when a provider calls *back* into your system over a webhook, you need to
prove the request is genuine before acting on it. `maivn-tools` ships two
event surfaces for exactly these two directions:

- **Audit events** describe operations connector tools perform (outbound).
- **Webhook helpers** verify inbound deliveries from providers (inbound).

Both are lightweight and optional: you choose where audit events go by
plugging in a sink, and verification is a single call. Neither surface ever
logs secrets.

## Audit events

```python
from maivn_tools import (
    AuditEvent,
    AuditEventKind,
    AuditEventSeverity,
    InMemoryAuditSink,
)

sink = InMemoryAuditSink()
sink.emit(
    AuditEvent(
        kind=AuditEventKind.WRITE,
        provider="example",
        tool="create_post",
        target="post:123",
        severity=AuditEventSeverity.NOTICE,
        detail={"size": 4096},
    )
)
for event in sink.events:
    print(event.to_dict())
```

### Recommended fields

| Field | Notes |
| --- | --- |
| `kind` | One of the normalized `AuditEventKind` values. Map provider events onto these so dashboards stay consistent. |
| `provider` | Must match `ProviderMetadata.name`. |
| `tool` | Tool name as registered on the Agent. |
| `connection_id` | Useful when a host manages many connections. |
| `actor` | Principal that initiated the call (user id, agent id). |
| `target` | URL, ID, or path of the affected object. |
| `detail` | Free-form, JSON-serializable map. **Never** include secrets. |

### Custom sinks

`AuditSink` has a single `emit` method. Implementations should be exception-
safe; failure to log audit events must not crash the connector.

```python
from maivn_tools import AuditEvent, AuditSink


class OtelAuditSink(AuditSink):
    def __init__(self, tracer):
        self._tracer = tracer

    def emit(self, event: AuditEvent) -> None:
        try:
            self._tracer.add_event(event.to_dict())
        except Exception:
            pass
```

## Webhook signature verification

`WebhookVerifier` covers the HMAC patterns most providers use.

```python
from maivn_tools import SignatureAlgorithm, WebhookVerifier

verifier = WebhookVerifier(
    secret="shared-secret",
    signature_header="X-Hub-Signature-256",
    algorithm=SignatureAlgorithm.HMAC_SHA256,
    encoding="hex",
    timestamp_header="X-Hub-Timestamp",
    tolerance_seconds=300,
)
verifier.verify(request_headers, request_body)
```

A `SignatureMismatchError` is raised when the signature is missing,
malformed, or wrong, or when the optional timestamp falls outside the
configured tolerance window.

For one-off verification without building a verifier, call
`verify_hmac_signature(secret, payload, signature, algorithm=..., encoding=...)`
directly.

### Supported algorithms

`SignatureAlgorithm.HMAC_SHA1`, `SignatureAlgorithm.HMAC_SHA256`, and
`SignatureAlgorithm.HMAC_SHA512`.

### Supported encodings

`"hex"` (default) and `"base64"`. Provider documentation typically states
which one to expect.

For higher-level normalization into a `NormalizedWebhookEvent`, see the
[`WebhookListener` adapter](generic-adapters.md#webhooklistener).
