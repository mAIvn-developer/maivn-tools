"""Sigma Computing REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import (
    LIST_DATASETS_OUTPUT,
    LIST_MEMBERS_OUTPUT,
    LIST_WORKBOOKS_OUTPUT,
)

# MARK: - Module helpers


def _dict_entries(entries: list[object]) -> list[dict[str, Any]]:
    """Keep only the mapping entries from a Sigma list payload."""
    return [cast("dict[str, Any]", item) for item in entries if isinstance(item, dict)]


# MARK: - Tool set


@toolset(prefix="sigma")
class SigmaToolSet:
    """A connector for the Sigma Computing v2 REST API.

    Args:
        access_token: Bearer token issued via OAuth client-credentials.
        base_url: Cloud region URL (e.g.
            ``"https://aws-api.sigmacomputing.com"`` for AWS US;
            ``"https://api.sigmacomputing.com"`` for GCP US).
    """

    metadata = ProviderMetadata(
        name="sigma",
        display_name="Sigma Computing",
        version="0.1.0",
        description="Workbooks, datasets, members, schedules, and embeds.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://help.sigmacomputing.com/reference/get-started-sigma-api",
        homepage_url="https://www.sigmacomputing.com/",
        tags=("bi", "analytics"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        base_url: str = "https://aws-api.sigmacomputing.com",
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

    # MARK: - Internal helpers

    @staticmethod
    def _workbook_summary(
        workbook: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "workbook_ref": f"workbook_{index}",
            "name": workbook.get("name", ""),
            "description": workbook.get("description", "") or "",
            "owner_email": workbook.get("ownerEmail", "") or workbook.get("createdByEmail", ""),
            "updated_at": workbook.get("updatedAt", ""),
        }
        if include_ids:
            summary["workbook_id"] = workbook.get("workbookId", "") or workbook.get("id", "")
        return summary

    @staticmethod
    def _dataset_summary(
        dataset: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "dataset_ref": f"dataset_{index}",
            "name": dataset.get("name", ""),
            "description": dataset.get("description", "") or "",
            "owner_email": dataset.get("ownerEmail", "") or dataset.get("createdByEmail", ""),
            "updated_at": dataset.get("updatedAt", ""),
        }
        if include_ids:
            summary["dataset_id"] = dataset.get("datasetId", "") or dataset.get("id", "")
        return summary

    @staticmethod
    def _member_summary(
        member: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "member_ref": f"member_{index}",
            "name": (member.get("firstName", "") + " " + member.get("lastName", "")).strip()
            or member.get("displayName", ""),
            "email": member.get("email", ""),
            "member_type": member.get("memberType", "") or member.get("type", ""),
            "is_archived": member.get("isArchived", False),
        }
        if include_ids:
            summary["member_id"] = member.get("memberId", "") or member.get("id", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_WORKBOOKS_OUTPUT)
    def list_workbooks(
        self,
        *,
        page: str | None = None,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Sigma workbooks.

        Best first tool for workbook discovery. Returns compact summaries
        with ``workbook_ref``, name, description, owner email, and
        ``updated_at``. Raw Sigma workbook IDs are omitted unless
        ``include_ids=True``; set it only when a follow-up tool
        (:meth:`get_workbook`, :meth:`export_workbook`,
        :meth:`create_embed`) needs the raw ID.

        Sigma cursor-paginates: ``limit`` sets the page size, and ``page``
        must be the ``nextPage`` token string returned by the previous call
        (leave unset for the first page). Iterate until ``nextPage`` is null.
        """
        params: dict[str, Any] = {"limit": limit}
        if page is not None:
            params["page"] = page
        payload: dict[str, Any] = self._client.get("/v2/workbooks", params=params).json()
        entries: object = payload.get("entries")
        if not isinstance(entries, list):
            return payload
        rows: list[object] = cast("list[object]", entries)
        summaries: list[dict[str, Any]] = [
            self._workbook_summary(workbook, index=index, include_ids=include_ids)
            for index, workbook in enumerate(_dict_entries(rows), start=1)
        ]
        return {
            "workbooks": summaries,
            "nextPage": payload.get("nextPage"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_workbook(self, workbook_id: str) -> dict[str, Any]:
        """Return one workbook by ID.

        ``workbook_id`` is the raw Sigma workbook ID returned by
        ``list_workbooks(include_ids=True)``. The ID is an internal handle
        and should not appear in final answers.
        """
        if not workbook_id:
            raise ValueError("workbook_id is required")
        result: dict[str, Any] = self._client.get(f"/v2/workbooks/{workbook_id}").json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def export_workbook(
        self,
        *,
        workbook_id: str,
        format: str,
        element_id: str | None = None,
        parameters: dict[str, Any] | None = None,
        row_limit: int | None = None,
        offset: int | None = None,
        export_as: str | None = None,
    ) -> dict[str, Any]:
        """Trigger a workbook export.

        ``format`` is one of ``csv``/``json``/``jsonl``/``pdf``/``png``/
        ``xlsx``. Returns a payload containing a ``queryId``; retrieve the
        file with ``GET /v2/query/{queryId}/download`` once ready (the
        ``queryId`` expires after 1 hour by default).

        ``row_limit`` and ``offset`` page batched exports beyond 1M rows.
        ``export_as`` selects the member email to apply row-level security
        for. These optional body fields are only sent when provided.
        """
        if not workbook_id or not format:
            raise ValueError("workbook_id and format are required")
        if format not in {"csv", "json", "jsonl", "pdf", "png", "xlsx"}:
            raise ValueError("format must be csv/json/jsonl/pdf/png/xlsx")
        body: dict[str, Any] = {"format": format}
        if element_id is not None:
            body["elementId"] = element_id
        if parameters is not None:
            body["parameters"] = parameters
        if row_limit is not None:
            body["rowLimit"] = row_limit
        if offset is not None:
            body["offset"] = offset
        if export_as is not None:
            body["exportAs"] = export_as
        result: dict[str, Any] = self._client.post(
            f"/v2/workbooks/{workbook_id}/export", json=body
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_DATASETS_OUTPUT)
    def list_datasets(
        self,
        *,
        page: str | None = None,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Sigma datasets.

        Returns compact summaries with ``dataset_ref``, name, description,
        owner email, and ``updated_at``. Raw Sigma dataset IDs are omitted
        unless ``include_ids=True``.

        Sigma cursor-paginates: ``limit`` sets the page size, and ``page``
        must be the ``nextPage`` token string from the previous call (leave
        unset for the first page).

        Deprecated: the ``/v2/datasets`` endpoints are legacy. Datasets can
        no longer be created/edited after 2026-06-02 and stop returning
        usable results after the 2026-09-15 sunset; use data models instead.
        """
        params: dict[str, Any] = {"limit": limit}
        if page is not None:
            params["page"] = page
        payload: dict[str, Any] = self._client.get("/v2/datasets", params=params).json()
        entries: object = payload.get("entries")
        if not isinstance(entries, list):
            return payload
        rows: list[object] = cast("list[object]", entries)
        summaries: list[dict[str, Any]] = [
            self._dataset_summary(dataset, index=index, include_ids=include_ids)
            for index, dataset in enumerate(_dict_entries(rows), start=1)
        ]
        return {
            "datasets": summaries,
            "nextPage": payload.get("nextPage"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        """Return one dataset by ID.

        ``dataset_id`` is the raw Sigma dataset ID. The ID is an internal
        handle and should not appear in final answers.
        """
        if not dataset_id:
            raise ValueError("dataset_id is required")
        result: dict[str, Any] = self._client.get(f"/v2/datasets/{dataset_id}").json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_MEMBERS_OUTPUT)
    def list_members(
        self,
        *,
        page: str | None = None,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Sigma members (org users).

        Returns compact summaries with ``member_ref``, full name, email,
        ``member_type``, and ``is_archived``. Raw Sigma member IDs are
        omitted unless ``include_ids=True``.

        Sigma cursor-paginates: ``limit`` sets the page size, and ``page``
        must be the ``nextPage`` token string from the previous call (leave
        unset for the first page).
        """
        params: dict[str, Any] = {"limit": limit}
        if page is not None:
            params["page"] = page
        payload: dict[str, Any] = self._client.get("/v2/members", params=params).json()
        entries: object = payload.get("entries")
        if not isinstance(entries, list):
            return payload
        rows: list[object] = cast("list[object]", entries)
        summaries: list[dict[str, Any]] = [
            self._member_summary(member, index=index, include_ids=include_ids)
            for index, member in enumerate(_dict_entries(rows), start=1)
        ]
        return {
            "members": summaries,
            "nextPage": payload.get("nextPage"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_schedules(
        self,
        *,
        page: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        """List Sigma scheduled exports.

        Returns the raw Sigma schedule list payload. Sigma cursor-paginates:
        ``limit`` sets the page size, and ``page`` must be the ``nextPage``
        token string from the previous call (leave unset for the first page).
        """
        params: dict[str, Any] = {"limit": limit}
        if page is not None:
            params["page"] = page
        result: dict[str, Any] = self._client.get("/v2/schedules", params=params).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_embed(
        self,
        *,
        workbook_id: str,
        embed_type: str = "secure",
        source_type: str = "workbook",
        source_id: str | None = None,
    ) -> dict[str, Any]:
        """Create an embed for a workbook.

        Calls ``POST /v2/workbooks/{workbook_id}/embeds``. ``embed_type`` is
        one of ``secure``/``public``/``application`` and controls visibility
        and access control. ``source_type`` scopes the embed and is one of
        ``workbook``/``page``/``element``; ``source_id`` is the page or
        element identifier and is required when ``source_type`` is ``page``
        or ``element``. Returns the embed payload.

        For per-user embed-user provisioning, use the JWT-signed embed URL
        flow rather than the deprecated v1 secure Embed-API.
        """
        if not workbook_id:
            raise ValueError("workbook_id is required")
        if source_type not in {"workbook", "page", "element"}:
            raise ValueError("source_type must be workbook/page/element")
        body: dict[str, Any] = {
            "embedType": embed_type,
            "sourceType": source_type,
        }
        if source_id is not None:
            body["sourceId"] = source_id
        result: dict[str, Any] = self._client.post(
            f"/v2/workbooks/{workbook_id}/embeds", json=body
        ).json()
        return result
