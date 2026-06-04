"""Airbyte Cloud / OSS REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: ID coercion helpers


def _coerce_id(candidate: Any, *keys: str) -> str:
    """Pick a string ID from a raw value, dict, or list of dicts.

    Accepts a raw string ID, a dict with one of ``keys``, or a list of such
    dicts. Used by tolerant write tools so the agent can pass in dicts
    returned from list/get tools directly.
    """
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, int):
        return str(candidate)
    if isinstance(candidate, dict):
        mapping = cast("dict[Any, Any]", candidate)
        for key in keys:
            value: Any = mapping.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, int):
                return str(value)
        for nested in mapping.values():
            nested_value: Any = nested
            if isinstance(nested_value, dict | list):
                try:
                    return _coerce_id(nested_value, *keys)
                except ValueError:
                    continue
    if isinstance(candidate, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in sequence:
            item_value: Any = item
            try:
                return _coerce_id(item_value, *keys)
            except ValueError:
                continue
    raise ValueError(f"could not extract an ID from {type(cast('object', candidate)).__name__}")


def _coerce_int_id(candidate: Any, *keys: str) -> int:
    """Coerce a value to an integer ID, with the same tolerance as ``_coerce_id``."""
    if isinstance(candidate, int):
        return candidate
    raw = _coerce_id(candidate, *keys)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"could not coerce {raw!r} to int") from exc


# MARK: Summary builders


def _summarize_workspace(
    workspace: dict[str, Any], *, index: int, include_ids: bool
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "workspace_ref": f"workspace_{index}",
        "name": workspace.get("name", ""),
        "data_residency": workspace.get("dataResidency", ""),
    }
    if include_ids:
        summary["workspace_id"] = workspace.get("workspaceId") or workspace.get("id", "")
    return summary


def _summarize_source(source: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "source_ref": f"source_{index}",
        "name": source.get("name", ""),
        "source_type": source.get("sourceType") or source.get("sourceName", ""),
    }
    if include_ids:
        summary["source_id"] = source.get("sourceId") or source.get("id", "")
        summary["workspace_id"] = source.get("workspaceId", "")
    return summary


def _summarize_destination(
    destination: dict[str, Any], *, index: int, include_ids: bool
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "destination_ref": f"destination_{index}",
        "name": destination.get("name", ""),
        "destination_type": destination.get("destinationType")
        or destination.get("destinationName", ""),
    }
    if include_ids:
        summary["destination_id"] = destination.get("destinationId") or destination.get("id", "")
        summary["workspace_id"] = destination.get("workspaceId", "")
    return summary


def _summarize_connection(
    connection: dict[str, Any], *, index: int, include_ids: bool
) -> dict[str, Any]:
    schedule: Any = connection.get("schedule") or {}
    schedule_type: Any = (
        cast("dict[str, Any]", schedule).get("scheduleType") if isinstance(schedule, dict) else ""
    ) or connection.get("scheduleType", "")
    summary: dict[str, Any] = {
        "connection_ref": f"connection_{index}",
        "name": connection.get("name", ""),
        "source": connection.get("sourceName") or connection.get("sourceId", ""),
        "destination": connection.get("destinationName") or connection.get("destinationId", ""),
        "schedule": schedule_type,
        "status": connection.get("status", ""),
    }
    if include_ids:
        summary["connection_id"] = connection.get("connectionId") or connection.get("id", "")
        summary["source_id"] = connection.get("sourceId", "")
        summary["destination_id"] = connection.get("destinationId", "")
    return summary


def _summarize_job(job: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "job_ref": f"job_{index}",
        "job_type": job.get("jobType", ""),
        "status": job.get("status", ""),
        "started_at": job.get("startTime") or job.get("createdAt", ""),
        "ended_at": job.get("endTime") or job.get("updatedAt", ""),
        "rows_synced": job.get("rowsSynced") or job.get("recordsSynced"),
        "bytes_synced": job.get("bytesSynced"),
    }
    if include_ids:
        summary["job_id"] = job.get("jobId") or job.get("id", "")
        summary["connection_id"] = job.get("connectionId", "")
    return summary


# MARK: Toolset


@toolset(prefix="airbyte")
class AirbyteToolSet:
    """A connector for the Airbyte v1 REST API.

    Args:
        access_token: Bearer token (Airbyte Cloud) or workspace token (OSS).
        base_url: API root. Defaults to Airbyte Cloud.
    """

    metadata = ProviderMetadata(
        name="airbyte",
        display_name="Airbyte",
        version="0.1.0",
        description="Workspaces, sources, destinations, connections, and jobs.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://reference.airbyte.com/",
        homepage_url="https://airbyte.com/",
        tags=("etl", "data-movement"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        base_url: str = "https://api.airbyte.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
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
    def list_workspaces(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List workspaces in the Airbyte account.

        Best first tool for discovering workspaces. Returns compact
        summaries with a stable ``workspace_ref``, name, and data residency.
        Raw workspace IDs are omitted by default — set ``include_ids=True``
        only when a follow-up tool (e.g. :meth:`list_sources`) needs the
        raw ``workspaceId``. Pass ``raw=True`` to bypass the summary view.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        payload: dict[str, Any] = self._client.get(
            "/v1/workspaces", params={"limit": limit, "offset": offset}
        ).json()
        if raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, workspace in enumerate(items, start=1):
            if isinstance(workspace, dict):
                summaries.append(
                    _summarize_workspace(
                        cast("dict[str, Any]", workspace), index=index, include_ids=include_ids
                    )
                )
        return {"workspaces": summaries, "next": payload.get("next")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_sources(
        self,
        *,
        workspace_ids: list[str] | None = None,
        limit: int = 25,
        offset: int = 0,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List sources (data origins) in the account.

        Returns compact summaries with ``source_ref``, name, and source
        type. Raw source IDs are omitted by default — set
        ``include_ids=True`` when a follow-up tool like
        :meth:`create_connection` or :meth:`delete_source` needs the raw
        ``sourceId``. Pass ``raw=True`` for the unfiltered API response.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if workspace_ids is not None:
            params["workspaceIds"] = workspace_ids
        payload: dict[str, Any] = self._client.get("/v1/sources", params=params).json()
        if raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, source in enumerate(items, start=1):
            if isinstance(source, dict):
                summaries.append(
                    _summarize_source(
                        cast("dict[str, Any]", source), index=index, include_ids=include_ids
                    )
                )
        return {"sources": summaries, "next": payload.get("next")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_source(self, source_id: Any) -> dict[str, Any]:
        """Return one source's full configuration.

        Returns the raw Airbyte source resource. ``source_id`` may be a
        raw ID string or a source dict from :meth:`list_sources`
        (``include_ids=True``).
        """
        resolved_id = _coerce_id(source_id, "source_id", "sourceId", "id")
        if not resolved_id:
            raise ValueError("source_id is required")
        return self._client.get(f"/v1/sources/{resolved_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_source(
        self,
        *,
        workspace_id: str,
        name: str,
        source_type: str,
        configuration: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a source in a workspace.

        Returns the new source resource (with its server-assigned
        ``sourceId``). ``source_type`` is an Airbyte source name (e.g.
        ``postgres``, ``stripe``). ``configuration`` carries the
        source-type-specific connection fields.
        """
        if not workspace_id or not name or not source_type:
            raise ValueError("workspace_id, name, and source_type are required")
        return self._client.post(
            "/v1/sources",
            json={
                "workspaceId": workspace_id,
                "name": name,
                "sourceType": source_type,
                "configuration": configuration,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_source(self, source_id: Any) -> dict[str, Any]:
        """Permanently delete a source. Destructive and irreversible.

        Returns ``{"source_id": ..., "deleted": True, "status": ...}``.
        Confirm with the user before calling — every connection that uses
        this source will also become invalid.
        """
        resolved_id = _coerce_id(source_id, "source_id", "sourceId", "id")
        if not resolved_id:
            raise ValueError("source_id is required")
        response = self._client.delete(f"/v1/sources/{resolved_id}")
        return {"source_id": resolved_id, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_destinations(
        self,
        *,
        workspace_ids: list[str] | None = None,
        limit: int = 25,
        offset: int = 0,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List destinations (data sinks) in the account.

        Returns compact summaries with ``destination_ref``, name, and
        destination type. Raw destination IDs are omitted by default — set
        ``include_ids=True`` when a follow-up tool needs the raw
        ``destinationId``. Pass ``raw=True`` for the unfiltered API
        response.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if workspace_ids is not None:
            params["workspaceIds"] = workspace_ids
        payload: dict[str, Any] = self._client.get("/v1/destinations", params=params).json()
        if raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, destination in enumerate(items, start=1):
            if isinstance(destination, dict):
                summaries.append(
                    _summarize_destination(
                        cast("dict[str, Any]", destination), index=index, include_ids=include_ids
                    )
                )
        return {"destinations": summaries, "next": payload.get("next")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_connections(
        self,
        *,
        workspace_ids: list[str] | None = None,
        limit: int = 25,
        offset: int = 0,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List connections (source -> destination pipelines).

        Returns compact summaries with ``connection_ref``, human-readable
        ``source`` and ``destination``, schedule type, and status. Raw IDs
        are omitted by default — set ``include_ids=True`` when a follow-up
        tool like :meth:`trigger_sync` needs the raw ``connectionId``.
        Pass ``raw=True`` for the unfiltered API response.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if workspace_ids is not None:
            params["workspaceIds"] = workspace_ids
        payload: dict[str, Any] = self._client.get("/v1/connections", params=params).json()
        if raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, connection in enumerate(items, start=1):
            if isinstance(connection, dict):
                summaries.append(
                    _summarize_connection(
                        cast("dict[str, Any]", connection), index=index, include_ids=include_ids
                    )
                )
        return {"connections": summaries, "next": payload.get("next")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_connection(self, connection_id: Any) -> dict[str, Any]:
        """Return one connection's full configuration + status.

        Returns the raw Airbyte connection resource. ``connection_id`` may
        be a raw ID or a connection dict from :meth:`list_connections`
        (``include_ids=True``).
        """
        resolved_id = _coerce_id(connection_id, "connection_id", "connectionId", "id")
        if not resolved_id:
            raise ValueError("connection_id is required")
        return self._client.get(f"/v1/connections/{resolved_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_connection(
        self,
        *,
        source_id: str,
        destination_id: str,
        name: str,
        configurations: dict[str, Any] | None = None,
        schedule: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a connection wiring a source to a destination.

        Returns the new connection resource (with its server-assigned
        ``connectionId``). ``configurations`` describes per-stream sync
        settings; ``schedule`` controls cadence (e.g.
        ``{"scheduleType": "manual"}``).
        """
        if not source_id or not destination_id or not name:
            raise ValueError("source_id, destination_id, and name are required")
        body: dict[str, Any] = {
            "sourceId": source_id,
            "destinationId": destination_id,
            "name": name,
        }
        if configurations is not None:
            body["configurations"] = configurations
        if schedule is not None:
            body["schedule"] = schedule
        return self._client.post("/v1/connections", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def trigger_sync(self, connection_id: Any) -> dict[str, Any]:
        """Trigger a one-off sync on a connection.

        Returns the new job resource (with ``jobId``, ``status``).
        ``connection_id`` may be a raw ID or a connection dict from
        :meth:`list_connections` (``include_ids=True``) /
        :meth:`get_connection`.
        """
        resolved_id = _coerce_id(connection_id, "connection_id", "connectionId", "id")
        if not resolved_id:
            raise ValueError("connection_id is required")
        return self._client.post(
            "/v1/jobs",
            json={"connectionId": resolved_id, "jobType": "sync"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def trigger_reset(self, connection_id: Any) -> dict[str, Any]:
        """Reset a connection's replication state. Clears destination data.

        Returns the new job resource. ``connection_id`` accepts the same
        formats as :meth:`trigger_sync`. This is heavier than a normal
        sync — confirm with the user first.
        """
        resolved_id = _coerce_id(connection_id, "connection_id", "connectionId", "id")
        if not resolved_id:
            raise ValueError("connection_id is required")
        return self._client.post(
            "/v1/jobs",
            json={"connectionId": resolved_id, "jobType": "reset"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_jobs(
        self,
        *,
        connection_id: str | None = None,
        status: str | None = None,
        limit: int = 25,
        offset: int = 0,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List sync jobs (optionally filtered by connection or status).

        Returns compact summaries with ``job_ref``, job type, status,
        start/end timestamps, and rows synced. Raw job IDs are omitted by
        default — set ``include_ids=True`` when a follow-up tool needs the
        raw ``jobId``. Pass ``raw=True`` for the unfiltered API response.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if connection_id is not None:
            params["connectionId"] = connection_id
        if status is not None:
            params["status"] = status
        payload: dict[str, Any] = self._client.get("/v1/jobs", params=params).json()
        if raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, job in enumerate(items, start=1):
            if isinstance(job, dict):
                summaries.append(
                    _summarize_job(
                        cast("dict[str, Any]", job), index=index, include_ids=include_ids
                    )
                )
        return {"jobs": summaries, "next": payload.get("next")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_job(self, job_id: Any) -> dict[str, Any]:
        """Return one job's full details.

        Returns the raw Airbyte job resource (status, attempt history,
        rows/bytes synced). ``job_id`` may be a raw integer ID or a job
        dict from :meth:`list_jobs` (``include_ids=True``).
        """
        resolved_id = _coerce_int_id(job_id, "job_id", "jobId", "id")
        if not resolved_id:
            raise ValueError("job_id is required")
        return self._client.get(f"/v1/jobs/{resolved_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def cancel_job(self, job_id: Any) -> dict[str, Any]:
        """Cancel a running job. Destructive (the in-flight sync is aborted).

        Returns the cancelled job resource. ``job_id`` may be a raw integer
        ID or a job dict from :meth:`list_jobs` (``include_ids=True``).
        Confirm with the user before calling — partial syncs may leave
        destination tables in an inconsistent state.
        """
        resolved_id = _coerce_int_id(job_id, "job_id", "jobId", "id")
        if not resolved_id:
            raise ValueError("job_id is required")
        return self._client.delete(f"/v1/jobs/{resolved_id}").json()
