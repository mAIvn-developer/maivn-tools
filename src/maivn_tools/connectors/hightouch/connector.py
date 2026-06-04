"""Hightouch REST API connector."""
# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

_API_VERSION = "v1"
_DEFAULT_BASE_URL = f"https://api.hightouch.com/api/{_API_VERSION}"


# MARK: Helpers


def _coerce_id(candidate: Any, *keys: str) -> str:
    """Pick a string ID from a raw value, dict, or list of dicts.

    Used by tolerant write tools so the agent can pass in the dicts
    returned from list/get tools directly.
    """
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, int):
        return str(candidate)
    if isinstance(candidate, dict):
        candidate_dict = cast("dict[Any, Any]", candidate)
        for key in keys:
            value: Any = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, int):
                return str(value)
        for nested in candidate_dict.values():
            nested_value: Any = nested
            if isinstance(nested_value, dict | list):
                try:
                    return _coerce_id(nested_value, *keys)
                except ValueError:
                    continue
    if isinstance(candidate, list | tuple):
        candidate_seq = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in candidate_seq:
            item_value: Any = item
            try:
                return _coerce_id(item_value, *keys)
            except ValueError:
                continue
    type_name = type(cast("object", candidate)).__name__
    raise ValueError(f"could not extract an ID from {type_name}")


def _summarize_source(source: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "source_ref": f"source_{index}",
        "name": source.get("name") or source.get("slug", ""),
        "type": source.get("type", ""),
        "created_at": source.get("createdAt", ""),
    }
    if include_ids:
        summary["source_id"] = source.get("id", "")
    return summary


def _summarize_destination(
    destination: dict[str, Any], *, index: int, include_ids: bool
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "destination_ref": f"destination_{index}",
        "name": destination.get("name") or destination.get("slug", ""),
        "type": destination.get("type", ""),
        "created_at": destination.get("createdAt", ""),
    }
    if include_ids:
        summary["destination_id"] = destination.get("id", "")
    return summary


def _summarize_model(model: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "model_ref": f"model_{index}",
        "name": model.get("name") or model.get("slug", ""),
        "source": model.get("sourceName") or model.get("sourceId", ""),
        "created_at": model.get("createdAt", ""),
    }
    if include_ids:
        summary["model_id"] = model.get("id", "")
        summary["source_id"] = model.get("sourceId", "")
    return summary


def _summarize_sync(sync: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    schedule: Any = sync.get("schedule") or {}
    schedule_type: Any = (
        cast("dict[str, Any]", schedule).get("type") if isinstance(schedule, dict) else ""
    )
    summary: dict[str, Any] = {
        "sync_ref": f"sync_{index}",
        "name": sync.get("name") or sync.get("slug", ""),
        "destination": sync.get("destinationName") or sync.get("destinationId", ""),
        "model": sync.get("modelName") or sync.get("modelId", ""),
        "schedule": schedule_type,
        "disabled": sync.get("disabled"),
        "last_run_status": sync.get("status") or sync.get("lastRunStatus", ""),
    }
    if include_ids:
        summary["sync_id"] = sync.get("id", "")
        summary["destination_id"] = sync.get("destinationId", "")
        summary["model_id"] = sync.get("modelId", "")
    return summary


def _summarize_sync_run(
    sync_run: dict[str, Any], *, index: int, include_ids: bool
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "run_ref": f"run_{index}",
        "status": sync_run.get("status", ""),
        "started_at": sync_run.get("startedAt") or sync_run.get("createdAt", ""),
        "finished_at": sync_run.get("finishedAt", ""),
        "successful_rows": sync_run.get("successfulRows"),
        "failed_rows": sync_run.get("failedRows"),
        "query_size": sync_run.get("querySize"),
        "error": sync_run.get("error", ""),
    }
    if include_ids:
        summary["run_id"] = sync_run.get("id", "")
        summary["sync_id"] = sync_run.get("syncId", "")
    return summary


@toolset(prefix="hightouch")
class HightouchToolSet:
    """A connector for the Hightouch REST API.

    Args:
        api_key: Workspace API key.
    """

    metadata = ProviderMetadata(
        name="hightouch",
        display_name="Hightouch",
        version="0.1.0",
        description="Sources, models, destinations, syncs, and runs.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://hightouch.com/docs/api-reference/",
        homepage_url="https://hightouch.com/",
        tags=("etl", "reverse-etl", "data-activation"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(api_key),
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
        page: int = 0,
        per_page: int = 25,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List sources (warehouses Hightouch reads from).

        Best first tool for discovering sources. Returns compact summaries
        with ``source_ref``, name, type, and created date. Raw source IDs
        are omitted by default — set ``include_ids=True`` only when a
        follow-up tool needs the raw ``source_id``. Pass ``raw=True`` for
        the unfiltered API response.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        payload: dict[str, Any] = self._client.get(
            "/sources", params={"page": page, "perPage": per_page}
        ).json()
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
        return {"sources": summaries, "next_page": payload.get("nextPage")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_source(self, source_id: Any) -> dict[str, Any]:
        """Return one source's full configuration.

        Returns the raw Hightouch source resource. ``source_id`` may be a
        raw ID string or a source dict from :meth:`list_sources`
        (``include_ids=True``).
        """
        resolved_id = _coerce_id(source_id, "source_id", "id")
        if not resolved_id:
            raise ValueError("source_id is required")
        result: dict[str, Any] = self._client.get(f"/sources/{resolved_id}").json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_destinations(
        self,
        *,
        page: int = 0,
        per_page: int = 25,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List destinations (downstream tools Hightouch writes to).

        Returns compact summaries with ``destination_ref``, name, type, and
        created date. Raw destination IDs are omitted by default — set
        ``include_ids=True`` when a follow-up tool needs the raw
        ``destination_id``. Pass ``raw=True`` for the unfiltered API
        response.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        payload: dict[str, Any] = self._client.get(
            "/destinations",
            params={"page": page, "perPage": per_page},
        ).json()
        if raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, destination in enumerate(items, start=1):
            if isinstance(destination, dict):
                summaries.append(
                    _summarize_destination(
                        cast("dict[str, Any]", destination),
                        index=index,
                        include_ids=include_ids,
                    )
                )
        return {"destinations": summaries, "next_page": payload.get("nextPage")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_models(
        self,
        *,
        page: int = 0,
        per_page: int = 25,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List models (Hightouch's source-side query definitions).

        Returns compact summaries with ``model_ref``, name, the originating
        source name (or ID), and created date. Raw model IDs are omitted
        by default — set ``include_ids=True`` when a follow-up tool needs
        the raw ``model_id``. Pass ``raw=True`` for the unfiltered API
        response.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        payload: dict[str, Any] = self._client.get(
            "/models", params={"page": page, "perPage": per_page}
        ).json()
        if raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, model in enumerate(items, start=1):
            if isinstance(model, dict):
                summaries.append(
                    _summarize_model(
                        cast("dict[str, Any]", model), index=index, include_ids=include_ids
                    )
                )
        return {"models": summaries, "next_page": payload.get("nextPage")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_model(self, model_id: Any) -> dict[str, Any]:
        """Return one model's full definition.

        Returns the raw Hightouch model resource. ``model_id`` may be a raw
        ID string or a model dict from :meth:`list_models`
        (``include_ids=True``).
        """
        resolved_id = _coerce_id(model_id, "model_id", "id")
        if not resolved_id:
            raise ValueError("model_id is required")
        result: dict[str, Any] = self._client.get(f"/models/{resolved_id}").json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_syncs(
        self,
        *,
        page: int = 0,
        per_page: int = 25,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List syncs (model -> destination pipelines).

        Returns compact summaries with ``sync_ref``, name, destination,
        model, schedule type, disabled flag, and last-run status. Raw IDs
        are omitted by default — set ``include_ids=True`` when a follow-up
        tool like :meth:`trigger_sync` or :meth:`list_sync_runs` needs the
        raw ``sync_id``. Pass ``raw=True`` for the unfiltered API response.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        payload: dict[str, Any] = self._client.get(
            "/syncs", params={"page": page, "perPage": per_page}
        ).json()
        if raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, sync in enumerate(items, start=1):
            if isinstance(sync, dict):
                summaries.append(
                    _summarize_sync(
                        cast("dict[str, Any]", sync), index=index, include_ids=include_ids
                    )
                )
        return {"syncs": summaries, "next_page": payload.get("nextPage")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_sync(self, sync_id: Any) -> dict[str, Any]:
        """Return one sync's full configuration.

        Returns the raw Hightouch sync resource. ``sync_id`` may be a raw
        ID string or a sync dict from :meth:`list_syncs`
        (``include_ids=True``).
        """
        resolved_id = _coerce_id(sync_id, "sync_id", "id")
        if not resolved_id:
            raise ValueError("sync_id is required")
        result: dict[str, Any] = self._client.get(f"/syncs/{resolved_id}").json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def trigger_sync(
        self,
        sync_id: Any,
        *,
        full_resync: bool = False,
    ) -> dict[str, Any]:
        """Trigger a sync run.

        Returns the new run resource (with ``id``, ``status``). ``sync_id``
        may be a raw ID or a sync dict from :meth:`list_syncs`
        (``include_ids=True``). ``full_resync=True`` re-emits the full
        dataset rather than the diff and is heavier — confirm with the
        user first if it would generate notable cost.
        """
        resolved_id = _coerce_id(sync_id, "sync_id", "id")
        if not resolved_id:
            raise ValueError("sync_id is required")
        result: dict[str, Any] = self._client.post(
            f"/syncs/{resolved_id}/trigger",
            json={"fullResync": full_resync},
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_sync_runs(
        self,
        sync_id: Any,
        *,
        page: int = 0,
        per_page: int = 25,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List runs for a sync.

        Returns compact summaries with ``run_ref``, status, start/end
        timestamps, successful/failed row counts, and error message. Raw
        run IDs are omitted by default — set ``include_ids=True`` when a
        follow-up tool needs the raw ``run_id``. Pass ``raw=True`` for the
        unfiltered API response.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        resolved_id = _coerce_id(sync_id, "sync_id", "id")
        if not resolved_id:
            raise ValueError("sync_id is required")
        payload: dict[str, Any] = self._client.get(
            f"/syncs/{resolved_id}/runs",
            params={"page": page, "perPage": per_page},
        ).json()
        if raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, run in enumerate(items, start=1):
            if isinstance(run, dict):
                summaries.append(
                    _summarize_sync_run(
                        cast("dict[str, Any]", run), index=index, include_ids=include_ids
                    )
                )
        return {"runs": summaries, "next_page": payload.get("nextPage")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_sync_run(
        self,
        *,
        sync_id: Any,
        run_id: Any,
    ) -> dict[str, Any]:
        """Return one sync run's full details.

        Returns the raw Hightouch sync-run resource. Both ``sync_id`` and
        ``run_id`` may be raw IDs or dicts from the corresponding list
        tools (``include_ids=True``).

        The Hightouch API has no single-run-by-id endpoint; this fetches the
        sync's runs filtered by ``runId`` and returns the matching run.
        """
        resolved_sync_id = _coerce_id(sync_id, "sync_id", "id")
        resolved_run_id = _coerce_id(run_id, "run_id", "id")
        if not resolved_sync_id or not resolved_run_id:
            raise ValueError("sync_id and run_id are required")
        payload: dict[str, Any] = self._client.get(
            f"/syncs/{resolved_sync_id}/runs",
            params={"runId": resolved_run_id},
        ).json()
        items: list[Any] = payload.get("data") or []
        for run in items:
            if isinstance(run, dict):
                run_dict = cast("dict[str, Any]", run)
                if str(run_dict.get("id", "")) == resolved_run_id:
                    return run_dict
        raise ValueError(f"sync run {resolved_run_id} not found for sync {resolved_sync_id}")
