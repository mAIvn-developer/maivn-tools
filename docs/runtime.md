# HTTP runtime

Every connector in `maivn-tools` eventually talks to a provider over HTTP,
and every provider fails differently: some throttle you, some return cryptic
5xx errors, some want a `Retry-After` honored to the millisecond. The runtime
layer exists so connector authors never re-solve those problems. Write the
endpoints; the runtime handles the rest.

It is the connector-facing HTTP stack, split into two pieces: a low-level
**transport** that simply sends one request and returns one response, and a
higher-level **client** that composes retries, rate limits, auth, default
headers, correlation IDs, and stable error normalization on top of any
transport. Because the two are decoupled, the same connector code runs
unchanged against a real network and against a canned test transport.

## Transports

`HttpTransport` is an abstract base class with a single method:

```python
class HttpTransport(ABC):
    def send(self, request: HttpRequest) -> HttpResponse: ...
```

Two implementations ship out of the box:

- `UrllibTransport` — the default; uses `urllib.request` so the package has
  no required third-party dependency.
- `MockTransport` — in `maivn_tools.testing`; queues canned responses and
  records every request.

Custom transports (e.g. `httpx`, `requests`, async) implement the same
interface and plug directly into `HttpClient`.

## HttpClient

```python
from maivn_tools import (
    BearerTokenAuth,
    HttpClient,
    RetryPolicy,
    RateLimitPolicy,
    TokenBucket,
)

client = HttpClient(
    base_url="https://api.example.com",
    auth=BearerTokenAuth("token"),
    retry=RetryPolicy(max_attempts=4, initial_backoff_seconds=0.5),
    rate_limit=TokenBucket(RateLimitPolicy(requests_per_second=10, burst=20)),
    default_headers={"Accept": "application/json"},
)

response = client.get("/users/me")
print(response.json())
```

### Per-request controls

`HttpClient.request` accepts:

- `params` — query parameters merged with any added by the auth strategy.
- `headers` — per-request headers that override `default_headers`.
- `json` — JSON body; the client serializes it and sets `Content-Type`.
- `data` — raw bytes body.
- `timeout` — overrides the client default.
- `correlation_id` — sets `X-Request-ID`. A new UUID is generated when
  omitted.
- `idempotency_key` — sets `Idempotency-Key` when supplied.

### Retries

`RetryPolicy` is exponential backoff with full jitter. Defaults:

- `max_attempts=3`
- `initial_backoff_seconds=0.5`
- `max_backoff_seconds=30.0`
- `backoff_multiplier=2.0`
- `jitter=True`

Retries fire on `RetryableError`, `RateLimitError`, and `TransportError` by
default. Override `retry_on` to add provider-specific exceptions.

When a response includes a `Retry-After` header, the client honors it
instead of computing the next backoff. Values are clipped to
`max_backoff_seconds`.

### Rate limits

`RateLimitPolicy(requests_per_second, burst, scope)` declares cooperative
limits. `TokenBucket` is a thread-safe implementation suitable for in-
process throttling. The client calls `try_acquire` before each attempt and
sleeps via `time_until_available()` when tokens are not yet ready.

Hosts that already enforce limits upstream can leave `rate_limit=None`.

## Error normalization

The client maps HTTP status codes onto a stable exception hierarchy:

```
ConnectorError
├── TransportError
│   └── TimeoutError
├── ProviderError
│   ├── AuthError                   (401)
│   ├── PermissionDeniedError       (403)
│   ├── NotFoundError               (404)
│   ├── ValidationError             (400, 409, 422)
│   ├── RateLimitError              (429)
│   └── RetryableError              (5xx without a more specific mapping)
```

Use `normalize_status_error(status, message, detail=..., retry_after_seconds=...)`
to build the same exceptions from custom code paths.

## Pagination

The runtime provides four paginators covering common provider conventions:

| Helper | Convention |
| --- | --- |
| `CursorPaginator` | Opaque `next_cursor` returned by each page. |
| `OffsetPaginator` | `offset` and `limit` with optional `total`. |
| `PageTokenPaginator` | Google-style `next_page_token`. |
| `DeltaTokenPaginator` | Change feed with `next_link` and a final `delta_token`. |

Each paginator exposes `iter_pages()` and `iter_items()`:

```python
from maivn_tools import CursorPaginator

def fetch_page(cursor):
    resp = client.get("/items", params={"cursor": cursor})
    body = resp.json()
    return body, body.get("next_cursor")

paginator = CursorPaginator(fetch_page)
for item in paginator.iter_items():
    print(item)
```
