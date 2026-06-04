# Auth and secrets

Almost every real connector needs a credential, and the two hard parts
are always the same: attaching it to the request correctly, and getting
it out of source control and into your runtime safely. `maivn-tools`
keeps those concerns apart so you can mix and match them. **Auth
strategies** decide *how* a credential rides on a request (a header, a
query param, a refreshed OAuth2 token); **secret resolvers** decide
*where* the credential comes from (an environment variable, an injected
map, a chain of fallbacks). You compose the two, and secrets stay out of
logs, metadata, and audit trails by default.

## Auth strategies

Every strategy implements `AuthStrategy` and provides two methods:

- `apply(request)` mutates a request dictionary in place to add headers or
  query parameters.
- `describe()` returns a JSON-serializable dictionary that contains **no
  secret material** — safe to log or include in connector catalogs.

### Built-in strategies

| Strategy | Use it for |
| --- | --- |
| `NoAuth` | Public endpoints; default for `HttpClient` when no auth is supplied. |
| `ApiKeyAuth(api_key, header=..., query_param=..., prefix=None)` | Static API key sent via header or query string. Provide exactly one of `header` or `query_param`. |
| `BearerTokenAuth(token, scheme="Bearer")` | Long-lived bearer token. Supports custom header names and schemes (e.g. `Token`). |
| `BasicAuth(username, password)` | HTTP Basic credentials. Encodes the pair into the `Authorization` header. |
| `OAuth2BearerAuth(provider)` | Bearer auth fed by a caller-supplied `OAuth2TokenProvider`. The provider handles refresh. |

### Custom strategies

Subclass `AuthStrategy` for providers with bespoke schemes — see the
[API policy](api-policy.md) for guarantees about the interface stability.

## OAuth 2.0 flow layer

The OAuth flow layer turns a token endpoint plus a client_id/secret into
managed access tokens. It supports four grants out of the box:

- Authorization code (with optional PKCE)
- Refresh token
- Client credentials
- Device code

```python
from maivn_tools import (
    OAuth2EndpointConfig,
    OAuth2Flow,
    generate_pkce_challenge,
)

flow = OAuth2Flow(
    client_id="...",
    client_secret="...",
    endpoints=OAuth2EndpointConfig(
        authorize_url="https://idp.example.test/oauth/authorize",
        token_url="https://idp.example.test/oauth/token",
    ),
)

# Authorization-code with PKCE
pkce = generate_pkce_challenge()
url = flow.authorization_url(
    redirect_uri="https://app.example.test/callback",
    scope="openid email",
    state="random-state",
    pkce=pkce,
)
# ... user grants, returns to callback with ?code=... ...
token = flow.exchange_code(code, redirect_uri="https://app.example.test/callback", pkce_verifier=pkce.verifier)
```

### Token caches

For long-running agents, wrap a refresh strategy in a `TokenCache`:

```python
cache = flow.refresh_token_cache(refresh_token, scope="api")
# Or for client-credentials services:
cache = flow.client_credentials_cache(scope="api")

connector = MyConnector(token=cache)
```

`TokenCache` is callable and returns a current `OAuth2Token` on demand,
refreshing only when the cached token is within the configured `leeway`
of its `expires_at`. It is thread-safe.

### Device code

For headless installations or CLIs:

```python
grant = flow.request_device_code(scope="api")
print(f"Visit {grant.verification_uri} and enter {grant.user_code}")
# Poll using grant.interval until the user completes the flow:
token = flow.poll_device_code(grant.device_code)
```

## Secret resolvers

A `SecretRef` is a *name* for a secret; a `SecretResolver` turns it into the
value. Provider connectors should accept either a resolved string **or** a
`SecretRef` and call the resolver only when they actually need the secret.

### Built-in resolvers

| Resolver | Source |
| --- | --- |
| `EnvironmentSecretResolver(env=None, prefix="")` | Process environment variables. |
| `StaticSecretResolver(secrets)` | An in-memory mapping. Intended for tests. |
| `ChainedSecretResolver([...])` | Walks a list of resolvers and returns the first match. |

```python
from maivn_tools import ChainedSecretResolver, EnvironmentSecretResolver, SecretRef

resolver = ChainedSecretResolver([
    EnvironmentSecretResolver(prefix="MAIVN_"),
    EnvironmentSecretResolver(),
])
token = resolver.resolve(SecretRef("GITHUB_TOKEN"))
```

`MissingSecretError` is raised when no resolver can provide the secret.
Use `try_resolve` to get `None` instead.

## Credential safety

- Never put secrets into `ProviderMetadata`, `ConnectionMetadata`, audit
  events, error messages, or `describe()` output.
- Treat `SecretRef` instances as the safe wire-format. Resolve them as late
  as possible.
- Strategies should not log raw tokens; the SDK request runtime never logs
  request headers by default.
- See the [security policy](security.md) for the full credential-safety
  policy.
