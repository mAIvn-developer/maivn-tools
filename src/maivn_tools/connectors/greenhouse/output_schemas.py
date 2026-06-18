# pyright: strict
"""First-class output schemas for the Greenhouse toolset.

These document the connector-owned, normalized ``_*_summary`` shapes that the
list tools build from the raw Harvest payloads. They are not the raw Greenhouse
responses: each schema mirrors exactly the compact dict the connector emits, so
the assignment planner and repair loop can resolve fields like ``job_ref`` or
``candidate_ref`` without guessing.

Raw provider IDs (``job_id``/``candidate_id``) are only present when a tool is
called with ``include_ids=True``; they are documented here as optional.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_*_summary`` builders)

_JOB_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "job_ref": {"type": "string"},
        "name": {"type": "string"},
        "status": {"type": "string"},
        "office_names": {"type": "array", "items": {"type": "string"}},
        "opened_at": {"type": ["string", "null"]},
        "closed_at": {"type": ["string", "null"]},
        "job_id": {"type": ["integer", "string"]},
    },
    "required": ["job_ref"],
}

_CANDIDATE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "candidate_ref": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "title": {"type": "string"},
        "company": {"type": "string"},
        "application_date": {"type": ["string", "null"]},
        "candidate_id": {"type": ["integer", "string"]},
    },
    "required": ["candidate_ref"],
}


# MARK: - Tool output schemas

LIST_JOBS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "jobs": {"type": "array", "items": _JOB_SUMMARY},
    },
    "required": ["jobs"],
}

LIST_CANDIDATES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "candidates": {"type": "array", "items": _CANDIDATE_SUMMARY},
    },
    "required": ["candidates"],
}


__all__ = [
    "LIST_CANDIDATES_OUTPUT",
    "LIST_JOBS_OUTPUT",
]
