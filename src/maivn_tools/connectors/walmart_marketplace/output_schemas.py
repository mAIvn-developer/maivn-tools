# pyright: strict
"""First-class output schemas for the Walmart Marketplace toolset.

These document the connector-owned, normalized shapes that ``list_items`` and
``list_orders`` build from the raw Walmart v3 payloads (the default
``include_raw=False`` path). Each schema mirrors exactly the compact dict the
connector constructs via ``_item_summary`` / ``_order_summary`` so the
assignment planner and repair loop can resolve fields like ``sku`` or
``purchase_order_id`` without guessing.

When a tool is called with ``include_raw=True`` it returns the raw provider
payload instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_ITEM_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "item_ref": {"type": "string"},
        "sku": {"type": "string"},
        "product_name": {"type": "string"},
        "price": {"type": ["object", "number", "string", "null"]},
        "publish_status": {"type": "string"},
        "lifecycle_status": {"type": "string"},
        "wpid": {"type": "string"},
        "gtin": {"type": "string"},
    },
    "required": ["item_ref", "sku"],
}

_ORDER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "order_ref": {"type": "string"},
        "purchase_order_id": {"type": "string"},
        "customer_order_id": {"type": "string"},
        "order_date": {"type": "string"},
        "customer_name": {"type": "string"},
        "customer_email_id": {"type": "string"},
        "purchase_order_id_raw": {"type": "string"},
    },
    "required": ["order_ref", "purchase_order_id"],
}


# MARK: - Tool output schemas

LIST_ITEMS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": _ITEM_SUMMARY},
        "count": {"type": "integer"},
        "total_items": {"type": ["integer", "null"]},
        "next_cursor": {"type": ["string", "null"]},
    },
    "required": ["items", "count"],
}

LIST_ORDERS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "orders": {"type": "array", "items": _ORDER_SUMMARY},
        "count": {"type": "integer"},
        "next_cursor": {"type": ["string", "null"]},
    },
    "required": ["orders", "count"],
}


__all__ = [
    "LIST_ITEMS_OUTPUT",
    "LIST_ORDERS_OUTPUT",
]
