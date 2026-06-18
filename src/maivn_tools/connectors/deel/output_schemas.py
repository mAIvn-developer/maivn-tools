# pyright: strict
"""First-class output schemas for the Deel toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default. They are not the raw Deel payloads: each schema
mirrors exactly the compact dict the connector builds (``list_people`` and
``list_contracts``), so the assignment planner and repair loop can resolve
fields like ``employee_ref`` or ``contract_ref`` without guessing.

Raw Deel IDs (``person_id`` / ``contract_id``) are only present when a tool is
called with ``include_ids=True``; the read tools that return the provider
response unchanged are intentionally not annotated here.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_PERSON_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "employee_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "title": {"type": "string"},
        "department": {"type": "string"},
        "hiring_status": {"type": "string"},
        "hiring_type": {"type": "string"},
        "start_date": {"type": "string"},
        "person_id": {"type": ["string", "integer"]},
    },
    "required": ["employee_ref", "name"],
}

_CONTRACT_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "contract_ref": {"type": "string"},
        "title": {"type": "string"},
        "type": {"type": "string"},
        "status": {"type": "string"},
        "worker_name": {"type": "string"},
        "country": {"type": "string"},
        "start_date": {"type": "string"},
        "contract_id": {"type": ["string", "integer"]},
    },
    "required": ["contract_ref"],
}


# MARK: - Tool output schemas

LIST_PEOPLE_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "employees": {"type": "array", "items": _PERSON_SUMMARY},
        "page": {"type": ["integer", "null"]},
    },
    "required": ["employees"],
}

LIST_CONTRACTS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "contracts": {"type": "array", "items": _CONTRACT_SUMMARY},
        "page": {"type": ["integer", "null"]},
    },
    "required": ["contracts"],
}


__all__ = [
    "LIST_CONTRACTS_OUTPUT",
    "LIST_PEOPLE_OUTPUT",
]
