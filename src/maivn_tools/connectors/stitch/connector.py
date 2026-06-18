# pyright: strict
"""Stitch Data Connect + Import REST API connector."""

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_SOURCES_OUTPUT

# MARK: Helpers


def _coerce_int_id(candidate: Any, *keys: str) -> int:
    """Coerce a value to an integer ID, accepting raw values, dicts, or lists."""
    if isinstance(candidate, int):
        return candidate
    if isinstance(candidate, str):
        try:
            return int(candidate)
        except ValueError as exc:
            raise ValueError(f"could not coerce {candidate!r} to int") from exc
    if isinstance(candidate, dict):
        mapping = cast("dict[Any, Any]", candidate)
        for key in keys:
            value: Any = mapping.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    continue
        for nested in mapping.values():
            nested_value: Any = nested
            if isinstance(nested_value, dict | list):
                try:
                    return _coerce_int_id(nested_value, *keys)
                except ValueError:
                    continue
    if isinstance(candidate, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in sequence:
            item_value: Any = item
            try:
                return _coerce_int_id(item_value, *keys)
            except ValueError:
                continue
    raise ValueError(f"could not extract an int ID from {type(cast('object', candidate)).__name__}")


def _summarize_source(source: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    schedule: Any = source.get("schedule")
    current_status: Any = source.get("current_status")
    summary: dict[str, Any] = {
        "source_ref": f"source_{index}",
        "name": source.get("display_name") or source.get("name", ""),
        "type": source.get("type", ""),
        "schedule": cast("dict[str, Any]", schedule).get("frequency_in_minutes")
        if isinstance(schedule, dict)
        else source.get("frequency_in_minutes"),
        "paused": source.get("paused_at") is not None,
        "last_run_status": cast("dict[str, Any]", current_status).get("status", "")
        if isinstance(current_status, dict)
        else "",
    }
    if include_ids:
        summary["source_id"] = source.get("id", "")
    return summary


# MARK: ToolSet


@toolset(prefix="stitch")
class StitchToolSet:
    """A connector for Stitch Data Connect.

    Args:
        access_token: Stitch API access token.
        region: ``"na"`` (default) or ``"eu"`` for the EU stack.
    """

    metadata = ProviderMetadata(
        name="stitch",
        display_name="Stitch Data",
        version="0.1.0",
        description="Sources, destinations, replication, and import streams.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url=("https://www.stitchdata.com/docs/developers/stitch-connect/api"),
        homepage_url="https://www.stitchdata.com/",
        tags=("etl", "data-movement"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        region: str = "na",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        if region not in {"na", "eu"}:
            raise ValueError("region must be na or eu")
        self.connection = connection
        host = "api.stitchdata.com" if region == "na" else "api.eu-central-1.stitchdata.com"
        self._client = HttpClient(
            base_url=f"https://{host}",
            auth=BearerTokenAuth(access_token),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_SOURCES_OUTPUT)
    def list_sources(
        self,
        *,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List sources in the Stitch account.

        Best first tool for discovering sources. Returns compact summaries
        with ``source_ref``, name, type, schedule (frequency in minutes),
        paused flag, and last-run status. Raw source IDs are omitted by
        default — set ``include_ids=True`` only when a follow-up tool
        (e.g. :meth:`update_source`, :meth:`trigger_extraction`,
        :meth:`delete_source`) needs the raw ``source_id``. Pass
        ``raw=True`` for the unfiltered API response.
        """
        payload: Any = self._client.get("/v4/sources").json()
        if raw:
            return payload
        items: list[Any] = cast(
            "list[Any]",
            payload if isinstance(payload, list) else (payload.get("data") or []),
        )
        summaries: list[dict[str, Any]] = []
        for index, source in enumerate(items, start=1):
            source_value: Any = source
            if isinstance(source_value, dict):
                summaries.append(
                    _summarize_source(
                        cast("dict[str, Any]", source_value),
                        index=index,
                        include_ids=include_ids,
                    )
                )
        return {"sources": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_source(self, source_id: Any) -> dict[str, Any]:
        """Return one source's full configuration + status.

        Returns the raw Stitch source resource. ``source_id`` may be a raw
        integer ID or a source dict from :meth:`list_sources`
        (``include_ids=True``).
        """
        resolved_id = _coerce_int_id(source_id, "source_id", "id")
        if not resolved_id:
            raise ValueError("source_id is required")
        return self._client.get(f"/v4/sources/{resolved_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_source(
        self,
        *,
        type: str,
        display_name: str,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a source.

        Returns the new source resource (with its server-assigned ``id``).
        ``type`` is a Stitch source type (e.g. ``"platform.postgres"``);
        ``properties`` carries the source-type-specific connection fields.
        """
        if not type or not display_name:
            raise ValueError("type and display_name are required")
        body: dict[str, Any] = {"type": type, "display_name": display_name}
        if properties is not None:
            body["properties"] = properties
        return self._client.post("/v4/sources", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_source(
        self,
        source_id: Any,
        *,
        display_name: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Patch a source.

        Returns the updated source resource. ``source_id`` may be a raw ID
        or a source dict from :meth:`list_sources` (``include_ids=True``).
        At least one of ``display_name`` / ``properties`` is required.
        """
        resolved_id = _coerce_int_id(source_id, "source_id", "id")
        if not resolved_id:
            raise ValueError("source_id is required")
        body: dict[str, Any] = {}
        if display_name is not None:
            body["display_name"] = display_name
        if properties is not None:
            body["properties"] = properties
        if not body:
            raise ValueError("at least one update field is required")
        return self._client.put(f"/v4/sources/{resolved_id}", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_source(self, source_id: Any) -> dict[str, Any]:
        """Permanently delete a source. Destructive and irreversible.

        Returns ``{"source_id": ..., "deleted": True, "status": ...}``.
        ``source_id`` may be a raw ID or a source dict. Confirm with the
        user before calling — all replication state is removed.
        """
        resolved_id = _coerce_int_id(source_id, "source_id", "id")
        if not resolved_id:
            raise ValueError("source_id is required")
        response = self._client.delete(f"/v4/sources/{resolved_id}")
        return {"source_id": resolved_id, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_streams(self, source_id: Any) -> dict[str, Any]:
        """List streams (tables) discovered for a source.

        Returns the raw streams payload. ``source_id`` may be a raw ID or
        a source dict from :meth:`list_sources` (``include_ids=True``).
        """
        resolved_id = _coerce_int_id(source_id, "source_id", "id")
        if not resolved_id:
            raise ValueError("source_id is required")
        return self._client.get(f"/v4/sources/{resolved_id}/streams").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_stream(
        self,
        *,
        source_id: Any,
        tap_stream_id: str,
        metadata: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Update stream metadata (selection / replication keys).

        Returns the updated stream resource. ``source_id`` may be a raw ID
        or a source dict from the corresponding list tool. ``tap_stream_id``
        is the stream's ``tap_stream_id`` string (from :meth:`list_streams`).
        ``metadata`` is a list of breadcrumb-keyed entries, e.g.
        ``[{"breadcrumb": [], "metadata": {"selected": True}}]``.
        """
        resolved_source_id = _coerce_int_id(source_id, "source_id", "id")
        if not resolved_source_id or not tap_stream_id or not metadata:
            raise ValueError("source_id, tap_stream_id, and metadata are required")
        return self._client.put(
            f"/v4/sources/{resolved_source_id}/streams/metadata",
            json={"streams": [{"tap_stream_id": tap_stream_id, "metadata": metadata}]},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_destination(self) -> dict[str, Any]:
        """Return the account's destination configuration(s).

        Returns the raw Stitch ``GET /v4/destinations`` payload, which is an
        array of Destination objects (Stitch typically configures a single
        destination per account). No ID is required.
        """
        return self._client.get("/v4/destinations").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def trigger_extraction(self, source_id: Any) -> dict[str, Any]:
        """Trigger a source extraction now.

        Returns the API ack payload. ``source_id`` may be a raw ID or a
        source dict from :meth:`list_sources` (``include_ids=True``).
        """
        resolved_id = _coerce_int_id(source_id, "source_id", "id")
        if not resolved_id:
            raise ValueError("source_id is required")
        return self._client.post(f"/v4/sources/{resolved_id}/sync").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_replication_summary(
        self,
        source_id: Any,
    ) -> dict[str, Any]:
        """Return replication progress for a source.

        Returns the raw last-connection-check payload (rows replicated,
        last sync timestamp, error details). ``source_id`` may be a raw ID
        or a source dict.
        """
        resolved_id = _coerce_int_id(source_id, "source_id", "id")
        if not resolved_id:
            raise ValueError("source_id is required")
        return self._client.get(f"/v4/sources/{resolved_id}/last-connection-check").json()
