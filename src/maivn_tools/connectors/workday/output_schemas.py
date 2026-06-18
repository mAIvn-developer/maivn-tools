# pyright: strict
"""First-class output schemas for the Workday toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools return by default. They are not the raw Workday REST payloads: each
schema mirrors exactly the compact dict the connector builds, so the assignment
planner and repair loop can resolve fields like ``worker_ref`` or ``job_ref``
without guessing.

When a list tool receives a payload whose ``data`` is not a list it returns the
raw provider response instead; these schemas describe the default normalized
form. Raw Workday IDs (``worker_id``, ``candidate_id``, ``job_id``) only appear
when called with ``include_ids=True``.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_WORKER_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "worker_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "title": {"type": "string"},
        "hire_date": {"type": "string"},
        "is_active": {"type": "boolean"},
        "worker_id": {"type": "string"},
    },
    "required": ["worker_ref", "name"],
}

_CANDIDATE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "candidate_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "status": {"type": "string"},
        "application_date": {"type": "string"},
        "candidate_id": {"type": "string"},
    },
    "required": ["candidate_ref", "name"],
}

_JOB_POSTING_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "job_ref": {"type": "string"},
        "title": {"type": "string"},
        "location": {"type": "string"},
        "posted_at": {"type": "string"},
        "status": {"type": "string"},
        "job_id": {"type": "string"},
    },
    "required": ["job_ref", "title"],
}


# MARK: - Wrapper helpers


def _listing(item_key: str, item_schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Build a ``{<item_key>: [...], total: int | null}`` schema."""
    return {
        "type": "object",
        "properties": {
            item_key: {"type": "array", "items": item_schema},
            "total": {"type": ["integer", "null"]},
        },
        "required": [item_key],
    }


# MARK: - Tool output schemas

LIST_WORKERS_OUTPUT: dict[str, JsonValue] = _listing("workers", _WORKER_SUMMARY)
LIST_JOB_POSTINGS_OUTPUT: dict[str, JsonValue] = _listing("jobs", _JOB_POSTING_SUMMARY)
LIST_CANDIDATES_OUTPUT: dict[str, JsonValue] = _listing("candidates", _CANDIDATE_SUMMARY)


__all__ = [
    "LIST_CANDIDATES_OUTPUT",
    "LIST_JOB_POSTINGS_OUTPUT",
    "LIST_WORKERS_OUTPUT",
]
