# pyright: strict
"""First-class output schemas for the Rippling toolset.

These document the connector-owned, normalized shape that ``list_employees``
returns by default: a ``{"employees": [...], "totalAvailable": int}`` envelope
whose items are the compact dicts built by ``_employee_summary``. They are not
the raw Rippling employee payloads; each schema mirrors exactly the dict the
connector constructs, so the assignment planner and repair loop can resolve
fields like ``employee_ref`` without guessing.

The other Rippling tools return the raw provider response unchanged and are
intentionally left without a first-class output schema.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summary (mirrors ``_employee_summary``)

_EMPLOYEE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "employee_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "title": {"type": "string"},
        "department": {"type": "string"},
        "hire_date": {"type": "string"},
        "status": {"type": "string"},
        "employee_id": {"type": "string"},
    },
    "required": ["employee_ref", "name"],
}


# MARK: - Tool output schemas

LIST_EMPLOYEES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "employees": {"type": "array", "items": _EMPLOYEE_SUMMARY},
        "totalAvailable": {"type": "integer"},
    },
    "required": ["employees"],
}


__all__ = [
    "LIST_EMPLOYEES_OUTPUT",
]
