# Generic adapters

Most providers do not have a hand-written `maivn-tools` connector — and you
should not have to wait for one. The generic adapters let you stand up a
working, Agent-ready connector against almost any API in minutes, by
describing the shape of the API rather than coding each call by hand.

They cover the API styles a provider connector almost always needs:
REST/HTTP, OpenAPI, GraphQL, webhooks, and MCP servers. Each adapter sits on
the Tier 0 kernel, so callers automatically get retries, rate limits,
audit-friendly error normalization, and a test transport for free — the same
guarantees the first-party connectors are built on.

| Adapter | Use it when you have... |
| --- | --- |
| `GenericHttpConnector` | A REST API and a short list of endpoints to expose. |
| `OpenAPIConnector` | An OpenAPI 3.x document to import endpoints from. |
| `GraphQLConnector` | A GraphQL endpoint and a fixed catalog of operations. |
| `WebhookListener` | Inbound provider webhooks to verify and normalize. |
| `MCPBridge` | Existing MCP servers to surface as Agent tools. |

## `GenericHttpConnector`

Turns a list of `HttpEndpoint` definitions into Agent-ready callables.

```python
from maivn_tools import (
    AuthMode,
    BearerTokenAuth,
    GenericHttpConnector,
    HttpEndpoint,
    PermissionFlag,
    PermissionSet,
    ProviderMetadata,
)

connector = GenericHttpConnector(
    metadata=ProviderMetadata(
        name="example",
        display_name="Example API",
        version="0.1.0",
        auth_modes=(AuthMode.BEARER,),
    ),
    base_url="https://api.example.com",
    auth=BearerTokenAuth("token"),
    endpoints=[
        HttpEndpoint(name="ping", method="GET", path="/ping"),
        HttpEndpoint(
            name="create_widget",
            method="POST",
            path="/widgets",
            body_params=("name", "color"),
            permissions=PermissionSet(PermissionFlag.WRITE),
        ),
    ],
)
```

Each endpoint declares:

- `path` placeholders like `/users/{user_id}` — required keyword arguments.
- `query_params` — keyword arguments serialized into the URL.
- `body_params` — keyword arguments serialized into the JSON body. Not
  allowed on `GET`, `HEAD`, or `DELETE`.
- `static_query` and `static_headers` — merged into every call.
- `permissions` and `destructive` — declared upfront so hosts can inspect
  them.

Unknown keyword arguments are rejected at call time so tool surfaces stay
explicit.

## `OpenAPIConnector`

Imports an OpenAPI 3.x document and produces a list of `HttpEndpoint`
definitions. Pass the parsed mapping (not a URL); the importer does not
fetch documents over the network.

```python
import json
from maivn_tools import (
    GenericHttpConnector,
    OpenAPIConnector,
    PermissionFlag,
    PermissionSet,
    ProviderMetadata,
)

document = json.loads(spec_text)
importer = OpenAPIConnector(
    document,
    operation_allowlist={"listPets", "getPet", "createPet"},
    permission_overrides={"createPet": PermissionSet(PermissionFlag.WRITE)},
)
connector = GenericHttpConnector(
    metadata=ProviderMetadata(
        name="petstore",
        display_name="Petstore",
        version="0.1.0",
    ),
    base_url="https://petstore.example.com",
    endpoints=importer.endpoints(),
)
```

Defaults are conservative: safe methods (`GET`, `HEAD`, `OPTIONS`) get
`PermissionFlag.READ`; `DELETE` gets `PermissionFlag.DELETE` and is marked
destructive; everything else gets `PermissionFlag.WRITE`. Override per
operation through `permission_overrides` / `destructive_overrides`.

## `GraphQLConnector`

Exposes a fixed catalog of GraphQL operations as callable tools. The
connector forwards the query string verbatim — it never parses the
GraphQL — and surfaces a stable `ProviderError` when the response contains
an `errors` array.

```python
from maivn_tools import (
    GraphQLConnector,
    GraphQLOperation,
    PermissionFlag,
    PermissionSet,
    ProviderMetadata,
)

connector = GraphQLConnector(
    metadata=ProviderMetadata(
        name="example_gql",
        display_name="Example GraphQL",
        version="0.1.0",
    ),
    endpoint="https://api.example.com/graphql",
    operations=[
        GraphQLOperation(
            name="get_viewer",
            query="query GetViewer { viewer { id name } }",
            description="Return the authenticated viewer.",
        ),
        GraphQLOperation(
            name="create_post",
            query="mutation CreatePost($title: String!) { createPost(title: $title) { id } }",
            permissions=PermissionSet(PermissionFlag.WRITE),
            destructive=False,
            variables_allowlist=("title",),
        ),
    ],
)

create_post = connector.tools()[1]
create_post(variables={"title": "Hello"})
```

When `variables_allowlist` is non-empty, the tool rejects unknown variables.

## `WebhookListener`

Verifies and normalizes provider webhook deliveries. The listener is
transport-agnostic: pass raw headers and body, get back a normalized event.

```python
from maivn_tools import SignatureAlgorithm, WebhookListener, WebhookVerifier

listener = WebhookListener(
    provider="example",
    verifier=WebhookVerifier(
        secret="shared-secret",
        signature_header="X-Example-Signature",
        algorithm=SignatureAlgorithm.HMAC_SHA256,
        timestamp_header="X-Example-Timestamp",
        tolerance_seconds=300,
    ),
    event_type_header="X-Example-Event",
)

event = listener.handle(request.headers, request.body)
# event.payload is the parsed JSON body
```

`listener.try_handle(...)` returns `None` instead of raising on a signature
mismatch, which is useful for endpoints that always return `204` and log
failures asynchronously.

## MCP bridge

`MCPBridge` translates declarative `MCPServerSpec` definitions into
`maivn.MCPServer` instances.

```python
from maivn import Agent
from maivn_tools import MCPBridge, MCPHttpServer, MCPStdioServer

bridge = MCPBridge([
    MCPStdioServer(
        name="local-fs",
        command="uvx",
        args=("mcp-filesystem", "--root", "/srv/data"),
    ),
    MCPHttpServer(
        name="search",
        url="https://mcp.example.com",
        bearer_token="token",
        prefix="search.",
    ),
])

agent = Agent(model="auto", mcp_servers=bridge.build())
```

The bridge imports `maivn` lazily, so you can construct and inspect specs
without the SDK installed.
