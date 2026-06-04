"""NetSuite SuiteTalk REST connector.

NetSuite's REST web services use OAuth 1.0 (TBA) which requires custom
signing. This connector takes an :class:`AuthStrategy` so callers can
plug in their own OAuth1 signer. The default :class:`NoAuth` strategy is
suitable for unit-testing the surface.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.base import AuthStrategy, NoAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

# NetSuite REST endpoints return JSON whose top level may be an object or, in
# error/edge responses, a non-object. Modelling the boundary as this union (a)
# keeps the defensive ``isinstance(payload, dict)`` guards meaningful under
# strict checking and (b) gives ``.get`` a concrete ``dict[str, Any]`` type.
JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None

# MARK: Helpers


def _coerce_id(candidate: Any) -> str | int:
    """Resolve a raw NetSuite record id from a dict/string/int."""
    if isinstance(candidate, str) and candidate:
        return candidate
    if isinstance(candidate, int):
        return candidate
    if isinstance(candidate, dict):
        mapping = cast(dict[str, Any], candidate)
        for key in ("record_id", "id", "internalId"):
            value: Any = mapping.get(key)
            if isinstance(value, str | int) and value:
                return value
        nested_value: Any
        for nested_value in mapping.values():
            if isinstance(nested_value, dict | list | tuple):
                try:
                    return _coerce_id(nested_value)
                except ValueError:
                    continue
    if isinstance(candidate, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        item: Any
        for item in sequence:
            try:
                return _coerce_id(item)
            except ValueError:
                continue
    raise ValueError("could not resolve a NetSuite record id from the given input")


# MARK: ToolSet


@toolset(prefix="netsuite")
class NetSuiteToolSet:
    """A connector for the NetSuite SuiteTalk REST API.

    Plug into an Agent with ``agent.add_toolset(NetSuiteToolSet(
    account_id=..., auth=...))`` and the agent can answer questions about
    customers, invoices, vendors, and other NetSuite records.
    """

    metadata = ProviderMetadata(
        name="netsuite",
        display_name="NetSuite",
        version="0.1.0",
        description="SuiteQL queries, record CRUD across NetSuite REST records.",
        auth_modes=(AuthMode.CUSTOM,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_1540391670.html",
        homepage_url="https://www.netsuite.com/",
        tags=("erp", "accounting", "finance"),
    )

    def __init__(
        self,
        *,
        account_id: str,
        auth: AuthStrategy | None = None,
        base_url: str | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not account_id:
            raise ValueError("account_id is required")
        self.connection = connection
        # Account IDs use '_' in the URL but a dash variant is also accepted.
        host_segment = account_id.lower().replace("_", "-")
        url = base_url or f"https://{host_segment}.suitetalk.api.netsuite.com"
        self._client = HttpClient(
            base_url=url.rstrip("/"),
            auth=auth or NoAuth(),
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
    def suiteql(self, query: str, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        """Run a SuiteQL query (POST to ``/query/v1/suiteql``).

        Returns the raw NetSuite SuiteQL response (``items``, ``count``,
        ``hasMore``, ``links``).
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        result: dict[str, Any] = self._client.post(
            "/services/rest/query/v1/suiteql",
            params={"limit": limit, "offset": offset},
            headers={"Prefer": "transient"},
            json={"q": query},
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_records(
        self,
        record_type: str,
        *,
        limit: int = 25,
        offset: int = 0,
        q: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List records of a NetSuite ``record_type`` (e.g. ``"customer"``).

        Returns compact summaries with ``record_ref`` plus any obvious
        display fields the response includes (``name``, ``entityId``,
        ``email``, ``companyName``). Raw NetSuite ``id`` values are
        omitted unless ``include_ids=True`` (needed for
        :meth:`get_record` / :meth:`update_record` / :meth:`delete_record`).
        """
        if not record_type:
            raise ValueError("record_type must be a non-empty string")
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if q is not None:
            params["q"] = q
        payload: JsonValue = self._client.get(
            f"/services/rest/record/v1/{record_type}",
            params=params,
        ).json()
        items: Any = payload.get("items", []) if isinstance(payload, dict) else []
        summaries: list[dict[str, Any]] = []
        item: Any
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            record = cast(dict[str, Any], item)
            summary: dict[str, Any] = {
                "record_ref": f"{record_type}_{index}",
                "record_type": record_type,
            }
            for display_field in ("entityId", "companyName", "name", "email", "subsidiary"):
                value: Any = record.get(display_field)
                if isinstance(value, str | int | float) and value not in ("", None):
                    summary[display_field] = value
            if include_ids:
                summary["record_id"] = record.get("id", "")
            summaries.append(summary)
        count: Any = None
        if isinstance(payload, dict):
            # Record collections return 'totalResults'; SuiteQL-style payloads
            # use 'count'. Prefer the documented record-collection field.
            count = payload.get("totalResults", payload.get("count"))
        return {
            "records": summaries,
            "record_type": record_type,
            "count": count,
            "has_more": bool(payload.get("hasMore")) if isinstance(payload, dict) else False,
            "offset": payload.get("offset") if isinstance(payload, dict) else None,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_record(self, record_type: str, record_id: str | int) -> dict[str, Any]:
        """Return one NetSuite record by type + id."""
        if not record_type or not record_id:
            raise ValueError("record_type and record_id must be non-empty")
        return self._client.get(
            f"/services/rest/record/v1/{record_type}/{record_id}",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_record(self, record_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a NetSuite record. Returns the new record."""
        if not record_type or not payload:
            raise ValueError("record_type and payload must be non-empty")
        return self._client.post(
            f"/services/rest/record/v1/{record_type}",
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_record(
        self,
        record_type: str,
        record_id: Any,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch a NetSuite record.

        ``record_id`` accepts a raw ID or a dict returned by
        :meth:`list_records` (with ``include_ids=True``) /
        :meth:`get_record`. Returns the updated record.
        """
        resolved = _coerce_id(record_id)
        if not record_type or not payload:
            raise ValueError("record_type and payload must be non-empty")
        return self._client.patch(
            f"/services/rest/record/v1/{record_type}/{resolved}",
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_record(self, record_type: str, record_id: Any) -> dict[str, Any]:
        """Delete a NetSuite record. Destructive — confirm with the user.

        ``record_id`` accepts a raw ID or a dict from list/get tools.
        """
        if not record_type:
            raise ValueError("record_type must be a non-empty string")
        resolved = _coerce_id(record_id)
        self._client.delete(f"/services/rest/record/v1/{record_type}/{resolved}")
        return {"type": record_type, "id": resolved, "deleted": True}
