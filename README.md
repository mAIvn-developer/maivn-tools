# maivn-tools

`maivn-tools` provides connector toolsets, generic API adapters, file helpers,
and an HTTP runtime for the [mAIvn Python SDK](https://maivn.io).

> **Pre-release software.** Most provider connectors are covered by offline
> contract tests but have not yet been exercised end to end against live
> provider accounts. Test the exact operations and permissions you plan to use
> before relying on a connector with production data.

## Install

```bash
pip install maivn-tools
```

The package installs `maivn` as a direct dependency. Provider credentials stay
in the caller's process; use the authentication and secret-resolver APIs rather
than putting credentials in prompts, tool metadata, or source code.

## Start here

- [Quickstart](docs/quickstart.md)
- [Toolset authoring](docs/toolsets.md)
- [Authentication and secrets](docs/auth.md)
- [Permissions and dry runs](docs/permissions.md)
- [Connector catalog](docs/index.md#connectors-by-category)

The package exports more than 170 toolsets. Register only the tools and
permissions needed for a workflow, and exclude destructive tools when the
application does not need them.

```python
from pathlib import Path

from maivn import Agent
from maivn_tools import LocalFilesToolSet

workspace = Path('./documents')
workspace.mkdir(exist_ok=True)

agent = Agent(name='Document reviewer')
agent.add_toolset(LocalFilesToolSet(workspace), include_tags=['read'])
```

See each connector page for its constructor, provider scopes, pagination,
write behavior, and current validation limits.
