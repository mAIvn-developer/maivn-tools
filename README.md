# mAIvn Tools

Optional tool integrations for the mAIvn Python SDK.

This repository is intentionally scaffolded as a standalone PyPI package. It is also
intended to become the implementation target for a future `maivn[tools]` optional
dependency, but the core `maivn` package is not wired to that extra yet.

## Development

```powershell
uv sync
uv run pytest
uv run ruff check .
uv run pyright
```
