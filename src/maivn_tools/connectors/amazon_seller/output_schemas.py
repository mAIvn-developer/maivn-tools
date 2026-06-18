# pyright: strict
"""First-class output schemas for the Amazon Seller (SP-API) toolset.

These document the connector-owned, normalized ``_order_summary`` shape that
``list_orders`` returns by default (``include_raw=False``). They are not the raw
SP-API Orders payload: each schema mirrors exactly the compact dict the
connector builds, so the assignment planner and repair loop can resolve fields
like ``order_ref`` or ``amazon_order_id`` without guessing.

When ``list_orders`` is called with ``include_raw=True`` it returns the raw
provider payload instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summary (mirrors the connector's ``_order_summary`` builder)

_ORDER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "order_ref": {"type": "string"},
        "amazon_order_id": {"type": "string"},
        "purchase_date": {"type": "string"},
        "order_status": {"type": "string"},
        "fulfillment_channel": {"type": "string"},
        "buyer_email": {"type": "string"},
        "total_amount": {"type": "string"},
        "total_currency": {"type": "string"},
        "number_of_items_shipped": {"type": "integer"},
        "number_of_items_unshipped": {"type": "integer"},
        "amazon_order_id_raw": {"type": "string"},
        "seller_order_id": {"type": "string"},
    },
    "required": ["order_ref", "amazon_order_id"],
}


# MARK: - Tool output schemas

LIST_ORDERS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "orders": {"type": "array", "items": _ORDER_SUMMARY},
        "count": {"type": "integer"},
        "next_token": {"type": ["string", "null"]},
    },
    "required": ["orders", "count"],
}


__all__ = [
    "LIST_ORDERS_OUTPUT",
]
