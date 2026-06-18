# pyright: strict
"""First-class output schemas for the Census toolset.

These document the connector-owned, normalized ``_summarize_*`` shapes that the
list tools return by default (``raw=False``). They are not the raw Census REST
payloads: each schema mirrors exactly the compact dict the connector builds, so
the assignment planner and repair loop can resolve fields like ``sync_ref`` or
``run_ref`` without guessing.

When a tool is called with ``raw=True`` it returns the raw provider response
instead; these schemas describe the default normalized form.
"""

from __future__ import annotations

from pydantic import JsonValue

# MARK: - Entity summaries (mirror the connector's ``_summarize_*`` builders)

_SOURCE_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "source_ref": {"type": "string"},
        "name": {"type": "string"},
        "type": {"type": "string"},
        "created_at": {"type": "string"},
        "source_id": {"type": ["integer", "string"]},
    },
    "required": ["source_ref", "name"],
}

_DESTINATION_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "destination_ref": {"type": "string"},
        "name": {"type": "string"},
        "type": {"type": "string"},
        "created_at": {"type": "string"},
        "destination_id": {"type": ["integer", "string"]},
    },
    "required": ["destination_ref", "name"],
}

_MODEL_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "model_ref": {"type": "string"},
        "name": {"type": "string"},
        "source": {"type": ["integer", "string", "null"]},
        "created_at": {"type": "string"},
        "model_id": {"type": ["integer", "string"]},
        "source_id": {"type": ["integer", "string"]},
    },
    "required": ["model_ref", "name"],
}

_SYNC_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "sync_ref": {"type": "string"},
        "name": {"type": "string"},
        "destination": {"type": ["integer", "string"]},
        "operation": {"type": "string"},
        "schedule": {"type": "string"},
        "paused": {"type": ["boolean", "null"]},
        "last_sync_status": {"type": "string"},
        "sync_id": {"type": ["integer", "string"]},
    },
    "required": ["sync_ref", "name"],
}

_SYNC_RUN_SUMMARY: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "run_ref": {"type": "string"},
        "status": {"type": "string"},
        "started_at": {"type": "string"},
        "finished_at": {"type": "string"},
        "records_processed": {"type": ["integer", "null"]},
        "records_updated": {"type": ["integer", "null"]},
        "records_failed": {"type": ["integer", "null"]},
        "error": {"type": "string"},
        "run_id": {"type": ["integer", "string"]},
        "sync_id": {"type": ["integer", "string"]},
    },
    "required": ["run_ref", "status"],
}


# MARK: - Tool output schemas

LIST_SOURCES_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {"sources": {"type": "array", "items": _SOURCE_SUMMARY}},
    "required": ["sources"],
}

LIST_DESTINATIONS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {"destinations": {"type": "array", "items": _DESTINATION_SUMMARY}},
    "required": ["destinations"],
}

LIST_MODELS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {"models": {"type": "array", "items": _MODEL_SUMMARY}},
    "required": ["models"],
}

LIST_SYNCS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {"syncs": {"type": "array", "items": _SYNC_SUMMARY}},
    "required": ["syncs"],
}

LIST_SYNC_RUNS_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "properties": {"runs": {"type": "array", "items": _SYNC_RUN_SUMMARY}},
    "required": ["runs"],
}


__all__ = [
    "LIST_DESTINATIONS_OUTPUT",
    "LIST_MODELS_OUTPUT",
    "LIST_SOURCES_OUTPUT",
    "LIST_SYNCS_OUTPUT",
    "LIST_SYNC_RUNS_OUTPUT",
]
