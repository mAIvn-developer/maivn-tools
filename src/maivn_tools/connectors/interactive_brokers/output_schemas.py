# pyright: strict
"""First-class output schemas for the Interactive Brokers toolset.

These document the connector-owned, normalized shapes that the list tools
build from IBKR's Client Portal responses (the default, non-``raw`` form).
They are not the raw IBKR payloads: each schema mirrors exactly the compact
dict the connector assembles, so the assignment planner and repair loop can
resolve fields like ``position_ref`` or ``order_ref`` without guessing.

When a tool is called with ``raw=True`` it returns the unmodified provider
response instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's normalizer loops)

_POSITION_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "position_ref": {"type": "string"},
        "symbol": {"type": "string"},
        "position": {"type": ["number", "null"]},
        "mkt_value": {"type": ["number", "null"]},
        "mkt_price": {"type": ["number", "null"]},
        "avg_cost": {"type": ["number", "null"]},
        "unrealized_pnl": {"type": ["number", "null"]},
        "asset_class": {"type": "string"},
        "currency": {"type": "string"},
        "exchange": {"type": "string"},
        "conid": {"type": ["integer", "null"]},
    },
    "required": ["position_ref", "symbol"],
}

_ORDER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "order_ref": {"type": "string"},
        "symbol": {"type": "string"},
        "side": {"type": ["string", "null"]},
        "quantity": {"type": ["number", "null"]},
        "status": {"type": ["string", "null"]},
        "order_type": {"type": ["string", "null"]},
        "limit_price": {"type": ["number", "null"]},
        "avg_price": {"type": ["string", "number", "null"]},
        "filled_quantity": {"type": ["number", "null"]},
        "time_in_force": {"type": ["string", "null"]},
        "account_id": {"type": ["string", "null"]},
        "order_id": {"type": ["integer", "string", "null"]},
    },
    "required": ["order_ref", "symbol"],
}


# MARK: - Tool output schemas

LIST_POSITIONS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "positions": {"type": "array", "items": _POSITION_SUMMARY},
        "count": {"type": "integer"},
        "page_id": {"type": "integer"},
        "account_id": {"type": "string"},
    },
    "required": ["positions", "count", "account_id"],
}

LIST_ORDERS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "orders": {"type": "array", "items": _ORDER_SUMMARY},
        "count": {"type": "integer"},
    },
    "required": ["orders", "count"],
}


__all__ = [
    "LIST_ORDERS_OUTPUT",
    "LIST_POSITIONS_OUTPUT",
]
