"""Airtable Web + Meta API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast
from urllib.parse import quote

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="airtable")
class AirtableToolSet:
    """A connector for the Airtable Web + Meta APIs.

    Args:
        access_token: Personal access token (``pat...``) or OAuth bearer
            token.
        base_url: API root (default ``"https://api.airtable.com"``).
    """

    metadata = ProviderMetadata(
        name="airtable",
        display_name="Airtable",
        version="0.1.0",
        description="Bases, tables, records, comments, attachments, and webhooks.",
        auth_modes=(AuthMode.BEARER, AuthMode.OAUTH2_AUTH_CODE),
        scopes={
            "data.records:read": "Read records.",
            "data.records:write": "Create / update / delete records.",
            "data.recordComments:read": "Read record comments.",
            "data.recordComments:write": "Post record comments.",
            "schema.bases:read": "Read base schemas.",
            "schema.bases:write": "Create / modify table schemas.",
            "webhook:manage": "Manage webhooks.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://airtable.com/developers/web/api/introduction",
        homepage_url="https://airtable.com/",
        tags=("database", "productivity", "no-code"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        base_url: str = "https://api.airtable.com",
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

    # MARK: - Meta: bases & schema

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_bases(
        self,
        *,
        offset: str | None = None,
    ) -> dict[str, Any]:
        """List Airtable bases the token can access.

        Returns the raw ``{"bases": [...], "offset": ...}`` payload. Each
        base dict has ``id`` and ``name``; pass the ``id`` to
        :meth:`get_base_schema` or :meth:`list_records`.
        """
        params: dict[str, Any] = {}
        if offset is not None:
            params["offset"] = offset
        return self._client.get(
            "/v0/meta/bases",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_base_schema(
        self,
        base_id: str,
        *,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return a base's table and field schema.

        Returns ``{"tables": [{"id": ..., "name": ..., "fields": [...]}]}``.
        Use this to discover ``table_id`` values before calling
        :meth:`list_records`.
        """
        if not base_id:
            raise ValueError("base_id is required")
        params: dict[str, Any] = {}
        if include is not None:
            params["include"] = include
        return self._client.get(
            f"/v0/meta/bases/{base_id}/tables",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_table(
        self,
        base_id: str,
        *,
        name: str,
        fields: list[dict[str, Any]],
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a table in a base.

        Returns the new table resource (``id``, ``name``, ``fields``).
        """
        if not base_id or not name or not fields:
            raise ValueError("base_id, name, and fields are required")
        body: dict[str, Any] = {"name": name, "fields": fields}
        if description is not None:
            body["description"] = description
        return self._client.post(
            f"/v0/meta/bases/{base_id}/tables",
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_field(
        self,
        *,
        base_id: str,
        table_id: str,
        name: str,
        field_type: str,
        options: dict[str, Any] | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Add a field to a table.

        Returns the new field resource (``id``, ``name``, ``type``).
        """
        if not base_id or not table_id or not name or not field_type:
            raise ValueError("base_id, table_id, name, and field_type are required")
        body: dict[str, Any] = {"name": name, "type": field_type}
        if options is not None:
            body["options"] = options
        if description is not None:
            body["description"] = description
        return self._client.post(
            f"/v0/meta/bases/{base_id}/tables/{table_id}/fields",
            json=body,
        ).json()

    # MARK: - Records

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_records(
        self,
        *,
        base_id: str,
        table_id_or_name: str,
        view: str | None = None,
        fields: list[str] | None = None,
        filter_by_formula: str | None = None,
        sort: list[dict[str, str]] | None = None,
        max_records: int | None = None,
        page_size: int = 100,
        offset: str | None = None,
        cell_format: str = "json",
        time_zone: str | None = None,
        user_locale: str | None = None,
        return_fields_by_field_id: bool = False,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List records in a table.

        Best first tool for record exploration. By default returns compact
        summaries with a stable ``record_ref`` (``record_1``, ``record_2``,
        ...) that is safe to show in final answers, alongside the original
        Airtable ``fields`` dict for each record. Raw Airtable record IDs
        are omitted by default because they are internal handles. Set
        ``include_ids=True`` only when a follow-up tool (:meth:`update_records`,
        :meth:`delete_records`, :meth:`create_comment`) needs the raw
        ``record_id``.

        Set ``include_metadata=False`` to receive the raw Airtable payload
        instead. Pagination is preserved via the ``offset`` cursor.
        """
        if not base_id or not table_id_or_name:
            raise ValueError("base_id and table_id_or_name are required")
        if cell_format not in {"json", "string"}:
            raise ValueError("cell_format must be json or string")
        if cell_format == "string" and (time_zone is None or user_locale is None):
            raise ValueError("time_zone and user_locale are required when cell_format is 'string'")
        params: dict[str, Any] = {
            "pageSize": page_size,
            "cellFormat": cell_format,
            "returnFieldsByFieldId": str(return_fields_by_field_id).lower(),
        }
        if view is not None:
            params["view"] = view
        if fields is not None:
            params["fields[]"] = fields
        if filter_by_formula is not None:
            params["filterByFormula"] = filter_by_formula
        if sort is not None:
            for i, s in enumerate(sort):
                if "field" in s:
                    params[f"sort[{i}][field]"] = s["field"]
                if "direction" in s:
                    params[f"sort[{i}][direction]"] = s["direction"]
        if max_records is not None:
            params["maxRecords"] = max_records
        if offset is not None:
            params["offset"] = offset
        if time_zone is not None:
            params["timeZone"] = time_zone
        if user_locale is not None:
            params["userLocale"] = user_locale
        payload: dict[str, Any] = self._client.get(
            f"/v0/{base_id}/{quote(table_id_or_name, safe='')}",
            params=params,
        ).json()
        if not include_metadata:
            return payload

        raw_records: list[Any] = payload.get("records", []) or []
        summaries: list[dict[str, Any]] = []
        for index, record in enumerate(raw_records, start=1):
            if not isinstance(record, dict):
                continue
            record_dict = cast("dict[str, Any]", record)
            summary: dict[str, Any] = {
                "record_ref": f"record_{index}",
                "fields": record_dict.get("fields") or {},
                "created_time": record_dict.get("createdTime", ""),
            }
            if include_ids:
                summary["record_id"] = record_dict.get("id", "")
            summaries.append(summary)
        result: dict[str, Any] = {"records": summaries}
        if payload.get("offset"):
            result["offset"] = payload["offset"]
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_record(
        self,
        *,
        base_id: str,
        table_id_or_name: str,
        record_id: str,
    ) -> dict[str, Any]:
        """Return one record by ID.

        Returns the raw Airtable record (``id``, ``fields``, ``createdTime``).
        Pass ``record_id`` from a previous :meth:`list_records` call (use
        ``include_ids=True`` to retrieve it).
        """
        if not base_id or not table_id_or_name or not record_id:
            raise ValueError("base_id, table_id_or_name, and record_id are required")
        return self._client.get(
            f"/v0/{base_id}/{quote(table_id_or_name, safe='')}/{record_id}",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_records(
        self,
        *,
        base_id: str,
        table_id_or_name: str,
        records: list[dict[str, Any]],
        typecast: bool = False,
        return_fields_by_field_id: bool = False,
    ) -> dict[str, Any]:
        """Create records (up to 10 per request).

        Each entry in ``records`` must be ``{"fields": {...}}``. Returns the
        Airtable response with created record IDs.
        """
        if not base_id or not table_id_or_name or not records:
            raise ValueError("base_id, table_id_or_name, and records are required")
        if len(records) > 10:
            raise ValueError("Airtable accepts at most 10 records per create call")
        return self._client.post(
            f"/v0/{base_id}/{quote(table_id_or_name, safe='')}",
            json={
                "records": records,
                "typecast": typecast,
                "returnFieldsByFieldId": return_fields_by_field_id,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_records(
        self,
        *,
        base_id: str,
        table_id_or_name: str,
        records: list[dict[str, Any]],
        typecast: bool = False,
        replace: bool = False,
        perform_upsert: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update records.

        Each entry in ``records`` should include the Airtable ``id`` and a
        ``fields`` dict. ``replace=False`` issues a ``PATCH`` (partial
        update); ``True`` issues a ``PUT`` (full replacement).
        ``perform_upsert`` enables Airtable's upsert mode (requires a
        ``fieldsToMergeOn`` key).
        """
        if not base_id or not table_id_or_name or not records:
            raise ValueError("base_id, table_id_or_name, and records are required")
        if len(records) > 10:
            raise ValueError("Airtable accepts at most 10 records per update call")
        body: dict[str, Any] = {"records": records, "typecast": typecast}
        if perform_upsert is not None:
            body["performUpsert"] = perform_upsert
        path = f"/v0/{base_id}/{quote(table_id_or_name, safe='')}"
        response = (
            self._client.put(path, json=body) if replace else self._client.patch(path, json=body)
        )
        return response.json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_records(
        self,
        *,
        base_id: str,
        table_id_or_name: str,
        record_ids: list[Any],
    ) -> dict[str, Any]:
        """Delete records (up to 10 per request).

        Destructive: deletes the records and cannot be undone. ``record_ids``
        accepts raw Airtable IDs (``"rec..."``), full record dicts from
        :meth:`list_records` (``include_ids=True``) or :meth:`get_record`,
        or a mixed list.
        """
        if not base_id or not table_id_or_name or not record_ids:
            raise ValueError("base_id, table_id_or_name, and record_ids are required")
        resolved = [self._extract_record_id(candidate) for candidate in record_ids]
        if len(resolved) > 10:
            raise ValueError("Airtable accepts at most 10 record IDs per delete call")
        return self._client.delete(
            f"/v0/{base_id}/{quote(table_id_or_name, safe='')}",
            params={"records[]": resolved},
        ).json()

    # MARK: - Comments

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_comments(
        self,
        *,
        base_id: str,
        table_id_or_name: str,
        record_id: str,
        page_size: int = 100,
        offset: str | None = None,
    ) -> dict[str, Any]:
        """List comments on a record.

        Returns ``{"comments": [...], "offset": ...}``. Each comment has
        ``id``, ``text``, ``author``, and ``createdTime``.
        """
        if not base_id or not table_id_or_name or not record_id:
            raise ValueError("base_id, table_id_or_name, and record_id are required")
        params: dict[str, Any] = {"pageSize": page_size}
        if offset is not None:
            params["offset"] = offset
        return self._client.get(
            f"/v0/{base_id}/{quote(table_id_or_name, safe='')}/{record_id}/comments",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_comment(
        self,
        *,
        base_id: str,
        table_id_or_name: str,
        record_id: str,
        text: str,
    ) -> dict[str, Any]:
        """Post a comment on a record.

        Returns the new comment resource.
        """
        if not base_id or not table_id_or_name or not record_id or not text:
            raise ValueError("base_id, table_id_or_name, record_id, and text are required")
        return self._client.post(
            f"/v0/{base_id}/{quote(table_id_or_name, safe='')}/{record_id}/comments",
            json={"text": text},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_comment(
        self,
        *,
        base_id: str,
        table_id_or_name: str,
        record_id: str,
        comment_id: str,
    ) -> dict[str, Any]:
        """Delete a comment on a record.

        Destructive: removes the comment permanently. Confirm with the user
        first.
        """
        if not base_id or not table_id_or_name or not record_id or not comment_id:
            raise ValueError("base_id, table_id_or_name, record_id, and comment_id are required")
        response = self._client.delete(
            f"/v0/{base_id}/{quote(table_id_or_name, safe='')}/{record_id}/comments/{comment_id}",
        )
        return {
            "comment_id": comment_id,
            "deleted": True,
            "status": response.status,
        }

    # MARK: - Webhooks

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_webhooks(self, base_id: str) -> dict[str, Any]:
        """List webhooks for a base.

        Returns ``{"webhooks": [{"id": ..., "notificationUrl": ...}]}``.
        """
        if not base_id:
            raise ValueError("base_id is required")
        return self._client.get(
            f"/v0/bases/{base_id}/webhooks",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_webhook(
        self,
        base_id: str,
        *,
        notification_url: str,
        specification: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a webhook.

        Returns the webhook resource including a MAC secret. The secret is
        returned once; persist it before responding.
        """
        if not base_id or not notification_url or not specification:
            raise ValueError("base_id, notification_url, and specification are required")
        return self._client.post(
            f"/v0/bases/{base_id}/webhooks",
            json={
                "notificationUrl": notification_url,
                "specification": specification,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_webhook(
        self,
        *,
        base_id: str,
        webhook_id: str,
    ) -> dict[str, Any]:
        """Delete a webhook.

        Destructive: webhook deliveries stop immediately.
        """
        if not base_id or not webhook_id:
            raise ValueError("base_id and webhook_id are required")
        response = self._client.delete(
            f"/v0/bases/{base_id}/webhooks/{webhook_id}",
        )
        return {
            "webhook_id": webhook_id,
            "deleted": True,
            "status": response.status,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_webhook_payloads(
        self,
        *,
        base_id: str,
        webhook_id: str,
        cursor: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Fetch pending webhook payloads."""
        if not base_id or not webhook_id:
            raise ValueError("base_id and webhook_id are required")
        params: dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        if limit is not None:
            params["limit"] = limit
        return self._client.get(
            f"/v0/bases/{base_id}/webhooks/{webhook_id}/payloads",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_current_user(self) -> dict[str, Any]:
        """Return the authenticated user.

        Returns ``{"id": ..., "email": ..., "scopes": [...]}``. Use to
        verify the token has the required scopes before issuing other
        calls.
        """
        return self._client.get("/v0/meta/whoami").json()

    # MARK: - Internal

    @staticmethod
    def _extract_record_id(candidate: Any) -> str:
        """Pull a record ID from an arbitrary upstream value.

        Accepts a raw ID string (``"rec..."``), a record dict returned by
        :meth:`list_records` (``include_ids=True``) or :meth:`get_record`,
        a one-item list containing either, or any nested dict carrying an
        ``id`` / ``record_id`` field.
        """
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("record id must be a non-empty string")
            return candidate
        if isinstance(candidate, dict):
            candidate_dict = cast("dict[Any, Any]", candidate)
            for key in ("record_id", "id"):
                value: Any = candidate_dict.get(key)
                if isinstance(value, str) and value:
                    return value
            for nested in candidate_dict.values():
                if isinstance(nested, dict):
                    try:
                        return AirtableToolSet._extract_record_id(nested)
                    except ValueError:
                        continue
        if isinstance(candidate, list | tuple):
            candidate_seq = cast("list[Any] | tuple[Any, ...]", candidate)
            for item in candidate_seq:
                try:
                    return AirtableToolSet._extract_record_id(item)
                except ValueError:
                    continue
        raise ValueError(f"could not extract Airtable record id from: {candidate!r}")
