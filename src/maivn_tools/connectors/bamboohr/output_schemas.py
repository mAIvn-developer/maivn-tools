# pyright: strict
"""First-class output schemas for the BambooHR toolset.

These document the connector-owned, normalized shape that ``list_employees``
returns by default. It is not the raw BambooHR directory payload: the schema
mirrors exactly the compact dict the connector builds (an ``employees`` array of
``_employee_summary`` dicts plus a ``totalAvailable`` count), so the assignment
planner and repair loop can resolve fields like ``employee_ref`` without
guessing.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summary (mirrors the connector's ``_employee_summary`` builder)

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
        "employee_id": {"type": ["string", "integer"]},
    },
    "required": ["employee_ref", "name"],
}


# MARK: - Tool output schemas

LIST_EMPLOYEES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "employees": {"type": "array", "items": _EMPLOYEE_SUMMARY},
        "totalAvailable": {"type": "integer"},
        "fields": {"type": ["array", "object", "null"]},
    },
    "required": ["employees"],
}


__all__ = [
    "LIST_EMPLOYEES_OUTPUT",
]
