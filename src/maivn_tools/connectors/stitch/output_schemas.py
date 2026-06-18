# pyright: strict
"""First-class output schemas for the Stitch toolset.

These document the connector-owned, normalized shape that ``list_sources``
returns by default. It is not the raw Stitch payload: the schema mirrors
exactly the compact ``_summarize_source`` dict the connector builds, so the
assignment planner and repair loop can resolve fields like ``source_ref``
without guessing.

When a tool is called with ``raw=True`` it returns the raw provider response
instead; this schema describes the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_summarize_source`` builder)

_SOURCE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "source_ref": {"type": "string"},
        "name": {"type": "string"},
        "type": {"type": "string"},
        "schedule": {"type": ["integer", "null"]},
        "paused": {"type": "boolean"},
        "last_run_status": {"type": "string"},
        "source_id": {"type": ["integer", "string"]},
    },
    "required": ["source_ref", "name"],
}


# MARK: - Tool output schemas

LIST_SOURCES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "sources": {"type": "array", "items": _SOURCE_SUMMARY},
    },
    "required": ["sources"],
}


__all__ = [
    "LIST_SOURCES_OUTPUT",
]
