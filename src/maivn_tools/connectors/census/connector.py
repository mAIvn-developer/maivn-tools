"""Census reverse-ETL REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Helpers


def _normalize_order(order: str) -> str:
    """Map order values to the documented ``asc``/``desc`` enum.

    The Census API documents ``order`` as accepting only ``asc`` or ``desc``
    (ordering by creation time). Legacy ``id``/``-id`` values are mapped to the
    documented enum for backward compatibility.
    """
    mapping = {"id": "asc", "-id": "desc", "asc": "asc", "desc": "desc"}
    normalized = mapping.get(order)
    if normalized is None:
        raise ValueError("order must be one of 'asc' or 'desc'")
    return normalized


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
        mapping = cast("dict[str, Any]", candidate)
        for key in keys:
            value: Any = mapping.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    continue
        nested: Any
        for nested in mapping.values():
            if isinstance(nested, dict | list):
                try:
                    return _coerce_int_id(nested, *keys)
                except ValueError:
                    continue
    if isinstance(candidate, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        item: Any
        for item in sequence:
            try:
                return _coerce_int_id(item, *keys)
            except ValueError:
                continue
    candidate_type: type[object] = type(cast("object", candidate))
    raise ValueError(f"could not extract an int ID from {candidate_type.__name__}")


def _summarize_source(source: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "source_ref": f"source_{index}",
        "name": source.get("name") or source.get("label", ""),
        "type": source.get("type", ""),
        "created_at": source.get("created_at", ""),
    }
    if include_ids:
        summary["source_id"] = source.get("id", "")
    return summary


def _summarize_destination(
    destination: dict[str, Any], *, index: int, include_ids: bool
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "destination_ref": f"destination_{index}",
        "name": destination.get("name") or destination.get("label", ""),
        "type": destination.get("type", ""),
        "created_at": destination.get("created_at", ""),
    }
    if include_ids:
        summary["destination_id"] = destination.get("id", "")
    return summary


def _summarize_model(model: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "model_ref": f"model_{index}",
        "name": model.get("name") or model.get("label", ""),
        "source": model.get("source_id"),
        "created_at": model.get("created_at", ""),
    }
    if include_ids:
        summary["model_id"] = model.get("id", "")
        summary["source_id"] = model.get("source_id", "")
    else:
        summary.pop("source", None)
    return summary


def _summarize_sync(sync: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    schedule: Any = sync.get("schedule") or {}
    schedule_freq: Any = (
        cast("dict[str, Any]", schedule).get("frequency") if isinstance(schedule, dict) else ""
    )
    summary: dict[str, Any] = {
        "sync_ref": f"sync_{index}",
        "name": sync.get("label") or sync.get("name", ""),
        "destination": sync.get("destination_attributes", {}).get("connection_id")
        if isinstance(sync.get("destination_attributes"), dict)
        else "",
        "operation": sync.get("operation", ""),
        "schedule": schedule_freq,
        "paused": sync.get("paused"),
        "last_sync_status": sync.get("last_sync_run", {}).get("status", "")
        if isinstance(sync.get("last_sync_run"), dict)
        else "",
    }
    if include_ids:
        summary["sync_id"] = sync.get("id", "")
    return summary


def _summarize_sync_run(run: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "run_ref": f"run_{index}",
        "status": run.get("status", ""),
        "started_at": run.get("created_at") or run.get("scheduled_execution_time", ""),
        "finished_at": run.get("completed_at", ""),
        "records_processed": run.get("records_processed"),
        "records_updated": run.get("records_updated"),
        "records_failed": run.get("records_failed"),
        "error": run.get("error_message") or run.get("error", ""),
    }
    if include_ids:
        summary["run_id"] = run.get("id", "")
        summary["sync_id"] = run.get("sync_id", "")
    return summary


# MARK: ToolSet


@toolset(prefix="census")
class CensusToolSet:
    """A connector for the Census v0 REST API.

    Args:
        secret_token: Workspace secret token (used as the HTTP Basic
            password with an empty username).
    """

    metadata = ProviderMetadata(
        name="census",
        display_name="Census",
        version="0.1.0",
        description="Sources, models, destinations, syncs, and runs.",
        auth_modes=(AuthMode.BASIC,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.getcensus.com/basics/api",
        homepage_url="https://www.getcensus.com/",
        tags=("etl", "reverse-etl"),
    )

    def __init__(
        self,
        *,
        secret_token: str,
        base_url: str = "https://app.getcensus.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not secret_token:
            raise ValueError("secret_token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BasicAuth("bearer", secret_token),
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
    def list_sources(
        self,
        *,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List sources (warehouses Census reads from).

        Best first tool for discovering sources. Returns compact summaries
        with ``source_ref``, name, type, and created date. Raw source IDs
        are omitted by default — set ``include_ids=True`` only when a
        follow-up tool needs the raw ``source_id``. Pass ``raw=True`` for
        the unfiltered API response.
        """
        payload: dict[str, Any] = self._client.get("/api/v1/sources").json()
        if raw:
            return payload
        items: Any = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        source: Any
        for index, source in enumerate(items, start=1):
            if isinstance(source, dict):
                summaries.append(
                    _summarize_source(
                        cast("dict[str, Any]", source), index=index, include_ids=include_ids
                    )
                )
        return {"sources": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_source(self, source_id: Any) -> dict[str, Any]:
        """Return one source's full configuration.

        Returns the raw Census source resource. ``source_id`` may be a raw
        integer ID or a source dict from :meth:`list_sources`
        (``include_ids=True``).
        """
        resolved_id = _coerce_int_id(source_id, "source_id", "id")
        if not resolved_id:
            raise ValueError("source_id is required")
        return self._client.get(f"/api/v1/sources/{resolved_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_destinations(
        self,
        *,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List destinations (downstream tools Census writes to).

        Returns compact summaries with ``destination_ref``, name, type,
        and created date. Raw destination IDs are omitted by default — set
        ``include_ids=True`` when a follow-up tool needs the raw
        ``destination_id``. Pass ``raw=True`` for the unfiltered API
        response.
        """
        payload: dict[str, Any] = self._client.get("/api/v1/destinations").json()
        if raw:
            return payload
        items: Any = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        destination: Any
        for index, destination in enumerate(items, start=1):
            if isinstance(destination, dict):
                summaries.append(
                    _summarize_destination(
                        cast("dict[str, Any]", destination), index=index, include_ids=include_ids
                    )
                )
        return {"destinations": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_models(
        self,
        *,
        order: str = "id",
        page: int = 1,
        per_page: int = 25,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List models (source-side query definitions).

        Returns compact summaries with ``model_ref``, name, and created
        date. Raw model IDs are omitted by default — set
        ``include_ids=True`` when a follow-up tool needs the raw
        ``model_id``. Pass ``raw=True`` for the unfiltered API response.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        payload: dict[str, Any] = self._client.get(
            "/api/v1/models",
            params={"order": _normalize_order(order), "page": page, "per_page": per_page},
        ).json()
        if raw:
            return payload
        items: Any = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        model: Any
        for index, model in enumerate(items, start=1):
            if isinstance(model, dict):
                summaries.append(
                    _summarize_model(
                        cast("dict[str, Any]", model), index=index, include_ids=include_ids
                    )
                )
        return {"models": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_model(self, model_id: Any) -> dict[str, Any]:
        """Return one model's full definition.

        Returns the raw Census model resource. ``model_id`` may be a raw
        integer ID or a model dict from :meth:`list_models`
        (``include_ids=True``).
        """
        resolved_id = _coerce_int_id(model_id, "model_id", "id")
        if not resolved_id:
            raise ValueError("model_id is required")
        return self._client.get(f"/api/v1/models/{resolved_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_syncs(
        self,
        *,
        order: str = "id",
        page: int = 1,
        per_page: int = 25,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List syncs (model -> destination pipelines).

        Returns compact summaries with ``sync_ref``, name, destination,
        operation, schedule frequency, paused flag, and last-run status.
        Raw IDs are omitted by default — set ``include_ids=True`` when a
        follow-up tool like :meth:`trigger_sync` needs the raw
        ``sync_id``. Pass ``raw=True`` for the unfiltered API response.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        payload: dict[str, Any] = self._client.get(
            "/api/v1/syncs",
            params={"order": _normalize_order(order), "page": page, "per_page": per_page},
        ).json()
        if raw:
            return payload
        items: Any = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        sync: Any
        for index, sync in enumerate(items, start=1):
            if isinstance(sync, dict):
                summaries.append(
                    _summarize_sync(
                        cast("dict[str, Any]", sync), index=index, include_ids=include_ids
                    )
                )
        return {"syncs": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_sync(self, sync_id: Any) -> dict[str, Any]:
        """Return one sync's full configuration.

        Returns the raw Census sync resource. ``sync_id`` may be a raw
        integer ID or a sync dict from :meth:`list_syncs`
        (``include_ids=True``).
        """
        resolved_id = _coerce_int_id(sync_id, "sync_id", "id")
        if not resolved_id:
            raise ValueError("sync_id is required")
        return self._client.get(f"/api/v1/syncs/{resolved_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def trigger_sync(
        self,
        sync_id: Any,
        *,
        force_full_sync: bool = False,
    ) -> dict[str, Any]:
        """Trigger a sync run.

        Returns the new sync-run resource (with ``id``, ``status``).
        ``sync_id`` may be a raw integer ID or a sync dict from
        :meth:`list_syncs` (``include_ids=True``). ``force_full_sync=True``
        re-emits the full dataset rather than incremental changes and is
        heavier — confirm with the user first if it would generate
        meaningful destination cost.
        """
        resolved_id = _coerce_int_id(sync_id, "sync_id", "id")
        if not resolved_id:
            raise ValueError("sync_id is required")
        return self._client.post(
            f"/api/v1/syncs/{resolved_id}/trigger",
            params={"force_full_sync": force_full_sync},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_sync_runs(
        self,
        sync_id: Any,
        *,
        order: str = "desc",
        page: int = 1,
        per_page: int = 25,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List sync runs for a sync.

        Returns compact summaries with ``run_ref``, status, start/end
        timestamps, record counts (processed/updated/failed), and error
        message. ``sync_id`` is required and may be a raw integer ID or a
        sync dict from :meth:`list_syncs` (``include_ids=True``); the live
        API only exposes sync runs nested under their parent sync. Raw run
        IDs are omitted by default — set ``include_ids=True`` when a
        follow-up tool needs the raw ``run_id``. Pass ``raw=True`` for the
        unfiltered API response.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        resolved_sync_id = _coerce_int_id(sync_id, "sync_id", "id")
        if not resolved_sync_id:
            raise ValueError("sync_id is required")
        params: dict[str, Any] = {
            "order": _normalize_order(order),
            "page": page,
            "per_page": per_page,
        }
        payload: dict[str, Any] = self._client.get(
            f"/api/v1/syncs/{resolved_sync_id}/sync_runs", params=params
        ).json()
        if raw:
            return payload
        items: Any = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        run: Any
        for index, run in enumerate(items, start=1):
            if isinstance(run, dict):
                summaries.append(
                    _summarize_sync_run(
                        cast("dict[str, Any]", run), index=index, include_ids=include_ids
                    )
                )
        return {"runs": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_sync_run(self, sync_run_id: Any) -> dict[str, Any]:
        """Return one sync run's full details.

        Returns the raw Census sync-run resource. ``sync_run_id`` may be a
        raw integer ID or a run dict from :meth:`list_sync_runs`
        (``include_ids=True``).
        """
        resolved_id = _coerce_int_id(sync_run_id, "sync_run_id", "run_id", "id")
        if not resolved_id:
            raise ValueError("sync_run_id is required")
        return self._client.get(f"/api/v1/sync_runs/{resolved_id}").json()
