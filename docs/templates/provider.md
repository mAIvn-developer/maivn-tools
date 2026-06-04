# <Provider name> connector

> Replace this template with the real connector docs. Keep the section
> ordering so every connector reads the same way. Most connectors are
> class-walk toolsets and use the `<Provider>ToolSet` name; the
> `<Provider>Connector` name is reserved for data-driven builders.

`<Provider>ToolSet` wraps the <Provider> API and exposes the tools an
agent needs most. It is built on `maivn_tools.runtime.HttpClient` (or the
relevant transport), and inherits retries, rate limits, and error
normalization from the kernel.

```python
from maivn import Agent
from maivn_tools import <Provider>ToolSet, register_connector

agent = Agent(model="auto")
agent.add_toolset(<Provider>ToolSet(token="..."))

# Builder-style connectors (the `<Provider>Connector` name) register
# their callables instead:
# register_connector(agent, <Provider>Connector(token="..."))
```

## Authentication

State the supported auth modes here. Reference the auth strategy or OAuth
flow used. List the scopes the connector advertises through
`metadata.scopes`.

| Mode | Notes |
| --- | --- |
| Bearer token | Sent as `Authorization: Bearer ...`. |
| OAuth 2.0 (auth code) | Use `OAuth2Flow` with the provider's authorize and token URLs. |
| API key | Set via `ApiKeyAuth(api_key, header=...)`. |

## Tools

List every public tool the connector exposes. Use the same table format
so users can scan quickly.

| Tool | Permission | Description |
| --- | --- | --- |
| `tool_a(arg1, arg2)` | READ | One-line description. |
| `tool_b(arg1, *, arg2)` | WRITE | One-line description. |
| `tool_c(arg1)` | DELETE (destructive) | One-line description. |

Include short examples for any non-obvious argument shape (cursor-based
pagination, complex filter syntax, attachment payloads).

## Errors

Document any provider-specific errors and how the connector maps them
onto the stable hierarchy in `maivn_tools.runtime.errors`. If the
connector defines its own `ProviderError` subclass, name it here.

## Configuration

| Argument | Default | Purpose |
| --- | --- | --- |
| `token` | required | Bearer or API token. |
| `base_url` | provider default | Override for tenants or test stacks. |
| `transport` | None | Custom `HttpTransport`, primarily for tests. |
| `connection` | None | Optional `ConnectionMetadata` for host bookkeeping. |

## Rate limits and pagination

Describe the provider's rate-limit headers and recommend a
`RateLimitPolicy`. Identify the pagination convention the connector uses
(cursor, page-token, offset) and point at the matching paginator helper.

## Webhooks

Only include this section if the connector ships a webhook listener.
Document the signature header, algorithm, encoding, and timestamp header,
and link to `docs/events.md`.

## Live tests

Add the required environment variables to `docs/testing.md` and call out
any sandbox-account requirements the provider imposes here.
