# pyright: strict
"""First-class output schemas for the Segment toolset.

These document the connector-owned, normalized shapes that the ``list_*``
tools build via ``_entity_summary``. They are not the raw Segment Public API
payloads: each schema mirrors exactly the compact dict the connector
constructs (``{<entity>_ref, name, slug, enabled, category, <entity>_id}``)
wrapped under the listing key plus a ``nextCursor`` pagination handle.

The ``category`` field appears only when the raw entity carries a ``metadata``
object, and ``<entity>_id`` only when the tool is called with
``include_ids=True``; both are therefore optional and never ``required``.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_entity_summary`` builder)

_SOURCE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "source_ref": {"type": "string"},
        "name": {"type": "string"},
        "slug": {"type": "string"},
        "enabled": {"type": "boolean"},
        "category": {"type": "string"},
        "source_id": {"type": "string"},
    },
    "required": ["source_ref"],
}

_DESTINATION_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "destination_ref": {"type": "string"},
        "name": {"type": "string"},
        "slug": {"type": "string"},
        "enabled": {"type": "boolean"},
        "category": {"type": "string"},
        "destination_id": {"type": "string"},
    },
    "required": ["destination_ref"],
}

_WAREHOUSE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "warehouse_ref": {"type": "string"},
        "name": {"type": "string"},
        "slug": {"type": "string"},
        "enabled": {"type": "boolean"},
        "category": {"type": "string"},
        "warehouse_id": {"type": "string"},
    },
    "required": ["warehouse_ref"],
}


# MARK: - Wrapper helper


def _listing(item_key: str, item_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], nextCursor: str | null}`` schema."""
    return {
        "type": "object",
        "properties": {
            item_key: {"type": "array", "items": item_schema},
            "nextCursor": {"type": ["string", "null"]},
        },
        "required": [item_key],
    }


# MARK: - Tool output schemas

LIST_SOURCES_OUTPUT: dict[str, JsonValue] = _listing("sources", _SOURCE_SUMMARY)
LIST_DESTINATIONS_OUTPUT: dict[str, JsonValue] = _listing("destinations", _DESTINATION_SUMMARY)
LIST_WAREHOUSES_OUTPUT: dict[str, JsonValue] = _listing("warehouses", _WAREHOUSE_SUMMARY)


__all__ = [
    "LIST_DESTINATIONS_OUTPUT",
    "LIST_SOURCES_OUTPUT",
    "LIST_WAREHOUSES_OUTPUT",
]
