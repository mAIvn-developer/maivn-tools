"""Iterable REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Helpers


def _coerce_id(candidate: Any, *, key: str) -> int | str | None:
    """Best-effort lookup of an ID from a dict/list/scalar input."""
    if candidate is None:
        return None
    if isinstance(candidate, int | str):
        return candidate
    if isinstance(candidate, dict):
        mapping = cast(dict[str, Any], candidate)
        for k in (key, "id", "list_id", "campaign_id"):
            value: Any = mapping.get(k)
            if isinstance(value, int | str):
                return value
        return None
    if isinstance(candidate, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in sequence:
            resolved = _coerce_id(item, key=key)
            if resolved is not None:
                return resolved
    return None


# MARK: ToolSet


@toolset(prefix="iterable")
class IterableToolSet:
    """A connector for Iterable's v1 REST API.

    Args:
        api_key: Server-side API key (sent via ``Api-Key`` header).
        base_url: API base URL. Defaults to the US data center
            (``https://api.iterable.com``). EU-region projects must pass
            ``base_url="https://api.eu.iterable.com"``.
    """

    metadata = ProviderMetadata(
        name="iterable",
        display_name="Iterable",
        version="0.1.0",
        description="Users, events, lists, campaigns, and templates.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://api.iterable.com/api/docs",
        homepage_url="https://iterable.com/",
        tags=("marketing", "automation"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.iterable.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="Api-Key"),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_user(
        self,
        *,
        email: str | None = None,
        user_id: str | None = None,
        data_fields: dict[str, Any] | None = None,
        prefer_user_id: bool = True,
        merge_nested_objects: bool = False,
    ) -> dict[str, Any]:
        """Upsert a user profile.

        Either ``email`` or ``user_id`` is required. ``data_fields`` is a
        dict of profile fields to set. Returns the Iterable response
        ``{"code": ..., "msg": ..., "params": ...}``.
        """
        if not email and not user_id:
            raise ValueError("email or user_id is required")
        body: dict[str, Any] = {
            "preferUserId": prefer_user_id,
            "mergeNestedObjects": merge_nested_objects,
        }
        if email is not None:
            body["email"] = email
        if user_id is not None:
            body["userId"] = user_id
        if data_fields is not None:
            body["dataFields"] = data_fields
        return self._client.post("/api/users/update", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self, *, email: str) -> dict[str, Any]:
        """Look up a user by email.

        Returns ``{"user": {"email": ..., "dataFields": {...}, ...}}``.
        Use this before :meth:`update_user` to inspect existing fields.
        """
        if not email:
            raise ValueError("email is required")
        return self._client.get("/api/users/getByEmail", params={"email": email}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_user(self, email: str) -> dict[str, Any]:
        """Delete a user's profile and data.

        Destructive: removes the user profile. Note this is *not* a GDPR
        right-to-be-forgotten operation - Iterable may re-create the profile
        if new data arrives. Use ``POST /api/users/forget`` for a true
        forget. Confirm with the user first. Returns the Iterable status
        response.
        """
        if not email:
            raise ValueError("email is required")
        return self._client.delete(f"/api/users/{email}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def track_event(
        self,
        *,
        email: str | None = None,
        user_id: str | None = None,
        event_name: str,
        data_fields: dict[str, Any] | None = None,
        created_at: int | None = None,
    ) -> dict[str, Any]:
        """Track a custom event for a user.

        Either ``email`` or ``user_id`` is required. ``event_name`` is the
        user-facing event label (e.g. ``"signed_up"``). ``created_at`` is
        a Unix timestamp in seconds; defaults to "now" server-side.
        """
        if not event_name:
            raise ValueError("event_name is required")
        if not email and not user_id:
            raise ValueError("email or user_id is required")
        body: dict[str, Any] = {"eventName": event_name}
        if email is not None:
            body["email"] = email
        if user_id is not None:
            body["userId"] = user_id
        if data_fields is not None:
            body["dataFields"] = data_fields
        if created_at is not None:
            body["createdAt"] = created_at
        return self._client.post("/api/events/track", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def track_purchase(
        self,
        *,
        user: dict[str, Any],
        items: list[dict[str, Any]],
        total: float,
        created_at: int | None = None,
        data_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Track a purchase event.

        ``user`` must contain ``email`` or ``userId``. ``items`` is the
        list of line items (each with ``id``, ``name``, ``price``,
        ``quantity``). ``total`` is the cart total.
        """
        if not user or not items or not total:
            raise ValueError("user, items, and total are required")
        body: dict[str, Any] = {"user": user, "items": items, "total": total}
        if created_at is not None:
            body["createdAt"] = created_at
        if data_fields is not None:
            body["dataFields"] = data_fields
        return self._client.post("/api/commerce/trackPurchase", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_lists(self, *, include_ids: bool = False) -> dict[str, Any]:
        """List static lists.

        Best first tool for finding a list to subscribe users to. Returns
        compact summaries: ``list_ref`` (``list_1``, ``list_2``, ...),
        ``name``, ``list_type``, ``created_at``. Raw numeric IDs are
        omitted by default - they are internal handles. Set
        ``include_ids=True`` when a follow-up tool (e.g. :meth:`add_subscribers`)
        needs the raw ``list_id``.
        """
        payload: Any = self._client.get("/api/lists").json()
        results: list[Any] = (
            cast(list[Any], cast(dict[str, Any], payload).get("lists", []))
            if isinstance(payload, dict)
            else []
        )
        summaries: list[dict[str, Any]] = []
        for index, list_item in enumerate(results, start=1):
            if not isinstance(list_item, dict):
                continue
            entry = cast(dict[str, Any], list_item)
            summary: dict[str, Any] = {
                "list_ref": f"list_{index}",
                "name": entry.get("name", ""),
                "list_type": entry.get("listType", ""),
                "created_at": entry.get("createdAt", ""),
            }
            if include_ids:
                summary["list_id"] = entry.get("id")
            summaries.append(summary)
        return {"lists": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_subscribers(
        self,
        *,
        list_id: Any,
        subscribers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Add users to a list.

        ``list_id`` may be a raw integer ID or a list dict returned by
        :meth:`list_lists` (with ``include_ids=True``). ``subscribers`` is
        a list of user dicts (each must contain ``email`` or ``userId``).
        """
        resolved_id = _coerce_id(list_id, key="list_id")
        if not resolved_id or not subscribers:
            raise ValueError("list_id and subscribers are required")
        return self._client.post(
            "/api/lists/subscribe",
            json={"listId": resolved_id, "subscribers": subscribers},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def remove_subscribers(
        self,
        *,
        list_id: Any,
        subscribers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Remove users from a list.

        Destructive: the users themselves are not deleted, but they are
        removed from the list. ``list_id`` may be a raw integer ID or a
        list dict (with ``include_ids=True``).
        """
        resolved_id = _coerce_id(list_id, key="list_id")
        if not resolved_id or not subscribers:
            raise ValueError("list_id and subscribers are required")
        return self._client.post(
            "/api/lists/unsubscribe",
            json={"listId": resolved_id, "subscribers": subscribers},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_campaigns(self, *, include_ids: bool = False) -> dict[str, Any]:
        """List campaigns.

        Returns compact, human-readable summaries: ``campaign_ref``
        (``campaign_1``, ``campaign_2``, ...), ``name``, ``campaign_state``,
        ``message_medium``, ``send_size``, ``created_at``, ``updated_at``.
        Raw numeric IDs are omitted by default; set ``include_ids=True``
        when a follow-up tool needs the raw ``campaign_id``.
        """
        payload: Any = self._client.get("/api/campaigns").json()
        results: list[Any] = (
            cast(list[Any], cast(dict[str, Any], payload).get("campaigns", []))
            if isinstance(payload, dict)
            else []
        )
        summaries: list[dict[str, Any]] = []
        for index, campaign in enumerate(results, start=1):
            if not isinstance(campaign, dict):
                continue
            entry = cast(dict[str, Any], campaign)
            summary: dict[str, Any] = {
                "campaign_ref": f"campaign_{index}",
                "name": entry.get("name", ""),
                "campaign_state": entry.get("campaignState", ""),
                "message_medium": entry.get("messageMedium", ""),
                "send_size": entry.get("sendSize"),
                "created_at": entry.get("createdAt", ""),
                "updated_at": entry.get("updatedAt", ""),
            }
            if include_ids:
                summary["campaign_id"] = entry.get("id")
                summary["template_id"] = entry.get("templateId")
            summaries.append(summary)
        return {"campaigns": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_templates(
        self,
        *,
        template_type: str | None = None,
        message_medium: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List message templates.

        Returns compact summaries: ``template_ref``, ``name``,
        ``template_type``, ``message_medium``, ``created_at``,
        ``updated_at``. Raw template IDs are omitted by default; set
        ``include_ids=True`` when a follow-up tool needs the raw
        ``template_id``.
        """
        params: dict[str, Any] = {}
        if template_type is not None:
            params["templateType"] = template_type
        if message_medium is not None:
            params["messageMedium"] = message_medium
        payload: Any = self._client.get("/api/templates", params=params or None).json()
        results: list[Any] = (
            cast(list[Any], cast(dict[str, Any], payload).get("templates", []))
            if isinstance(payload, dict)
            else []
        )
        summaries: list[dict[str, Any]] = []
        for index, template in enumerate(results, start=1):
            if not isinstance(template, dict):
                continue
            entry = cast(dict[str, Any], template)
            summary: dict[str, Any] = {
                "template_ref": f"template_{index}",
                "name": entry.get("name", ""),
                "template_type": entry.get("templateType", ""),
                "message_medium": entry.get("messageMedium", ""),
                "created_at": entry.get("createdAt", ""),
                "updated_at": entry.get("updatedAt", ""),
            }
            if include_ids:
                summary["template_id"] = entry.get("templateId")
            summaries.append(summary)
        return {"templates": summaries}
