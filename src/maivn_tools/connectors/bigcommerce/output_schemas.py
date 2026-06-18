# pyright: strict
"""First-class output schemas for the BigCommerce toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default. They are not the raw BigCommerce REST payloads:
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
        "price": {"type": ["number", "string"]},
        "is_visible": {"type": ["boolean", "null"]},
        "inventory_level": {"type": ["integer", "null"]},
        "product_id": {"type": ["integer", "null"]},
    },
    "required": ["product_ref"],
}

_ORDER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "order_ref": {"type": "string"},
        "order_number": {"type": ["integer", "string"]},
        "customer_name": {"type": "string"},
        "customer_email": {"type": "string"},
        "total_inc_tax": {"type": ["number", "string"]},
        "currency_code": {"type": "string"},
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
        "company": {"type": "string"},
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
        "meta": {"type": ["object", "null"]},
    },
    "required": ["products", "count"],
}

LIST_ORDERS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "orders": {"type": "array", "items": _ORDER_SUMMARY},
        "count": {"type": "integer"},
    },
    "required": ["orders", "count"],
}

LIST_CUSTOMERS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "customers": {"type": "array", "items": _CUSTOMER_SUMMARY},
        "count": {"type": "integer"},
    },
    "required": ["customers", "count"],
}


__all__ = [
    "LIST_CUSTOMERS_OUTPUT",
    "LIST_ORDERS_OUTPUT",
    "LIST_PRODUCTS_OUTPUT",
]
