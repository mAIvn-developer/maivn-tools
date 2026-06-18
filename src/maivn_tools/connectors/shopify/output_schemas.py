# pyright: strict
"""First-class output schemas for the Shopify toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default. They are not the raw Shopify Admin REST payloads:
each schema mirrors exactly the compact dict the connector builds, so the
assignment planner and repair loop can resolve fields like ``product_ref`` or
``order_number`` without guessing.

When a tool is called with ``include_raw=True`` it returns the unmodified
provider response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_PRODUCT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "product_ref": {"type": "string"},
        "title": {"type": "string"},
        "status": {"type": "string"},
        "vendor": {"type": "string"},
        "product_type": {"type": "string"},
        "sku": {"type": "string"},
        "price": {"type": "string"},
        "inventory_quantity": {"type": "integer"},
        "product_id": {"type": ["integer", "null"]},
    },
    "required": ["product_ref", "title"],
}

_ORDER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "order_ref": {"type": "string"},
        "order_number": {"type": "string"},
        "customer_name": {"type": "string"},
        "total_price": {"type": "string"},
        "currency": {"type": "string"},
        "financial_status": {"type": "string"},
        "fulfillment_status": {"type": "string"},
        "created_at": {"type": "string"},
        "order_id": {"type": ["integer", "null"]},
    },
    "required": ["order_ref", "order_number"],
}

_CUSTOMER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "customer_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "orders_count": {"type": "integer"},
        "total_spent": {"type": "string"},
        "state": {"type": "string"},
        "customer_id": {"type": ["integer", "null"]},
    },
    "required": ["customer_ref"],
}


# MARK: - Wrapper helpers


def _listing(item_key: str, item_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], "count": int}`` schema."""
    return {
        "type": "object",
        "properties": {
            item_key: {"type": "array", "items": item_schema},
            "count": {"type": "integer"},
        },
        "required": [item_key],
    }


# MARK: - Tool output schemas

LIST_PRODUCTS_OUTPUT: dict[str, JsonValue] = _listing("products", _PRODUCT_SUMMARY)
LIST_ORDERS_OUTPUT: dict[str, JsonValue] = _listing("orders", _ORDER_SUMMARY)
LIST_CUSTOMERS_OUTPUT: dict[str, JsonValue] = _listing("customers", _CUSTOMER_SUMMARY)


__all__ = [
    "LIST_CUSTOMERS_OUTPUT",
    "LIST_ORDERS_OUTPUT",
    "LIST_PRODUCTS_OUTPUT",
]
