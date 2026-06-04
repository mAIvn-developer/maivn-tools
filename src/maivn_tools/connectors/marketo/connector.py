"""Marketo REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Helpers


def _coerce_id(candidate: Any, *, key: str) -> Any:
    """Best-effort lookup of an ID from a dict/list/scalar input.

    Returns the candidate itself when it's a scalar (int/str). When given a
    dict, looks up ``key`` and common aliases. When given a list, returns the
    first valid candidate found.
    """
    if candidate is None:
        return None
    if isinstance(candidate, int | str):
        return candidate
    if isinstance(candidate, dict):
        mapping = cast(dict[Any, Any], candidate)
        for k in (key, "id", "campaign_id", "program_id", "list_id"):
            value: Any = mapping.get(k)
            if isinstance(value, int | str):
                return value
        return None
    if isinstance(candidate, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in sequence:
            resolved: Any = _coerce_id(item, key=key)
            if resolved is not None:
                return resolved
    return None


_MAX_LIST_MEMBERSHIP_IDS = 300


def _extract_lead_ids(input: list[dict[str, Any]]) -> list[Any]:
    """Pull lead ids out of a list of lead dicts for list-membership calls.

    Marketo's add/remove list-membership endpoints take lead ids ONLY as
    repeated ``id`` query parameters (ids supplied in a JSON body are
    ignored). Each entry must carry an ``id``. At most 300 ids are accepted
    per call.
    """
    lead_ids: list[Any] = []
    for entry in input:
        lead_id = _coerce_id(entry, key="id")
        if lead_id is None:
            raise ValueError("each lead in input must include an 'id'")
        lead_ids.append(lead_id)
    if not lead_ids:
        raise ValueError("input must contain at least one lead id")
    if len(lead_ids) > _MAX_LIST_MEMBERSHIP_IDS:
        raise ValueError(f"at most {_MAX_LIST_MEMBERSHIP_IDS} leads may be processed per call")
    return lead_ids


# MARK: Tool set


@toolset(prefix="marketo")
class MarketoToolSet:
    """A connector for Marketo's v1 REST API.

    Args:
        munchkin_id: Subscription Munchkin ID (e.g. ``"123-ABC-456"``).
        access_token: OAuth bearer token (obtained via the Identity
            service - the connector does not perform the exchange).
    """

    metadata = ProviderMetadata(
        name="marketo",
        display_name="Marketo",
        version="0.1.0",
        description="Leads, programs, campaigns, lists, and bulk extracts.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developers.marketo.com/rest-api/",
        homepage_url="https://www.marketo.com/",
        tags=("marketing", "automation"),
    )

    def __init__(
        self,
        *,
        munchkin_id: str,
        access_token: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not munchkin_id or not access_token:
            raise ValueError("munchkin_id and access_token are required")
        self.connection = connection
        self._client = HttpClient(
            base_url=f"https://{munchkin_id}.mktorest.com",
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
    def get_lead_by_filter(
        self,
        *,
        filter_type: str,
        filter_values: list[str],
        fields: list[str] | None = None,
        batch_size: int = 300,
        next_page_token: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve leads via a filter (``email``, ``id``, etc.).

        Best first tool to look up leads by a known field. Returns the raw
        Marketo response ``{"result": [...], "requestId": ..., "success":
        bool, "nextPageToken": ...}``. ``filter_values`` is the list of
        values to match. Use ``next_page_token`` from a prior response to
        page through results.
        """
        if not filter_type or not filter_values:
            raise ValueError("filter_type and filter_values are required")
        params: dict[str, Any] = {
            "filterType": filter_type,
            "filterValues": ",".join(filter_values),
            "batchSize": batch_size,
        }
        if fields is not None:
            params["fields"] = ",".join(fields)
        if next_page_token is not None:
            params["nextPageToken"] = next_page_token
        return self._client.get("/rest/v1/leads.json", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_or_update_leads(
        self,
        *,
        action: str,
        input: list[dict[str, Any]],
        lookup_field: str = "email",
    ) -> dict[str, Any]:
        """Create / update leads.

        ``action`` is one of ``createOnly``, ``updateOnly``, ``createOrUpdate``,
        or ``createDuplicate``. ``lookup_field`` (default ``"email"``) selects
        which field Marketo uses to match existing leads. Returns the Marketo
        response with per-lead ``status`` results.
        """
        if not input or not action:
            raise ValueError("action and input are required")
        if action not in {
            "createOnly",
            "updateOnly",
            "createOrUpdate",
            "createDuplicate",
        }:
            raise ValueError("invalid action")
        return self._client.post(
            "/rest/v1/leads.json",
            json={
                "action": action,
                "lookupField": lookup_field,
                "input": input,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_leads(self, ids: list[int]) -> dict[str, Any]:
        """Permanently delete leads by ID.

        Destructive and not reversible. Confirm with the user before calling.
        Returns ``{"requestId": ..., "result": [{"id": ..., "status":
        "deleted"}, ...], "success": bool}``.
        """
        if not ids:
            raise ValueError("ids must be non-empty")
        return self._client.post(
            "/rest/v1/leads/delete.json",
            json={"input": [{"id": i} for i in ids]},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_programs(
        self,
        *,
        max_return: int = 200,
        offset: int = 0,
        status: str | None = None,
        earliest_updated_at: str | None = None,
        latest_updated_at: str | None = None,
    ) -> dict[str, Any]:
        """List programs (campaign containers).

        Returns the raw Marketo response with ``result`` list of program
        records (``id``, ``name``, ``type``, ``status``, ``workspace``).
        Programs group campaigns and assets.

        The Browse Programs asset endpoint supports only ``status`` and an
        ``earliest_updated_at``/``latest_updated_at`` datetime range as
        filters (ISO-8601 datetimes); both bounds must be supplied together
        for the range filter to take effect. ``max_return`` is capped at 200.
        """
        if max_return < 1 or max_return > 200:
            raise ValueError("max_return must be between 1 and 200")
        params: dict[str, Any] = {
            "maxReturn": max_return,
            "offset": offset,
        }
        if status is not None:
            params["status"] = status
        if earliest_updated_at is not None and latest_updated_at is not None:
            params["earliestUpdatedAt"] = earliest_updated_at
            params["latestUpdatedAt"] = latest_updated_at
        return self._client.get("/rest/asset/v1/programs.json", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_campaigns(
        self,
        *,
        program_name: str | None = None,
        is_trigger: bool | None = None,
        batch_size: int = 25,
        next_page_token: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List smart campaigns.

        Best first tool for finding a campaign to trigger. Returns compact,
        human-readable summaries: ``campaign_ref`` (``campaign_1``,
        ``campaign_2``, ...), ``name``, ``program_name``, ``type``,
        ``active``, ``workspace_name``, ``created_at``, ``updated_at``. Raw
        Marketo numeric IDs are omitted by default - they are internal
        handles. Set ``include_ids=True`` only when a follow-up tool (e.g.
        :meth:`trigger_campaign`) needs the raw ``campaign_id``.
        """
        if batch_size < 1 or batch_size > 300:
            raise ValueError("batch_size must be between 1 and 300")
        params: dict[str, Any] = {"batchSize": batch_size}
        if program_name is not None:
            params["programName"] = program_name
        if is_trigger is not None:
            params["isTriggerable"] = str(is_trigger).lower()
        if next_page_token is not None:
            params["nextPageToken"] = next_page_token
        raw: Any = self._client.get("/rest/v1/campaigns.json", params=params).json()
        payload = cast(dict[str, Any], raw) if isinstance(raw, dict) else None
        results: list[Any] = payload.get("result", []) if payload is not None else []
        summaries: list[dict[str, Any]] = []
        for index, campaign in enumerate(results, start=1):
            if not isinstance(campaign, dict):
                continue
            record = cast(dict[Any, Any], campaign)
            summary: dict[str, Any] = {
                "campaign_ref": f"campaign_{index}",
                "name": record.get("name", ""),
                "program_name": record.get("programName", ""),
                "type": record.get("type", ""),
                "active": record.get("active"),
                "workspace_name": record.get("workspaceName", ""),
                "created_at": record.get("createdAt", ""),
                "updated_at": record.get("updatedAt", ""),
            }
            if include_ids:
                summary["campaign_id"] = record.get("id")
                summary["program_id"] = record.get("programId")
            summaries.append(summary)
        return {
            "campaigns": summaries,
            "next_page_token": payload.get("nextPageToken") if payload is not None else None,
            "more_result": payload.get("moreResult") if payload is not None else None,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def trigger_campaign(
        self,
        campaign_id: Any,
        *,
        input: list[dict[str, Any]],
        tokens: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Trigger a smart campaign for given leads.

        ``campaign_id`` may be a raw integer ID, a campaign dict returned by
        :meth:`list_campaigns` (with ``include_ids=True``), or a list of
        such dicts. ``input`` is the list of lead dicts to enroll (each must
        contain at least an ``id``). Optional ``tokens`` override program
        tokens for this run.
        """
        resolved_id = _coerce_id(campaign_id, key="campaign_id")
        if not resolved_id or not input:
            raise ValueError("campaign_id and input are required")
        body: dict[str, Any] = {"input": {"leads": input}}
        if tokens is not None:
            body["input"]["tokens"] = tokens
        return self._client.post(f"/rest/v1/campaigns/{resolved_id}/trigger.json", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_static_lists(
        self,
        *,
        batch_size: int = 25,
        next_page_token: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List static lists in the subscription.

        Returns compact summaries: ``list_ref`` (``list_1``, ``list_2``,
        ...), ``name``, ``program_name``, ``workspace_name``,
        ``computed_url``, ``created_at``, ``updated_at``. Raw numeric IDs
        are omitted by default; set ``include_ids=True`` when a follow-up
        tool needs the raw ``list_id``.
        """
        if batch_size < 1 or batch_size > 300:
            raise ValueError("batch_size must be between 1 and 300")
        params: dict[str, Any] = {"batchSize": batch_size}
        if next_page_token is not None:
            params["nextPageToken"] = next_page_token
        raw: Any = self._client.get("/rest/v1/lists.json", params=params).json()
        payload = cast(dict[str, Any], raw) if isinstance(raw, dict) else None
        results: list[Any] = payload.get("result", []) if payload is not None else []
        summaries: list[dict[str, Any]] = []
        for index, list_item in enumerate(results, start=1):
            if not isinstance(list_item, dict):
                continue
            record = cast(dict[Any, Any], list_item)
            summary: dict[str, Any] = {
                "list_ref": f"list_{index}",
                "name": record.get("name", ""),
                "program_name": record.get("programName", ""),
                "workspace_name": record.get("workspaceName", ""),
                "computed_url": record.get("computedUrl", ""),
                "created_at": record.get("createdAt", ""),
                "updated_at": record.get("updatedAt", ""),
            }
            if include_ids:
                summary["list_id"] = record.get("id")
            summaries.append(summary)
        return {
            "lists": summaries,
            "next_page_token": payload.get("nextPageToken") if payload is not None else None,
            "more_result": payload.get("moreResult") if payload is not None else None,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_leads_to_list(
        self,
        list_id: Any,
        *,
        input: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Add leads to a static list.

        ``list_id`` may be a raw integer ID or a list dict returned by
        :meth:`list_static_lists` (with ``include_ids=True``). ``input`` is
        a list of lead dicts (each must contain at least an ``id``). At most
        300 leads may be added per call.
        """
        resolved_id = _coerce_id(list_id, key="list_id")
        if not resolved_id or not input:
            raise ValueError("list_id and input are required")
        lead_ids = _extract_lead_ids(input)
        return self._client.post(
            f"/rest/v1/lists/{resolved_id}/leads.json",
            params={"id": lead_ids},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def remove_leads_from_list(
        self,
        list_id: Any,
        *,
        input: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Remove leads from a static list.

        Destructive: the leads themselves are not deleted, but they are
        removed from the list. ``list_id`` may be a raw integer ID or a
        list dict (with ``include_ids=True``). At most 300 leads may be
        removed per call.
        """
        resolved_id = _coerce_id(list_id, key="list_id")
        if not resolved_id or not input:
            raise ValueError("list_id and input are required")
        lead_ids = _extract_lead_ids(input)
        return self._client.delete(
            f"/rest/v1/lists/{resolved_id}/leads.json",
            params={"id": lead_ids},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_bulk_lead_export(
        self,
        *,
        fields: list[str],
        filter: dict[str, Any],
        format: str = "CSV",
    ) -> dict[str, Any]:
        """Create a bulk lead-extract job.

        Returns the export-job descriptor (``exportId``, ``status``,
        ``createdAt``). Poll the export status / download endpoints
        separately to retrieve the extract.
        """
        if not fields or not filter:
            raise ValueError("fields and filter are required")
        return self._client.post(
            "/bulk/v1/leads/export/create.json",
            json={"fields": fields, "format": format, "filter": filter},
        ).json()
