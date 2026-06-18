# pyright: strict
"""First-class output schemas for the 1Password Connect toolset.

These document the connector-owned, normalized shapes that the list tools
return -- the compact ``_vault_summary`` / ``_item_summary`` dicts the connector
builds, not the raw 1Password Connect payloads. The ``delete_item`` and
``get_heartbeat`` schemas mirror the small status dicts those tools construct.

Tools that return the raw provider response unchanged (``get_vault``,
``get_item``, ``create_item``, ``update_item``, ``patch_item``,
``get_item_files``) are provider-dependent and intentionally not described here.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_VAULT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "vault_ref": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "type": {"type": "string"},
        "item_count": {"type": "integer"},
        "vault_id": {"type": "string"},
    },
    "required": ["vault_ref", "name"],
}

_ITEM_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "item_ref": {"type": "string"},
        "title": {"type": "string"},
        "category": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "updated_at": {"type": "string"},
        "primary_url": {"type": "string"},
        "item_id": {"type": "string"},
        "vault_id": {"type": "string"},
    },
    "required": ["item_ref", "title"],
}


# MARK: - Tool output schemas

LIST_VAULTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "vaults": {"type": "array", "items": _VAULT_SUMMARY},
    },
    "required": ["vaults"],
}

LIST_ITEMS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": _ITEM_SUMMARY},
        "vault_id": {"type": "string"},
    },
    "required": ["items"],
}

DELETE_ITEM_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "item_id": {"type": "string"},
        "deleted": {"type": "boolean"},
        "status": {"type": "integer"},
    },
    "required": ["item_id", "deleted"],
}

HEARTBEAT_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "alive": {"type": "boolean"},
    },
    "required": ["status", "alive"],
}


__all__ = [
    "DELETE_ITEM_OUTPUT",
    "HEARTBEAT_OUTPUT",
    "LIST_ITEMS_OUTPUT",
    "LIST_VAULTS_OUTPUT",
]
