# pyright: strict
"""First-class output schemas for the WooCommerce toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default. They are not the raw WooCommerce REST payloads:
each schema mirrors exactly the compact dict the connector builds, so the
assignment planner and repair loop can resolve fields like ``product_ref`` or
``order_number`` without guessing.

When a tool is called with ``include_raw=True`` it returns the raw provider
response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_PRODUCT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "product_ref": {"type": "string"},
        "name": {"type": "string"},
        "sku": {"type": "string"},
        "price": {"type": "string"},
        "status": {"type": "string"},
        "stock_status": {"type": "string"},
        "stock_quantity": {"type": ["integer", "null"]},
        "product_id": {"type": ["integer", "null"]},
    },
    "required": ["product_ref"],
}

_ORDER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "order_ref": {"type": "string"},
        "order_number": {"type": ["string", "integer"]},
        "customer_name": {"type": "string"},
        "customer_email": {"type": "string"},
        "total": {"type": "string"},
        "currency": {"type": "string"},
        "status": {"type": "string"},
        "date_created": {"type": "string"},
        "order_id": {"type": ["integer", "null"]},
    },
    "required": ["order_ref"],
}

_CUSTOMER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "customer_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "username": {"type": "string"},
        "role": {"type": "string"},
        "customer_id": {"type": ["integer", "null"]},
    },
    "required": ["customer_ref"],
}


# MARK: - Tool output schemas

LIST_PRODUCTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "products": {"type": "array", "items": _PRODUCT_SUMMARY},
        "count": {"type": "integer"},
    },
    "required": ["products"],
}

LIST_ORDERS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "orders": {"type": "array", "items": _ORDER_SUMMARY},
        "count": {"type": "integer"},
    },
    "required": ["orders"],
}

LIST_CUSTOMERS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "customers": {"type": "array", "items": _CUSTOMER_SUMMARY},
        "count": {"type": "integer"},
    },
    "required": ["customers"],
}


__all__ = [
    "LIST_CUSTOMERS_OUTPUT",
    "LIST_ORDERS_OUTPUT",
    "LIST_PRODUCTS_OUTPUT",
]
