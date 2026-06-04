"""Braze REST API connector."""

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
    """Best-effort lookup of an ID from a dict/list/scalar input."""
    if candidate is None:
        return None
    if isinstance(candidate, int | str):
        return candidate
    if isinstance(candidate, dict):
        mapping = cast(dict[Any, Any], candidate)
        for k in (key, "id", "campaign_id", "canvas_id", "segment_id"):
            value: Any = mapping.get(k)
            if isinstance(value, int | str):
                return value
        return None
    if isinstance(candidate, list | tuple):
        items = cast(list[Any] | tuple[Any, ...], candidate)
        for item in items:
            value = _coerce_id(item, key=key)
            if value is not None:
                return value
    return None


# MARK: ToolSet


@toolset(prefix="braze")
class BrazeToolSet:
    """A connector for Braze's REST API.

    Args:
        rest_endpoint: Workspace REST endpoint, e.g.
            ``"https://rest.iad-01.braze.com"``.
        api_key: REST API key.
    """

    metadata = ProviderMetadata(
        name="braze",
        display_name="Braze",
        version="0.1.0",
        description="Users, events, purchases, campaigns, canvases, and email lists.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://www.braze.com/docs/api/basics/",
        homepage_url="https://www.braze.com/",
        tags=("marketing", "automation"),
    )

    def __init__(
        self,
        *,
        rest_endpoint: str,
        api_key: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not rest_endpoint or not api_key:
            raise ValueError("rest_endpoint and api_key are required")
        self.connection = connection
        self._client = HttpClient(
            base_url=rest_endpoint.rstrip("/"),
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

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def track_users(
        self,
        *,
        attributes: list[dict[str, Any]] | None = None,
        events: list[dict[str, Any]] | None = None,
        purchases: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Track user attributes, events, and purchases (``/users/track``).

        At least one of ``attributes``, ``events``, or ``purchases`` is
        required. Each list element must include an identifier such as
        ``external_id`` or ``user_alias``. Returns the Braze API status
        response.
        """
        if not attributes and not events and not purchases:
            raise ValueError("Provide attributes, events, or purchases")
        body: dict[str, Any] = {}
        if attributes is not None:
            body["attributes"] = attributes
        if events is not None:
            body["events"] = events
        if purchases is not None:
            body["purchases"] = purchases
        return self._client.post("/users/track", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def export_user_ids(
        self,
        *,
        external_ids: list[str] | None = None,
        email_address: str | None = None,
        fields_to_export: list[str] | None = None,
    ) -> dict[str, Any]:
        """Export user profile data by external ID or email.

        At least one of ``external_ids`` or ``email_address`` is
        required, but only one identifier type may be supplied per
        request. ``external_ids`` is the array-based bulk lookup field;
        ``email_address`` is a single email string per Braze's documented
        single-identifier constraint. ``fields_to_export`` limits the
        returned attributes. Returns ``{"users": [...],
        "invalid_user_ids": [...], "message": ...}``.
        """
        if not external_ids and not email_address:
            raise ValueError("external_ids or email_address is required")
        if external_ids and email_address:
            raise ValueError("Provide only one identifier type: external_ids or email_address")
        body: dict[str, Any] = {}
        if external_ids is not None:
            body["external_ids"] = external_ids
        if email_address is not None:
            body["email_address"] = email_address
        if fields_to_export is not None:
            body["fields_to_export"] = fields_to_export
        return self._client.post("/users/export/ids", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_users(
        self,
        *,
        external_ids: list[str] | None = None,
        braze_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Delete users by external or Braze ID.

        Destructive and not reversible (the user profile is removed).
        Confirm with the user first. Exactly one of ``external_ids`` or
        ``braze_ids`` is required; Braze accepts only one identifier type
        per request.
        """
        if not external_ids and not braze_ids:
            raise ValueError("external_ids or braze_ids is required")
        if external_ids and braze_ids:
            raise ValueError("Provide only one identifier type: external_ids or braze_ids")
        body: dict[str, Any] = {}
        if external_ids is not None:
            body["external_ids"] = external_ids
        if braze_ids is not None:
            body["braze_ids"] = braze_ids
        return self._client.post("/users/delete", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def send_messages(
        self,
        *,
        external_user_ids: list[str] | None = None,
        segment_id: str | None = None,
        messages: dict[str, Any] | None = None,
        campaign_id: str | None = None,
        send_id: str | None = None,
    ) -> dict[str, Any]:
        """Send transactional / triggered messages via ``/messages/send``.

        Either ``external_user_ids`` or ``segment_id`` is required, plus
        either ``messages`` (inline message payload) or ``campaign_id``
        (reference an existing campaign). Always confirm message contents
        and recipients before sending.
        """
        if not external_user_ids and not segment_id:
            raise ValueError("external_user_ids or segment_id is required")
        if not messages and not campaign_id:
            raise ValueError("messages or campaign_id is required")
        body: dict[str, Any] = {}
        if external_user_ids is not None:
            body["external_user_ids"] = external_user_ids
        if segment_id is not None:
            body["segment_id"] = segment_id
        if messages is not None:
            body["messages"] = messages
        if campaign_id is not None:
            body["campaign_id"] = campaign_id
        if send_id is not None:
            body["send_id"] = send_id
        return self._client.post("/messages/send", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def trigger_campaign(
        self,
        *,
        campaign_id: Any,
        recipients: list[dict[str, Any]] | None = None,
        broadcast: bool = False,
        trigger_properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Trigger an API-triggered campaign.

        ``campaign_id`` may be a raw string ID or a campaign dict returned
        by :meth:`list_campaigns` (with ``include_ids=True``). When
        ``broadcast=True`` Braze sends to every eligible user in the
        target audience; only use that mode when explicitly intended.
        """
        resolved_id = _coerce_id(campaign_id, key="campaign_id")
        if not resolved_id:
            raise ValueError("campaign_id is required")
        if broadcast and recipients:
            raise ValueError("broadcast=True cannot be combined with a recipients list")
        body: dict[str, Any] = {
            "campaign_id": resolved_id,
            "broadcast": broadcast,
        }
        if recipients is not None:
            body["recipients"] = recipients
        if trigger_properties is not None:
            body["trigger_properties"] = trigger_properties
        return self._client.post("/campaigns/trigger/send", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def trigger_canvas(
        self,
        *,
        canvas_id: Any,
        recipients: list[dict[str, Any]] | None = None,
        broadcast: bool = False,
        canvas_entry_properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Trigger an API-triggered canvas.

        ``canvas_id`` may be a raw string ID or a canvas dict returned by
        :meth:`list_canvases` (with ``include_ids=True``).
        """
        resolved_id = _coerce_id(canvas_id, key="canvas_id")
        if not resolved_id:
            raise ValueError("canvas_id is required")
        if broadcast and recipients:
            raise ValueError("broadcast=True cannot be combined with a recipients list")
        body: dict[str, Any] = {
            "canvas_id": resolved_id,
            "broadcast": broadcast,
        }
        if recipients is not None:
            body["recipients"] = recipients
        if canvas_entry_properties is not None:
            body["canvas_entry_properties"] = canvas_entry_properties
        return self._client.post("/canvas/trigger/send", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_campaigns(
        self,
        *,
        page: int = 0,
        include_archived: bool = False,
        sort_direction: str = "desc",
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List campaigns.

        Best first tool for finding a campaign. Returns compact summaries:
        ``campaign_ref`` (``campaign_1``, ``campaign_2``, ...), ``name``,
        ``is_api_campaign``, ``tags``, ``last_edited``. Raw API IDs are
        omitted by default - they are internal handles. Set
        ``include_ids=True`` when a follow-up tool (e.g.
        :meth:`trigger_campaign`) needs the raw ``campaign_id``.
        """
        raw: Any = self._client.get(
            "/campaigns/list",
            params={
                "page": page,
                "include_archived": str(include_archived).lower(),
                "sort_direction": sort_direction,
            },
        ).json()
        payload: dict[str, Any] | None = (
            cast(dict[str, Any], raw) if isinstance(raw, dict) else None
        )
        results: list[Any] = payload.get("campaigns", []) if payload is not None else []
        summaries: list[dict[str, Any]] = []
        for index, campaign in enumerate(results, start=1):
            if not isinstance(campaign, dict):
                continue
            campaign = cast(dict[str, Any], campaign)
            summary: dict[str, Any] = {
                "campaign_ref": f"campaign_{index}",
                "name": campaign.get("name", ""),
                "is_api_campaign": campaign.get("is_api_campaign"),
                "tags": campaign.get("tags", []),
                "last_edited": campaign.get("last_edited", ""),
            }
            if include_ids:
                summary["campaign_id"] = campaign.get("id")
            summaries.append(summary)
        return {
            "campaigns": summaries,
            "message": payload.get("message") if payload is not None else None,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_canvases(
        self,
        *,
        page: int = 0,
        include_archived: bool = False,
        sort_direction: str = "desc",
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List canvases (multi-step journeys).

        Returns compact summaries: ``canvas_ref``, ``name``, ``tags``,
        ``last_edited``. Raw IDs are omitted by default; set
        ``include_ids=True`` when a follow-up tool needs ``canvas_id``.
        """
        raw: Any = self._client.get(
            "/canvas/list",
            params={
                "page": page,
                "include_archived": str(include_archived).lower(),
                "sort_direction": sort_direction,
            },
        ).json()
        payload: dict[str, Any] | None = (
            cast(dict[str, Any], raw) if isinstance(raw, dict) else None
        )
        results: list[Any] = payload.get("canvases", []) if payload is not None else []
        summaries: list[dict[str, Any]] = []
        for index, canvas in enumerate(results, start=1):
            if not isinstance(canvas, dict):
                continue
            canvas = cast(dict[str, Any], canvas)
            summary: dict[str, Any] = {
                "canvas_ref": f"canvas_{index}",
                "name": canvas.get("name", ""),
                "tags": canvas.get("tags", []),
                "last_edited": canvas.get("last_edited", ""),
            }
            if include_ids:
                summary["canvas_id"] = canvas.get("id")
            summaries.append(summary)
        return {
            "canvases": summaries,
            "message": payload.get("message") if payload is not None else None,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def subscribe_users(
        self,
        *,
        subscription_group_id: str,
        subscription_state: str,
        external_ids: list[str] | None = None,
        email: list[str] | None = None,
        phone: list[str] | None = None,
    ) -> dict[str, Any]:
        """Set subscription-group state for users.

        ``subscription_state`` must be ``"subscribed"`` or
        ``"unsubscribed"``. At least one of ``external_ids``, ``email``,
        or ``phone`` should be provided.
        """
        if not subscription_group_id or not subscription_state:
            raise ValueError("subscription_group_id and subscription_state are required")
        if subscription_state not in {"subscribed", "unsubscribed"}:
            raise ValueError("subscription_state must be subscribed or unsubscribed")
        body: dict[str, Any] = {
            "subscription_group_id": subscription_group_id,
            "subscription_state": subscription_state,
        }
        if external_ids is not None:
            body["external_id"] = external_ids
        if email is not None:
            body["email"] = email
        if phone is not None:
            body["phone"] = phone
        return self._client.post("/subscription/status/set", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def export_segment(
        self,
        *,
        segment_id: str,
        fields_to_export: list[str],
    ) -> dict[str, Any]:
        """Export the users in a segment.

        Returns an export-job descriptor. Long-running segment exports
        return an ``object_prefix`` to poll separately.
        """
        if not segment_id or not fields_to_export:
            raise ValueError("segment_id and fields_to_export are required")
        return self._client.post(
            "/users/export/segment",
            json={
                "segment_id": segment_id,
                "fields_to_export": fields_to_export,
            },
        ).json()
