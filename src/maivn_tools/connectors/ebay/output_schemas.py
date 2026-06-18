# pyright: strict
"""First-class output schemas for the eBay toolset.

These document the connector-owned, normalized shapes that the listing tools
return by default (``include_raw=False``). They are not the raw eBay REST
payloads: each schema mirrors exactly the compact dict the connector builds via
``_item_summary`` / ``_order_summary``, so the assignment planner and repair
loop can resolve fields like ``item_ref`` or ``order_ref`` without guessing.

When a tool is called with ``include_raw=True`` it returns the raw provider
response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_ITEM_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "item_ref": {"type": "string"},
        "title": {"type": "string"},
        "price_value": {"type": "string"},
        "price_currency": {"type": "string"},
        "condition": {"type": "string"},
        "buying_options": {"type": "array", "items": {"type": "string"}},
        "item_web_url": {"type": "string"},
        "item_id": {"type": "string"},
        "legacy_item_id": {"type": "string"},
    },
    "required": ["item_ref"],
}

_ORDER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "order_ref": {"type": "string"},
        "creation_date": {"type": "string"},
        "order_fulfillment_status": {"type": "string"},
        "order_payment_status": {"type": "string"},
        "buyer_username": {"type": "string"},
        "total_value": {"type": "string"},
        "total_currency": {"type": "string"},
        "order_id": {"type": "string"},
        "legacy_order_id": {"type": "string"},
    },
    "required": ["order_ref"],
}


# MARK: - Wrapper helpers


def _listing(item_key: str, item_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], count: int, total, next}`` schema."""
    return {
        "type": "object",
        "properties": {
            item_key: {"type": "array", "items": item_schema},
            "count": {"type": "integer"},
            "total": {"type": ["integer", "null"]},
            "next": {"type": ["string", "null"]},
        },
        "required": [item_key, "count"],
    }


# MARK: - Tool output schemas

SEARCH_ITEMS_OUTPUT: dict[str, JsonValue] = _listing("items", _ITEM_SUMMARY)
LIST_ORDERS_OUTPUT: dict[str, JsonValue] = _listing("orders", _ORDER_SUMMARY)


__all__ = [
    "LIST_ORDERS_OUTPUT",
    "SEARCH_ITEMS_OUTPUT",
]
