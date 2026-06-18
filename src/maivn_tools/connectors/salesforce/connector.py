"""Salesforce REST API connector.

The connector authenticates with an OAuth-issued bearer token (any of the
supported Salesforce OAuth flows produces one). The caller passes either a
token string, an :class:`OAuth2Token`, or a token callable for refreshable
sessions.

Tools cover the canonical CRUD endpoints and SOQL search. SObject records
are addressed by API name (``Account``, ``Contact``, ``Opportunity``, etc.).
"""

# pyright: strict

from __future__ import annotations

import re
from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.oauth import OAuth2BearerAuth, OAuth2Token, OAuth2TokenProvider
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import (
    DELETE_RECORD_OUTPUT,
    SOQL_QUERY_OUTPUT,
    UPDATE_RECORD_OUTPUT,
)

TokenSource = OAuth2TokenProvider | OAuth2Token | str

_API_VERSION = "v66.0"

_OBJECT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_SUMMARY_FIELD_CANDIDATES: tuple[str, ...] = (
    "Name",
    "Subject",
    "Title",
    "FirstName",
    "LastName",
    "Email",
    "Phone",
    "Status",
    "StageName",
    "Amount",
    "CloseDate",
    "Type",
)


@toolset(prefix="salesforce")
class SalesforceToolSet:
    """A connector for the Salesforce REST API.

    Args:
        instance_url: Salesforce instance URL, e.g.
            ``https://acme.my.salesforce.com``.
        token: OAuth bearer credential.
        api_version: REST API version, defaulting to ``v66.0``.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="salesforce",
        display_name="Salesforce",
        version="0.1.0",
        description="Run SOQL and CRUD operations against Salesforce sObjects.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE, AuthMode.OAUTH2_CLIENT_CREDENTIALS),
        scopes={
            "api": "Read and write Salesforce data through the API.",
            "refresh_token": "Issue and use refresh tokens.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/",
        homepage_url="https://www.salesforce.com",
        tags=("crm", "salesforce"),
    )

    def __init__(
        self,
        *,
        instance_url: str,
        token: TokenSource,
        api_version: str = _API_VERSION,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not instance_url:
            raise ValueError("instance_url is required")
        if not api_version:
            raise ValueError("api_version is required")
        provider = _normalize_token_provider(token)
        self.connection = connection
        self._api_version = api_version
        self._client = HttpClient(
            base_url=instance_url.rstrip("/"),
            auth=OAuth2BearerAuth(provider),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def describe_global(self) -> dict[str, Any]:
        """Return the metadata catalog for the org.

        Returns ``{"sobjects": [{"name": ..., "label": ..., "queryable": ...}]}``
        for every accessible sObject.
        """
        return self._client.get(f"{self._base()}/sobjects").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def describe_object(self, object_name: str) -> dict[str, Any]:
        """Describe one sObject, including its fields.

        Returns the full sObject describe resource. Use ``fields[*]`` to
        learn which columns are queryable before writing SOQL.
        """
        _check_object_name(object_name)
        return self._client.get(f"{self._base()}/sobjects/{object_name}/describe").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SOQL_QUERY_OUTPUT)
    def soql_query(
        self,
        query: str,
        *,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Run a SOQL ``SELECT`` against Salesforce.

        Best first tool for exploring CRM data. Only ``SELECT`` / ``FIND``
        statements are accepted. By default returns compact summaries with
        a stable ``record_ref`` (``record_1``, ``record_2``, ...) plus the
        sObject type and a small set of the most common display fields
        (``Name``, ``Subject``, ``Email``, ``StageName``, ``Amount``, ...)
        that were actually selected. Salesforce ``Id`` values are internal
        handles and are omitted unless ``include_ids=True``. Set
        ``include_metadata=False`` to receive the raw Salesforce response
        including ``nextRecordsUrl`` for pagination.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        stripped = query.strip()
        head = stripped.split(None, 1)[0].lower()
        if head not in {"select", "find"}:
            raise ValueError("soql_query only accepts SELECT or FIND statements")
        payload = self._client.get(
            f"{self._base()}/query",
            params={"q": query},
        ).json()
        if not include_metadata:
            return payload
        return self._summarize_query(payload, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_record(
        self,
        object_name: str,
        record_id: Any,
        *,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return one sObject record by ID.

        ``record_id`` accepts the raw Salesforce ``Id`` string, a record
        dict returned by :meth:`soql_query` (``include_ids=True``), or a
        list of such dicts.
        """
        _check_object_name(object_name)
        resolved = self._extract_record_id(record_id)
        params: dict[str, Any] | None = None
        if fields is not None:
            params = {"fields": ",".join(fields)}
        return self._client.get(
            f"{self._base()}/sobjects/{object_name}/{resolved}",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_record(self, object_name: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Create an sObject record.

        Returns ``{"id": ..., "success": True, "errors": []}``.
        """
        _check_object_name(object_name)
        if not fields:
            raise ValueError("fields must be a non-empty dict")
        return self._client.post(
            f"{self._base()}/sobjects/{object_name}",
            json=fields,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(UPDATE_RECORD_OUTPUT)
    def update_record(
        self,
        object_name: str,
        record_id: Any,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch an sObject record.

        ``record_id`` accepts the raw Salesforce ``Id`` string or a dict/
        list from :meth:`soql_query`.
        """
        _check_object_name(object_name)
        resolved = self._extract_record_id(record_id)
        if not fields:
            raise ValueError("fields must be a non-empty dict")
        response = self._client.patch(
            f"{self._base()}/sobjects/{object_name}/{resolved}",
            json=fields,
        )
        return {"updated": True, "id": resolved, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    @tool_output(DELETE_RECORD_OUTPUT)
    def delete_record(self, object_name: str, record_id: Any) -> dict[str, Any]:
        """Delete an sObject record.

        Destructive: the row is moved to the recycle bin (or destroyed if
        the bin is purged). ``record_id`` accepts the raw Salesforce ``Id``
        string or a dict/list from :meth:`soql_query`.
        """
        _check_object_name(object_name)
        resolved = self._extract_record_id(record_id)
        response = self._client.delete(f"{self._base()}/sobjects/{object_name}/{resolved}")
        return {"deleted": True, "id": resolved, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upsert_record(
        self,
        object_name: str,
        external_field: str,
        external_value: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Upsert a record matched by an external ID field."""
        _check_object_name(object_name)
        _check_object_name(external_field)
        if not external_value or not fields:
            raise ValueError("external_value and fields must be non-empty")
        return self._client.patch(
            f"{self._base()}/sobjects/{object_name}/{external_field}/{external_value}",
            json=fields,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def query_more(self, next_records_url: str) -> dict[str, Any]:
        """Follow ``nextRecordsUrl`` returned by a previous SOQL query.

        Returns the next page of records in the same shape as the original
        ``soql_query(include_metadata=False)`` response.
        """
        if not next_records_url:
            raise ValueError("next_records_url must be a non-empty string")
        return self._client.get(next_records_url).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def query_all(self, query: str) -> dict[str, Any]:
        """Run a SOQL query including soft-deleted records (``queryAll``).

        Returns the raw Salesforce response.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        head = query.strip().split(None, 1)[0].lower()
        if head != "select":
            raise ValueError("query_all only accepts SELECT statements")
        return self._client.get(
            f"{self._base()}/queryAll",
            params={"q": query},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def sosl_search(self, query: str) -> dict[str, Any]:
        """Run a SOSL multi-object search via ``/search``.

        Returns ``{"searchRecords": [...]}``. Each entry has an ``attributes``
        block with ``type`` and ``url``.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        head = query.strip().split(None, 1)[0].lower()
        if head != "find":
            raise ValueError("sosl_search expects a FIND statement")
        return self._client.get(
            f"{self._base()}/search",
            params={"q": query},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_recent_items(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return the user's most recently-viewed records."""
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        return self._client.get(
            f"{self._base()}/recent",
            params={"limit": limit},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_versions(self) -> list[dict[str, Any]]:
        """List API versions exposed by the org."""
        return self._client.get("/services/data/").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_limits(self) -> dict[str, Any]:
        """Return current org limits and usage."""
        return self._client.get(f"{self._base()}/limits").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user_info(self) -> dict[str, Any]:
        """Return profile info for the user the token belongs to."""
        return self._client.get(f"{self._base()}/chatter/users/me").json()

    # MARK: - Reports & dashboards

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_reports(self) -> list[dict[str, Any]]:
        """List analytics reports visible to the user."""
        return self._client.get(f"{self._base()}/analytics/reports").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_report(self, report_id: str) -> dict[str, Any]:
        """Return one report definition by ID."""
        if not report_id:
            raise ValueError("report_id must be a non-empty string")
        return self._client.get(f"{self._base()}/analytics/reports/{report_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def run_report(
        self,
        report_id: str,
        *,
        include_details: bool = True,
    ) -> dict[str, Any]:
        """Execute a report and return its results."""
        if not report_id:
            raise ValueError("report_id must be a non-empty string")
        return self._client.get(
            f"{self._base()}/analytics/reports/{report_id}",
            params={"includeDetails": str(include_details).lower()},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_dashboards(self) -> list[dict[str, Any]]:
        """List analytics dashboards."""
        return self._client.get(f"{self._base()}/analytics/dashboards").json()

    # MARK: - Composite & tooling

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def composite_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a Salesforce ``/composite`` request (multiple sub-requests)."""
        if not payload:
            raise ValueError("payload must be a non-empty dict")
        return self._client.post(
            f"{self._base()}/composite",
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def composite_sobjects_create(
        self,
        records: list[dict[str, Any]],
        *,
        all_or_none: bool = False,
    ) -> dict[str, Any]:
        """Batch-create sObject records (up to 200)."""
        if not records:
            raise ValueError("records must contain at least one record")
        if len(records) > 200:
            raise ValueError("Salesforce composite limits to 200 records per request")
        return self._client.post(
            f"{self._base()}/composite/sobjects",
            json={"allOrNone": all_or_none, "records": records},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def composite_sobjects_update(
        self,
        records: list[dict[str, Any]],
        *,
        all_or_none: bool = False,
    ) -> dict[str, Any]:
        """Batch-update sObject records (each needs ``attributes.type`` and ``Id``)."""
        if not records:
            raise ValueError("records must contain at least one record")
        if len(records) > 200:
            raise ValueError("Salesforce composite limits to 200 records per request")
        return self._client.patch(
            f"{self._base()}/composite/sobjects",
            json={"allOrNone": all_or_none, "records": records},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def composite_sobjects_delete(
        self,
        ids: list[Any],
        *,
        all_or_none: bool = False,
    ) -> dict[str, Any]:
        """Batch-delete sObject records by ID.

        Destructive: rows move to the recycle bin (or are destroyed if it
        is purged). ``ids`` accepts raw ID strings, dicts returned by
        :meth:`soql_query`, or a mixed list.
        """
        if not ids:
            raise ValueError("ids must contain at least one id")
        resolved = [self._extract_record_id(item) for item in ids]
        return self._client.delete(
            f"{self._base()}/composite/sobjects",
            params={"ids": ",".join(resolved), "allOrNone": str(all_or_none).lower()},
        ).json()

    # MARK: - Internal

    def _base(self) -> str:
        return f"/services/data/{self._api_version}"

    @staticmethod
    def _summarize_query(payload: dict[str, Any], *, include_ids: bool) -> dict[str, Any]:
        summaries: list[dict[str, Any]] = []
        records: list[Any] = payload.get("records", []) or []
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                continue
            record_dict = cast(dict[str, Any], record)
            attributes: object = record_dict.get("attributes") or {}
            object_type: Any = (
                cast(dict[str, Any], attributes).get("type", "")
                if isinstance(attributes, dict)
                else ""
            )
            summary: dict[str, Any] = {
                "record_ref": f"record_{index}",
                "object_type": object_type,
            }
            for field in _SUMMARY_FIELD_CANDIDATES:
                if field in record_dict:
                    summary[field] = record_dict[field]
            if include_ids:
                summary["record_id"] = record_dict.get("Id", "")
            summaries.append(summary)
        result: dict[str, Any] = {
            "records": summaries,
            "totalSize": payload.get("totalSize", len(summaries)),
            "done": payload.get("done", True),
        }
        next_records_url: Any = payload.get("nextRecordsUrl")
        if next_records_url:
            result["nextRecordsUrl"] = next_records_url
        return result

    @staticmethod
    def _extract_record_id(candidate: Any) -> str:
        """Pull a Salesforce record ID from an arbitrary value.

        Accepts the raw ``Id`` string, a record dict returned by
        :meth:`soql_query`/:meth:`get_record` (looking up ``Id``,
        ``record_id``, or ``id``), or a list containing such dicts.
        """
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("record_id must be a non-empty string")
            return candidate
        if isinstance(candidate, dict):
            candidate_dict = cast(dict[str, Any], candidate)
            for key in ("Id", "id", "record_id"):
                value: Any = candidate_dict.get(key)
                if isinstance(value, str) and value:
                    return value
        if isinstance(candidate, list | tuple):
            items = cast("list[Any] | tuple[Any, ...]", candidate)
            for item in items:
                try:
                    return SalesforceToolSet._extract_record_id(item)
                except ValueError:
                    continue
        raise ValueError(f"could not extract Salesforce record id from: {candidate!r}")


def _check_object_name(name: str) -> None:
    if not name or not _OBJECT_NAME.fullmatch(name):
        raise ValueError(f"Invalid Salesforce sObject name: {name!r}")


def _normalize_token_provider(token: TokenSource) -> OAuth2TokenProvider:
    # Widen to ``object`` so the str fallback guard is not flagged as
    # unreachable; the runtime contract still validates every input shape.
    value = cast(object, token)
    if callable(value):
        # ``callable`` narrows to ``(...) -> object``; the documented contract
        # is that a callable token IS an ``OAuth2TokenProvider``.
        return cast(OAuth2TokenProvider, value)
    if isinstance(value, OAuth2Token):
        captured: OAuth2Token = value
        return lambda: captured
    if isinstance(value, str):
        if not value:
            raise ValueError("Token string must be non-empty")
        constant = OAuth2Token(access_token=value)
        return lambda: constant
    raise TypeError("Token must be an OAuth2TokenProvider callable, OAuth2Token, or string")
