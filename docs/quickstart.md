# Quickstart

Most agents are only as useful as the systems they can touch. This page
is the shortest path from `pip install` to an `Agent` that can actually
call a live HTTP API — no per-provider glue, no custom runtime. You
describe a few endpoints, register them, and the agent treats each one
as a tool it can invoke.

By the end you will have configured a generic HTTP connector, registered
it on an `Agent`, called a tool directly, and reused the same connector
on a `Swarm`.

## Install

```bash
pip install maivn-tools
```

Installing `maivn-tools` pulls the `maivn` SDK as a direct dependency, so a
single command gives you both. The package is **not** exposed as a
`maivn[tools]` extra — see the install note in [`index.md`](index.md) for
the rationale.

## Configure a generic HTTP connector

`GenericHttpConnector` takes provider metadata, a base URL, an auth
strategy, and a list of `HttpEndpoint` definitions. Each endpoint becomes a
single callable tool.

```python
from maivn import Agent
from maivn_tools import (
    AuthMode,
    BearerTokenAuth,
    GenericHttpConnector,
    HttpEndpoint,
    PermissionFlag,
    PermissionSet,
    ProviderMetadata,
    register_connector,
)

connector = GenericHttpConnector(
    metadata=ProviderMetadata(
        name="status_api",
        display_name="Status API",
        version="0.1.0",
        description="Read-only status endpoints.",
        auth_modes=(AuthMode.BEARER,),
    ),
    base_url="https://status.example.com",
    auth=BearerTokenAuth("token-from-secrets"),
    endpoints=[
        HttpEndpoint(
            name="get_incident",
            method="GET",
            path="/incidents/{incident_id}",
            description="Return one incident by id.",
        ),
        HttpEndpoint(
            name="list_incidents",
            method="GET",
            path="/incidents",
            description="List recent incidents.",
            query_params=("severity", "limit"),
        ),
        HttpEndpoint(
            name="acknowledge_incident",
            method="POST",
            path="/incidents/{incident_id}/ack",
            description="Acknowledge an incident.",
            body_params=("comment",),
            permissions=PermissionSet(PermissionFlag.WRITE),
        ),
    ],
)

agent = Agent(model="auto")
register_connector(agent, connector)
```

`register_connector` calls `agent.add_tool` once per endpoint. Each tool's
`permissions`, `destructive`, and `__doc__` attributes are populated so
hosts can inspect them.

### Model tiers

`model="auto"` selects a mAIvn model tier rather than a specific
provider model id. The SDK accepts four tier values:

| Tier | Use it for |
| --- | --- |
| `"auto"` | Recommended default. Let the SDK pick the cheapest tier that meets the task. |
| `"fast"` | Latency-sensitive, low-complexity work. |
| `"balanced"` | Steady mid-tier choice when you want a single tier for everything. |
| `"max"` | Highest-capability reasoning, accepts higher cost and latency. |

Tier-based selection insulates your application from the underlying
provider's model lifecycle; the SDK resolves each tier to a current model
at runtime.

## Use a tool

Tools take keyword arguments matching their declared path, query, and body
parameters:

```python
incident = connector.tools()[0]  # get_incident
result = incident(incident_id="inc-123")
```

## Use with a Swarm

`Swarm` exposes the same `add_tool` surface, so `register_connector` works
unchanged:

```python
from maivn import Swarm

swarm = Swarm(name="ops", agents=[agent])
register_connector(swarm, connector)
```

## Where to go next

- [Auth & secrets](auth.md) — load credentials from environment variables or
  custom resolvers.
- [Generic adapters](generic-adapters.md) — import OpenAPI documents,
  expose GraphQL operations, or verify webhook deliveries.
- [Testing connectors](testing.md) — write fast unit tests with
  `MockTransport` instead of live network calls.
