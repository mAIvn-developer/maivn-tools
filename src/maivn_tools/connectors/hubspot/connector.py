"""HubSpot CRM v3 connector.

Authenticates with a HubSpot private-app access token (recommended) or an
OAuth-issued bearer token. Tools cover the canonical CRM objects: contacts,
companies, deals, and tickets, plus an engagement helper for notes.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

HUBSPOT_API_URL = "https://api.hubapi.com"

_SUPPORTED_OBJECTS = {"contacts", "companies", "deals", "tickets"}
_ENGAGEMENT_TYPES = {"notes", "calls", "emails", "meetings", "tasks"}

_DISPLAY_FIELDS: dict[str, tuple[str, ...]] = {
    "contacts": ("email", "firstname", "lastname", "company", "lifecyclestage"),
    "companies": ("name", "domain", "industry", "country", "lifecyclestage"),
    "deals": ("dealname", "dealstage", "pipeline", "amount", "closedate"),
    "tickets": ("subject", "content", "hs_pipeline_stage", "hs_ticket_priority"),
}


@toolset(prefix="hubspot")
class HubSpotToolSet:
    """A connector for HubSpot CRM.

    Args:
        token: Bearer token (private-app or OAuth access token).
        transport: Optional :class:`HttpTransport` override.
        base_url: Override for tests.
    """

    metadata = ProviderMetadata(
        name="hubspot",
        display_name="HubSpot",
        version="0.1.0",
        description="Search, read, and update HubSpot CRM contacts, companies, deals, and tickets.",
        auth_modes=(AuthMode.BEARER, AuthMode.OAUTH2_AUTH_CODE),
        scopes={
            "crm.objects.contacts.read": "Read contacts.",
            "crm.objects.contacts.write": "Write contacts.",
            "crm.objects.companies.read": "Read companies.",
            "crm.objects.companies.write": "Write companies.",
            "crm.objects.deals.read": "Read deals.",
            "crm.objects.deals.write": "Write deals.",
            "tickets": "Read and write tickets.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developers.hubspot.com/docs/api/crm/understanding-the-crm",
        homepage_url="https://www.hubspot.com",
        tags=("crm", "marketing"),
    )

    def __init__(
        self,
        token: str,
        *,
        transport: HttpTransport | None = None,
        base_url: str = HUBSPOT_API_URL,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not token:
            raise ValueError("token must be a non-empty string")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url,
            auth=BearerTokenAuth(token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_objects(
        self,
        object_type: str,
        *,
        limit: int = 25,
        after: str | None = None,
        properties: list[str] | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List CRM objects of ``object_type`` (contacts/companies/deals/tickets).

        By default returns compact summaries with a stable ``object_ref``
        (``object_1``, ``object_2``, ...) plus a small set of the most
        useful display properties for the object type. Raw HubSpot ``id``
        values are internal handles and are omitted unless
        ``include_ids=True``. Set ``include_metadata=False`` to receive the
        raw HubSpot ``{"results": [...], "paging": {...}}`` payload.
        """
        _check_object_type(object_type)
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if after is not None:
            params["after"] = after
        if properties is not None:
            params["properties"] = ",".join(properties)
        payload = self._client.get(f"/crm/v3/objects/{object_type}", params=params).json()
        if not include_metadata:
            return payload
        return self._summarize_objects(
            payload,
            object_type=object_type,
            include_ids=include_ids,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_object(
        self,
        object_type: str,
        object_id: Any,
        *,
        properties: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return a single CRM object by ID.

        ``object_id`` accepts the raw HubSpot ID string, a dict returned by
        :meth:`list_objects`/:meth:`search_objects` (``include_ids=True``),
        or a list of such dicts.
        """
        _check_object_type(object_type)
        resolved = self._extract_object_id(object_id)
        params: dict[str, Any] | None = None
        if properties is not None:
            params = {"properties": ",".join(properties)}
        return self._client.get(f"/crm/v3/objects/{object_type}/{resolved}", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_objects(
        self,
        object_type: str,
        *,
        filter_groups: list[dict[str, Any]] | None = None,
        query: str | None = None,
        sorts: list[dict[str, str]] | None = None,
        limit: int = 25,
        after: str | None = None,
        properties: list[str] | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Run a HubSpot CRM search across ``object_type``.

        Best first tool for narrowing in on a contact/company/deal/ticket.
        By default returns compact summaries with a stable ``object_ref``
        (``object_1``, ``object_2``, ...) plus a small set of useful display
        properties. Raw HubSpot ``id`` values are internal handles and are
        omitted unless ``include_ids=True``. Set ``include_metadata=False``
        to receive the raw HubSpot payload including paging cursors.
        """
        _check_object_type(object_type)
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        payload_in: dict[str, Any] = {"limit": limit}
        if filter_groups is not None:
            payload_in["filterGroups"] = filter_groups
        if query is not None:
            payload_in["query"] = query
        if sorts is not None:
            payload_in["sorts"] = sorts
        if after is not None:
            payload_in["after"] = after
        if properties is not None:
            payload_in["properties"] = properties
        response = self._client.post(
            f"/crm/v3/objects/{object_type}/search",
            json=payload_in,
        ).json()
        if not include_metadata:
            return response
        return self._summarize_objects(
            response,
            object_type=object_type,
            include_ids=include_ids,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_object(
        self,
        object_type: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a CRM object.

        Returns the new HubSpot object resource (with ``id`` and
        ``properties``).
        """
        _check_object_type(object_type)
        if not properties:
            raise ValueError("properties must be a non-empty dict")
        return self._client.post(
            f"/crm/v3/objects/{object_type}",
            json={"properties": properties},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_object(
        self,
        object_type: str,
        object_id: Any,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch a CRM object's properties.

        ``object_id`` accepts the raw HubSpot ID string or a dict/list from
        :meth:`list_objects`/:meth:`search_objects`.
        """
        _check_object_type(object_type)
        resolved = self._extract_object_id(object_id)
        if not properties:
            raise ValueError("properties must be a non-empty dict")
        return self._client.patch(
            f"/crm/v3/objects/{object_type}/{resolved}",
            json={"properties": properties},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def archive_object(self, object_type: str, object_id: Any) -> dict[str, Any]:
        """Archive (soft-delete) a CRM object.

        Destructive: HubSpot archives the record. Confirm with the user
        first. ``object_id`` accepts the raw HubSpot ID string or a dict/
        list from :meth:`list_objects`/:meth:`search_objects`.
        """
        _check_object_type(object_type)
        resolved = self._extract_object_id(object_id)
        response = self._client.delete(f"/crm/v3/objects/{object_type}/{resolved}")
        return {"archived": True, "id": resolved, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_note(
        self,
        body: str,
        *,
        associations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a HubSpot note engagement, optionally linked to objects.

        Returns the new note resource.
        """
        if not body:
            raise ValueError("body must be a non-empty string")
        payload: dict[str, Any] = {
            "properties": {
                "hs_note_body": body,
                "hs_timestamp": _utc_now_ms(),
            },
        }
        if associations is not None:
            payload["associations"] = associations
        return self._client.post("/crm/v3/objects/notes", json=payload).json()

    # MARK: - Engagements (notes/calls/emails/meetings/tasks)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_engagements(
        self,
        engagement_type: str,
        *,
        limit: int = 25,
        after: str | None = None,
    ) -> dict[str, Any]:
        """List engagements of a given type."""
        _check_engagement_type(engagement_type)
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if after is not None:
            params["after"] = after
        return self._client.get(
            f"/crm/v3/objects/{engagement_type}",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_task(
        self,
        subject: str,
        *,
        body: str | None = None,
        priority: str = "NONE",
        status: str = "NOT_STARTED",
        due_timestamp_ms: int | None = None,
        associations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a task engagement."""
        if not subject:
            raise ValueError("subject must be a non-empty string")
        if priority not in {"NONE", "LOW", "MEDIUM", "HIGH"}:
            raise ValueError("priority must be NONE, LOW, MEDIUM, or HIGH")
        if status not in {"NOT_STARTED", "IN_PROGRESS", "WAITING", "COMPLETED", "DEFERRED"}:
            raise ValueError(
                "status must be NOT_STARTED, IN_PROGRESS, WAITING, COMPLETED, or DEFERRED"
            )
        properties: dict[str, Any] = {
            "hs_task_subject": subject,
            "hs_task_priority": priority,
            "hs_task_status": status,
            "hs_timestamp": _utc_now_ms(),
        }
        if body is not None:
            properties["hs_task_body"] = body
        if due_timestamp_ms is not None:
            properties["hs_task_completion_date"] = due_timestamp_ms
        payload: dict[str, Any] = {"properties": properties}
        if associations is not None:
            payload["associations"] = associations
        return self._client.post("/crm/v3/objects/tasks", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_email_engagement(
        self,
        *,
        subject: str,
        text: str,
        direction: str = "EMAIL",
        timestamp_ms: int | None = None,
        associations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Log an email engagement (does not send mail)."""
        if not subject or not text:
            raise ValueError("subject and text must be non-empty")
        if direction not in {"EMAIL", "INCOMING_EMAIL", "FORWARDED_EMAIL"}:
            raise ValueError("direction must be EMAIL, INCOMING_EMAIL, or FORWARDED_EMAIL")
        properties: dict[str, Any] = {
            "hs_email_subject": subject,
            "hs_email_text": text,
            "hs_email_direction": direction,
            "hs_timestamp": timestamp_ms or _utc_now_ms(),
        }
        payload: dict[str, Any] = {"properties": properties}
        if associations is not None:
            payload["associations"] = associations
        return self._client.post("/crm/v3/objects/emails", json=payload).json()

    # MARK: - Pipelines, owners, properties

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_pipelines(self, object_type: str) -> dict[str, Any]:
        """List pipelines defined for ``object_type`` (e.g. ``deals``, ``tickets``)."""
        _check_object_type(object_type)
        return self._client.get(f"/crm/v3/pipelines/{object_type}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_pipeline(self, object_type: str, pipeline_id: str) -> dict[str, Any]:
        """Return one pipeline definition."""
        _check_object_type(object_type)
        if not pipeline_id:
            raise ValueError("pipeline_id must be a non-empty string")
        return self._client.get(f"/crm/v3/pipelines/{object_type}/{pipeline_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_owners(
        self,
        *,
        email: str | None = None,
        limit: int = 100,
        after: str | None = None,
    ) -> dict[str, Any]:
        """List HubSpot owners (assignable agents)."""
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        params: dict[str, Any] = {"limit": limit}
        if email is not None:
            params["email"] = email
        if after is not None:
            params["after"] = after
        return self._client.get("/crm/v3/owners", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_owner(self, owner_id: str) -> dict[str, Any]:
        """Return a single owner."""
        if not owner_id:
            raise ValueError("owner_id must be a non-empty string")
        return self._client.get(f"/crm/v3/owners/{owner_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_properties(self, object_type: str) -> dict[str, Any]:
        """List property definitions for ``object_type``."""
        _check_object_type(object_type)
        return self._client.get(f"/crm/v3/properties/{object_type}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_property(self, object_type: str, property_name: str) -> dict[str, Any]:
        """Return one property definition."""
        _check_object_type(object_type)
        if not property_name:
            raise ValueError("property_name must be a non-empty string")
        return self._client.get(f"/crm/v3/properties/{object_type}/{property_name}").json()

    # MARK: - Associations & batch

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def associate_objects(
        self,
        *,
        from_object_type: str,
        from_object_id: str,
        to_object_type: str,
        to_object_id: str,
        association_type_id: int | None = None,
        association_category: str = "HUBSPOT_DEFINED",
    ) -> dict[str, Any]:
        """Create an association between two CRM objects (v4 Associations API).

        When ``association_type_id`` is omitted, a default (unlabeled)
        association is created via ``PUT .../associations/default/...``. When
        provided, a labeled association is created with the
        ``{associationCategory, associationTypeId}`` request body. Valid
        ``association_category`` values are ``HUBSPOT_DEFINED``,
        ``USER_DEFINED``, and ``INTEGRATOR_DEFINED``.
        """
        _check_object_type(from_object_type)
        _check_object_type(to_object_type)
        if not from_object_id or not to_object_id:
            raise ValueError("from_object_id and to_object_id must be non-empty")
        if association_type_id is None:
            return self._client.put(
                f"/crm/v4/objects/{from_object_type}/{from_object_id}/associations/default/"
                f"{to_object_type}/{to_object_id}",
                json=None,
            ).json()
        if association_category not in {
            "HUBSPOT_DEFINED",
            "USER_DEFINED",
            "INTEGRATOR_DEFINED",
        }:
            raise ValueError(
                "association_category must be HUBSPOT_DEFINED, USER_DEFINED, or INTEGRATOR_DEFINED"
            )
        return self._client.put(
            f"/crm/v4/objects/{from_object_type}/{from_object_id}/associations/"
            f"{to_object_type}/{to_object_id}",
            json=[
                {
                    "associationCategory": association_category,
                    "associationTypeId": association_type_id,
                }
            ],
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def remove_association(
        self,
        *,
        from_object_type: str,
        from_object_id: str,
        to_object_type: str,
        to_object_id: str,
    ) -> dict[str, Any]:
        """Remove associations between two CRM objects (v4 Associations API).

        Destructive: deletes all associations between the two records,
        regardless of label.
        """
        _check_object_type(from_object_type)
        _check_object_type(to_object_type)
        if not from_object_id or not to_object_id:
            raise ValueError("from_object_id and to_object_id must be non-empty")
        self._client.delete(
            f"/crm/v4/objects/{from_object_type}/{from_object_id}/associations/"
            f"{to_object_type}/{to_object_id}"
        )
        return {"removed": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def batch_read_objects(
        self,
        object_type: str,
        ids: list[Any],
        *,
        properties: list[str] | None = None,
    ) -> dict[str, Any]:
        """Batch-read CRM objects by ID.

        ``ids`` accepts raw HubSpot ID strings, dicts returned by
        :meth:`list_objects`/:meth:`search_objects`, or a mixed list.
        """
        _check_object_type(object_type)
        if not ids:
            raise ValueError("ids must contain at least one id")
        resolved = [self._extract_object_id(item) for item in ids]
        payload: dict[str, Any] = {"inputs": [{"id": i} for i in resolved]}
        if properties is not None:
            payload["properties"] = properties
        return self._client.post(
            f"/crm/v3/objects/{object_type}/batch/read",
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def batch_create_objects(
        self,
        object_type: str,
        inputs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Batch-create CRM objects.

        Each input should be ``{"properties": {...}}``.
        """
        _check_object_type(object_type)
        if not inputs:
            raise ValueError("inputs must contain at least one record")
        return self._client.post(
            f"/crm/v3/objects/{object_type}/batch/create",
            json={"inputs": inputs},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def batch_update_objects(
        self,
        object_type: str,
        inputs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Batch-update CRM objects (each input needs ``id`` and ``properties``)."""
        _check_object_type(object_type)
        if not inputs:
            raise ValueError("inputs must contain at least one record")
        return self._client.post(
            f"/crm/v3/objects/{object_type}/batch/update",
            json={"inputs": inputs},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def batch_archive_objects(
        self,
        object_type: str,
        ids: list[Any],
    ) -> dict[str, Any]:
        """Batch-archive CRM objects by ID.

        Destructive: archives every record listed. ``ids`` accepts raw
        HubSpot ID strings, dicts returned by :meth:`list_objects`/
        :meth:`search_objects`, or a mixed list.
        """
        _check_object_type(object_type)
        if not ids:
            raise ValueError("ids must contain at least one id")
        resolved = [self._extract_object_id(item) for item in ids]
        response = self._client.post(
            f"/crm/v3/objects/{object_type}/batch/archive",
            json={"inputs": [{"id": i} for i in resolved]},
        )
        return {"archived": len(resolved), "status": response.status}

    # MARK: - Internal

    @staticmethod
    def _summarize_objects(
        payload: dict[str, Any],
        *,
        object_type: str,
        include_ids: bool,
    ) -> dict[str, Any]:
        display_fields = _DISPLAY_FIELDS.get(object_type, ())
        summaries: list[dict[str, Any]] = []
        results: Any = payload.get("results", []) or []
        item: Any
        for index, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                continue
            item_dict = cast(dict[str, Any], item)
            properties: dict[str, Any] = item_dict.get("properties") or {}
            summary: dict[str, Any] = {
                "object_ref": f"object_{index}",
                "object_type": object_type,
                "updated_at": item_dict.get("updatedAt", ""),
            }
            for field in display_fields:
                summary[field] = properties.get(field, "")
            if include_ids:
                summary["object_id"] = item_dict.get("id", "")
            summaries.append(summary)
        result: dict[str, Any] = {"objects": summaries}
        if payload.get("paging"):
            result["paging"] = payload["paging"]
        return result

    @staticmethod
    def _extract_object_id(candidate: Any) -> str:
        """Pull a HubSpot object ID from an arbitrary value.

        Accepts the raw ID string, a dict returned by
        :meth:`list_objects`/:meth:`search_objects`/:meth:`get_object`
        (looking up ``object_id`` or ``id``), or a list containing such
        dicts.
        """
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("object_id must be a non-empty string")
            return candidate
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return str(candidate)
        if isinstance(candidate, dict):
            candidate_dict = cast(dict[Any, Any], candidate)
            for key in ("object_id", "id"):
                value: Any = candidate_dict.get(key)
                if isinstance(value, str) and value:
                    return value
                if isinstance(value, int) and not isinstance(value, bool):
                    return str(value)
        if isinstance(candidate, list | tuple):
            candidate_seq = cast("list[Any] | tuple[Any, ...]", candidate)
            for item in candidate_seq:
                try:
                    return HubSpotToolSet._extract_object_id(item)
                except ValueError:
                    continue
        raise ValueError(f"could not extract HubSpot object id from: {candidate!r}")


def _check_object_type(object_type: str) -> None:
    if object_type not in _SUPPORTED_OBJECTS:
        raise ValueError(f"object_type must be one of: {sorted(_SUPPORTED_OBJECTS)!r}")


def _check_engagement_type(engagement_type: str) -> None:
    if engagement_type not in _ENGAGEMENT_TYPES:
        raise ValueError(f"engagement_type must be one of: {sorted(_ENGAGEMENT_TYPES)!r}")


def _utc_now_ms() -> int:
    import time as _time

    return int(_time.time() * 1000)
