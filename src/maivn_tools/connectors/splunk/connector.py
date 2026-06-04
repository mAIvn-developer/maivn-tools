"""Splunk Enterprise / Cloud REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

_SUMMARY_MAX = 25


@toolset(prefix="splunk")
class SplunkToolSet:
    """A connector for the Splunk Enterprise / Cloud REST API.

    Args:
        token: Splunk authentication token, sent as
            ``Authorization: Bearer``.
        base_url: Splunkd management URL (e.g.
            ``https://splunk.example.com:8089``).
    """

    metadata = ProviderMetadata(
        name="splunk",
        display_name="Splunk",
        version="0.1.0",
        description="Search, jobs, indexes, saved searches, and HEC ingest.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
            }
        ),
        documentation_url=(
            "https://docs.splunk.com/Documentation/Splunk/latest/RESTREF/RESTprolog"
        ),
        homepage_url="https://www.splunk.com/",
        tags=("observability", "siem"),
    )

    def __init__(
        self,
        *,
        token: str,
        base_url: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not token or not base_url:
            raise ValueError("token and base_url are required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_search_job(
        self,
        *,
        search: str,
        earliest_time: str | None = None,
        latest_time: str | None = None,
        exec_mode: str = "normal",
    ) -> dict[str, Any]:
        """Create a search job.

        Returns the response containing the ``sid`` (search ID). Pass
        that ``sid`` to ``get_search_job`` for status and
        ``get_search_results`` for output. With ``exec_mode="oneshot"``,
        results are returned immediately rather than via a job.
        """
        if not search:
            raise ValueError("search is required")
        if exec_mode not in {"normal", "blocking", "oneshot"}:
            raise ValueError("exec_mode must be normal/blocking/oneshot")
        params: dict[str, Any] = {
            "search": search,
            "exec_mode": exec_mode,
            "output_mode": "json",
        }
        if earliest_time is not None:
            params["earliest_time"] = earliest_time
        if latest_time is not None:
            params["latest_time"] = latest_time
        return self._client.post("/services/search/jobs", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_search_job(self, sid: str) -> dict[str, Any]:
        """Return job status by SID.

        Returns ``entry[].content.dispatchState`` (``QUEUED``, ``RUNNING``,
        ``DONE``, ``FAILED``). Poll until ``DONE`` before calling
        ``get_search_results``.
        """
        if not sid:
            raise ValueError("sid is required")
        return self._client.get(
            f"/services/search/jobs/{sid}",
            params={"output_mode": "json"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_search_results(
        self,
        sid: str,
        *,
        count: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Fetch the results of a completed job.

        Returns ``{"results": [...], "fields": [...]}`` — the rows match
        the SPL of the job that produced them.
        """
        if not sid:
            raise ValueError("sid is required")
        return self._client.get(
            f"/services/search/v2/jobs/{sid}/results",
            params={"output_mode": "json", "count": count, "offset": offset},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def cancel_search_job(self, sid: str) -> dict[str, Any]:
        """Cancel a running job.

        Destructive — the job results cannot be retrieved after cancel.
        """
        if not sid:
            raise ValueError("sid is required")
        return self._client.post(
            f"/services/search/jobs/{sid}/control",
            params={"action": "cancel"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_indexes(
        self,
        *,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List indexes.

        Returns compact summaries by default: ``index_ref``, ``name``,
        ``total_event_count``, ``current_db_size_mb``, ``disabled``. Set
        ``include_metadata=False`` for the raw Splunk response (which
        contains additional fields).
        """
        payload: dict[str, Any] = self._client.get(
            "/services/data/indexes",
            params={"output_mode": "json"},
        ).json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("entry") or []
        summaries: list[dict[str, Any]] = []
        for index, entry in enumerate(items[:_SUMMARY_MAX], start=1):
            if not isinstance(entry, dict):
                continue
            entry_dict = cast("dict[str, Any]", entry)
            content: dict[str, Any] = entry_dict.get("content") or {}
            summaries.append(
                {
                    "index_ref": f"index_{index}",
                    "name": entry_dict.get("name", ""),
                    "total_event_count": content.get("totalEventCount", 0),
                    "current_db_size_mb": content.get("currentDBSizeMB", 0),
                    "disabled": content.get("disabled", False),
                }
            )
        return {"indexes": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_saved_searches(
        self,
        *,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List saved searches.

        Returns compact summaries: ``search_ref``, ``name``, ``search``
        (the SPL), ``is_scheduled``, ``cron_schedule``. Saved search names
        are user-facing — use them for ``update_saved_search``.
        """
        payload: dict[str, Any] = self._client.get(
            "/services/saved/searches",
            params={"output_mode": "json"},
        ).json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("entry") or []
        summaries: list[dict[str, Any]] = []
        for index, entry in enumerate(items[:_SUMMARY_MAX], start=1):
            if not isinstance(entry, dict):
                continue
            entry_dict = cast("dict[str, Any]", entry)
            content: dict[str, Any] = entry_dict.get("content") or {}
            summaries.append(
                {
                    "search_ref": f"search_{index}",
                    "name": entry_dict.get("name", ""),
                    "search": content.get("search", ""),
                    "is_scheduled": content.get("is_scheduled", False),
                    "cron_schedule": content.get("cron_schedule", ""),
                }
            )
        return {"saved_searches": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_saved_search(
        self,
        *,
        name: str,
        search: str,
        is_scheduled: bool = False,
        cron_schedule: str | None = None,
    ) -> dict[str, Any]:
        """Create a saved search.

        Returns the new saved-search entry. Set ``is_scheduled=True`` and
        provide a ``cron_schedule`` (e.g. ``"*/5 * * * *"``) to enable
        scheduled execution.
        """
        if not name or not search:
            raise ValueError("name and search are required")
        params: dict[str, Any] = {
            "name": name,
            "search": search,
            "is_scheduled": "1" if is_scheduled else "0",
            "output_mode": "json",
        }
        if cron_schedule is not None:
            params["cron_schedule"] = cron_schedule
        return self._client.post("/services/saved/searches", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_saved_search(
        self,
        *,
        name: str,
        search: str | None = None,
        cron_schedule: str | None = None,
        is_scheduled: bool | None = None,
    ) -> dict[str, Any]:
        """Update a saved search.

        Patches only the provided fields on the named saved search.
        Returns the updated entry.
        """
        if not name:
            raise ValueError("name is required")
        params: dict[str, Any] = {"output_mode": "json"}
        if search is not None:
            params["search"] = search
        if cron_schedule is not None:
            params["cron_schedule"] = cron_schedule
        if is_scheduled is not None:
            params["is_scheduled"] = "1" if is_scheduled else "0"
        if len(params) == 1:
            raise ValueError("at least one update field is required")
        from urllib.parse import quote

        return self._client.post(
            f"/services/saved/searches/{quote(name, safe='')}",
            params=params,
        ).json()
