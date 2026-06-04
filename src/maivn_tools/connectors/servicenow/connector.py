"""ServiceNow Table REST API connector."""

# pyright: strict

from __future__ import annotations

import re
from typing import Any, cast

from maivn import toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

_VALID_TABLE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_SUMMARY_FIELD_CANDIDATES: tuple[str, ...] = (
    "number",
    "short_description",
    "state",
    "priority",
    "urgency",
    "assigned_to",
    "assignment_group",
    "category",
    "sys_updated_on",
)


def _validate_table(table: str) -> None:
    if not table:
        raise ValueError("table must be a non-empty string")
    if not _VALID_TABLE.match(table):
        raise ValueError("table must match ^[A-Za-z][A-Za-z0-9_]*$")


@toolset(prefix="servicenow")
class ServiceNowToolSet:
    """A connector for the ServiceNow Now Platform Table API.

    Args:
        instance_url: Full instance URL, e.g. ``https://acme.service-now.com``.
        username: Basic-auth username.
        password: Basic-auth password (or API token).
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="servicenow",
        display_name="ServiceNow",
        version="0.1.0",
        description="Read and write ServiceNow records (incidents, problems, changes, tasks, CIs).",
        auth_modes=(AuthMode.BASIC, AuthMode.OAUTH2_AUTH_CODE),
        scopes={"useraccount": "Access records as the authenticated user."},
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://www.servicenow.com/docs/r/zurich/api-reference/rest-apis/c_TableAPI.html",
        homepage_url="https://www.servicenow.com/",
        tags=("itsm", "ticketing"),
    )

    def __init__(
        self,
        *,
        instance_url: str,
        username: str,
        password: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not instance_url:
            raise ValueError("instance_url is required")
        if not username or not password:
            raise ValueError("username and password are required")
        self.connection = connection
        self._client = HttpClient(
            base_url=instance_url.rstrip("/"),
            auth=BasicAuth(username, password),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Generic table CRUD

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_records(
        self,
        table: str,
        *,
        query: str | None = None,
        fields: list[str] | None = None,
        limit: int = 25,
        offset: int = 0,
        order_by: str | None = None,
        display_value: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List records from a ServiceNow table (e.g. ``"incident"``).

        Best first tool for ServiceNow exploration. By default returns
        compact summaries with a stable ``record_ref`` (``record_1``,
        ``record_2``, ...) plus the user-facing ``number``,
        ``short_description``, ``state``, ``priority``, and update
        timestamp. ServiceNow ``sys_id`` GUIDs are internal handles and are
        omitted unless ``include_ids=True``. Set ``include_metadata=False``
        to receive the raw ServiceNow ``{"result": [...]}`` payload.

        ``limit`` is capped at 1000 as an intentional safety guardrail; the
        Table API documents a maximum page size of 10000.
        """
        _validate_table(table)
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        params: dict[str, Any] = {"sysparm_limit": limit, "sysparm_offset": offset}
        if query is not None:
            params["sysparm_query"] = query
        if fields is not None:
            params["sysparm_fields"] = ",".join(fields)
        if order_by is not None:
            existing = params.get("sysparm_query", "")
            params["sysparm_query"] = (
                f"{existing}^ORDERBY{order_by}" if existing else f"ORDERBY{order_by}"
            )
        if display_value is not None:
            if display_value not in {"true", "false", "all"}:
                raise ValueError("display_value must be true/false/all")
            params["sysparm_display_value"] = display_value
        payload: dict[str, Any] = self._client.get(f"/api/now/table/{table}", params=params).json()
        if not include_metadata:
            return payload
        return self._summarize_records(payload, table=table, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_record(
        self,
        table: str,
        sys_id: Any,
        *,
        fields: list[str] | None = None,
        display_value: str | None = None,
    ) -> dict[str, Any]:
        """Return one record by ``sys_id``.

        ``sys_id`` accepts the raw GUID string, a record dict returned by
        :meth:`list_records` (``include_ids=True``), or a list of such
        dicts.
        """
        _validate_table(table)
        resolved = self._extract_sys_id(sys_id)
        params: dict[str, Any] = {}
        if fields is not None:
            params["sysparm_fields"] = ",".join(fields)
        if display_value is not None:
            params["sysparm_display_value"] = display_value
        return self._client.get(
            f"/api/now/table/{table}/{resolved}",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_record(self, table: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Create a record in a ServiceNow table.

        Returns the new record in the ServiceNow ``{"result": {...}}``
        envelope.
        """
        _validate_table(table)
        if not fields:
            raise ValueError("fields must be a non-empty dict")
        return self._client.post(f"/api/now/table/{table}", json=fields).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_record(
        self,
        table: str,
        sys_id: Any,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch a record.

        ``sys_id`` accepts the raw GUID string or a record dict/list from
        :meth:`list_records`/:meth:`get_record`.
        """
        _validate_table(table)
        resolved = self._extract_sys_id(sys_id)
        if not fields:
            raise ValueError("fields must be a non-empty dict")
        return self._client.patch(f"/api/now/table/{table}/{resolved}", json=fields).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_record(self, table: str, sys_id: Any) -> dict[str, Any]:
        """Delete a record.

        Destructive: row is removed from the table. ``sys_id`` accepts the
        raw GUID string or a record dict/list from :meth:`list_records`/
        :meth:`get_record`.
        """
        _validate_table(table)
        resolved = self._extract_sys_id(sys_id)
        self._client.delete(f"/api/now/table/{table}/{resolved}")
        return {"sys_id": resolved, "deleted": True}

    # MARK: - Incident shortcuts

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_incidents(
        self,
        *,
        query: str | None = None,
        limit: int = 25,
        offset: int = 0,
        fields: list[str] | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List ServiceNow incidents.

        Convenience wrapper around :meth:`list_records` against the
        ``incident`` table. See :meth:`list_records` for the summary
        behavior; ``include_ids`` and ``include_metadata`` are forwarded.
        """
        return self.list_records(
            "incident",
            query=query,
            limit=limit,
            offset=offset,
            fields=fields,
            include_metadata=include_metadata,
            include_ids=include_ids,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_incident(
        self,
        *,
        short_description: str,
        description: str | None = None,
        category: str | None = None,
        urgency: str | None = None,
        impact: str | None = None,
        caller_id: str | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an incident.

        Returns the new incident record in the ServiceNow ``{"result":
        {...}}`` envelope.
        """
        if not short_description:
            raise ValueError("short_description must be a non-empty string")
        fields: dict[str, Any] = {"short_description": short_description}
        if description is not None:
            fields["description"] = description
        if category is not None:
            fields["category"] = category
        if urgency is not None:
            fields["urgency"] = urgency
        if impact is not None:
            fields["impact"] = impact
        if caller_id is not None:
            fields["caller_id"] = caller_id
        if extra_fields is not None:
            fields.update(extra_fields)
        return self.create_record("incident", fields)

    # MARK: - Change request shortcuts

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_change_request(
        self,
        *,
        short_description: str,
        type: str = "normal",
        description: str | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a change request."""
        if not short_description:
            raise ValueError("short_description must be a non-empty string")
        fields: dict[str, Any] = {"short_description": short_description, "type": type}
        if description is not None:
            fields["description"] = description
        if extra_fields is not None:
            fields.update(extra_fields)
        return self.create_record("change_request", fields)

    # MARK: - Aggregation API

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def aggregate(
        self,
        table: str,
        *,
        query: str | None = None,
        group_by: list[str] | None = None,
        count: bool = True,
        avg_fields: list[str] | None = None,
        sum_fields: list[str] | None = None,
        min_fields: list[str] | None = None,
        max_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run a stats/aggregate query."""
        _validate_table(table)
        params: dict[str, Any] = {}
        if query is not None:
            params["sysparm_query"] = query
        if group_by is not None:
            params["sysparm_group_by"] = ",".join(group_by)
        if count:
            params["sysparm_count"] = "true"
        if avg_fields is not None:
            params["sysparm_avg_fields"] = ",".join(avg_fields)
        if sum_fields is not None:
            params["sysparm_sum_fields"] = ",".join(sum_fields)
        if min_fields is not None:
            params["sysparm_min_fields"] = ",".join(min_fields)
        if max_fields is not None:
            params["sysparm_max_fields"] = ",".join(max_fields)
        return self._client.get(
            f"/api/now/stats/{table}",
            params=params or None,
        ).json()

    # MARK: - Attachments

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_attachments(
        self,
        *,
        table: str | None = None,
        sys_id: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List attachments. Filter by record with ``table`` + ``sys_id``."""
        params: dict[str, Any] = {"sysparm_limit": limit}
        filters: list[str] = []
        if table is not None:
            _validate_table(table)
            filters.append(f"table_name={table}")
        if sys_id is not None:
            filters.append(f"table_sys_id={sys_id}")
        if query is not None:
            filters.append(query)
        if filters:
            params["sysparm_query"] = "^".join(filters)
        return self._client.get("/api/now/attachment", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_attachment(self, attachment_sys_id: str) -> dict[str, Any]:
        """Delete an attachment.

        Destructive: cannot be undone.
        """
        if not attachment_sys_id:
            raise ValueError("attachment_sys_id must be a non-empty string")
        self._client.delete(f"/api/now/attachment/{attachment_sys_id}")
        return {"sys_id": attachment_sys_id, "deleted": True}

    # MARK: - User lookup

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def find_user(
        self,
        *,
        email: str | None = None,
        user_name: str | None = None,
    ) -> dict[str, Any]:
        """Look up a user by email or username.

        Returns the summary shape from :meth:`list_records` against the
        ``sys_user`` table.
        """
        if not email and not user_name:
            raise ValueError("email or user_name must be provided")
        filters: list[str] = []
        if email is not None:
            filters.append(f"email={email}")
        if user_name is not None:
            filters.append(f"user_name={user_name}")
        return self.list_records("sys_user", query="^".join(filters), limit=10)

    # MARK: - Internal

    @staticmethod
    def _summarize_records(
        payload: dict[str, Any],
        *,
        table: str,
        include_ids: bool,
    ) -> dict[str, Any]:
        result: object = payload.get("result")
        if not isinstance(result, list):
            return payload
        records = cast("list[Any]", result)
        summaries: list[dict[str, Any]] = []
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                continue
            record_dict = cast("dict[str, Any]", record)
            summary: dict[str, Any] = {
                "record_ref": f"record_{index}",
                "table": table,
            }
            for field in _SUMMARY_FIELD_CANDIDATES:
                if field in record_dict:
                    summary[field] = record_dict[field]
            if include_ids:
                summary["sys_id"] = record_dict.get("sys_id", "")
            summaries.append(summary)
        return {"records": summaries}

    @staticmethod
    def _extract_sys_id(candidate: Any) -> str:
        """Pull a ServiceNow ``sys_id`` from an arbitrary value.

        Accepts the raw GUID string, a record dict returned by
        :meth:`list_records`/:meth:`get_record` (looking up ``sys_id`` or
        ``id``), or a list of such dicts.
        """
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("sys_id must be a non-empty string")
            return candidate
        if isinstance(candidate, dict):
            candidate_dict = cast("dict[Any, Any]", candidate)
            for key in ("sys_id", "id"):
                value: Any = candidate_dict.get(key)
                if isinstance(value, str) and value:
                    return value
        if isinstance(candidate, (list, tuple)):
            candidate_seq = cast("list[Any] | tuple[Any, ...]", candidate)
            for item in candidate_seq:
                try:
                    return ServiceNowToolSet._extract_sys_id(item)
                except ValueError:
                    continue
        raise ValueError(f"could not extract ServiceNow sys_id from: {candidate!r}")
