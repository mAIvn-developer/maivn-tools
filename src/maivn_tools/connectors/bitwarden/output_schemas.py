# pyright: strict
"""First-class output schemas for the Bitwarden toolset.

These document the connector-owned, normalized shape that ``list_secrets``
returns. It is not the raw SDK-server payload: the schema mirrors exactly the
compact dict the connector builds via ``_secret_summary`` (``secret_ref`` plus
``key``, and ``secret_id`` only when ``include_ids=True``), so the assignment
planner and repair loop can resolve a secret reference without guessing.

The value-returning read tools (``get_secret``, ``get_secrets_by_ids``) and the
write tools return the raw decrypted SDK-server response unchanged and are
therefore intentionally not given a first-class schema here.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_secret_summary`` builder)

_SECRET_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "secret_ref": {"type": "string"},
        "key": {"type": "string"},
        "secret_id": {"type": "string"},
    },
    "required": ["secret_ref", "key"],
}


# MARK: - Tool output schemas

LIST_SECRETS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "secrets": {"type": "array", "items": _SECRET_SUMMARY},
    },
    "required": ["secrets"],
}


__all__ = [
    "LIST_SECRETS_OUTPUT",
]
