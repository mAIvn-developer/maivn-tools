# pyright: strict
"""First-class output schemas for the Gusto toolset.

These document the connector-owned shapes that the discovery/list tools build
themselves, rather than the raw Gusto REST payloads. ``list_companies`` wraps
the companies it discovers from ``GET /v1/me`` into a ``{"companies": [...]}``
envelope (each entry carries the ``uuid`` used as ``company_uuid`` elsewhere),
and ``list_employees`` returns ``{"employees": [...]}`` of the compact
``_employee_summary`` dicts. Each schema mirrors exactly what the connector's
own code produces so the assignment planner and repair loop can resolve fields
like ``employee_ref`` or ``uuid`` without guessing.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's builders)

_COMPANY_ITEM: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "uuid": {"type": "string"},
    },
    "required": ["uuid"],
}

_EMPLOYEE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "employee_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "title": {"type": "string"},
        "department": {"type": "string"},
        "hire_date": {"type": "string"},
        "is_terminated": {"type": "boolean"},
        "employee_id": {"type": "string"},
    },
    "required": ["employee_ref", "name"],
}


# MARK: - Tool output schemas

LIST_COMPANIES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "companies": {"type": "array", "items": _COMPANY_ITEM},
    },
    "required": ["companies"],
}

LIST_EMPLOYEES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "employees": {"type": "array", "items": _EMPLOYEE_SUMMARY},
    },
    "required": ["employees"],
}


__all__ = [
    "LIST_COMPANIES_OUTPUT",
    "LIST_EMPLOYEES_OUTPUT",
]
