"""Customer.io Track + App API v1 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.base import AuthStrategy
from ...auth.basic import BasicAuth
from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import (
    LIST_BROADCASTS_OUTPUT,
    LIST_CAMPAIGNS_OUTPUT,
    LIST_SEGMENTS_OUTPUT,
)


@toolset(prefix="customerio")
class CustomerIOToolSet:
    """A connector for Customer.io Track and App APIs.

    Args:
        track_site_id: Site ID for Track API (basic auth).
        track_api_key: API key for Track API (basic auth password).
        app_api_key: Bearer token for the App / Beta API.
        region: ``"us"`` (default) or ``"eu"``.
    """

    metadata = ProviderMetadata(
        name="customer_io",
        display_name="Customer.io",
        version="0.1.0",
        description="Transactional sends, people, segments, broadcasts, events.",
        auth_modes=(AuthMode.BASIC, AuthMode.BEARER),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://customer.io/docs/api/",
        homepage_url="https://customer.io/",
        tags=("email", "marketing"),
    )

    def __init__(
        self,
        *,
        track_site_id: str | None = None,
        track_api_key: str | None = None,
        app_api_key: str | None = None,
        region: str = "us",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if region not in {"us", "eu"}:
            raise ValueError("region must be 'us' or 'eu'")
        if not app_api_key and not (track_site_id and track_api_key):
            raise ValueError("provide app_api_key or track_site_id+track_api_key")
        self.connection = connection
        self._region = region
        suffix = "" if region == "us" else "-eu"
        self._track_client: HttpClient | None = None
        if track_site_id and track_api_key:
            self._track_client = HttpClient(
                base_url=f"https://track{suffix}.customer.io",
                auth=BasicAuth(track_site_id, track_api_key),
                transport=transport,
                default_headers={"Accept": "application/json"},
            )
        self._app_client: HttpClient | None = None
        if app_api_key:
            self._app_client = HttpClient(
                base_url=f"https://api{suffix}.customer.io",
                auth=BearerTokenAuth(app_api_key),
                transport=transport,
                default_headers={"Accept": "application/json"},
            )

    def _require_track(self) -> HttpClient:
        if self._track_client is None:
            raise RuntimeError("Track API credentials not configured")
        return self._track_client

    def _require_app(self) -> HttpClient:
        if self._app_client is None:
            raise RuntimeError("App API key not configured")
        return self._app_client

    @property
    def track_client(self) -> HttpClient | None:
        return self._track_client

    @property
    def app_client(self) -> HttpClient | None:
        return self._app_client

    @staticmethod
    def _auth_for(client: HttpClient) -> AuthStrategy:
        return client.auth

    @staticmethod
    def _segment_summary(
        segment: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "segment_ref": f"segment_{index}",
            "name": segment.get("name", ""),
            "description": segment.get("description", ""),
            "type": segment.get("type", ""),
            "state": segment.get("state", ""),
        }
        if include_ids:
            summary["segment_id"] = segment.get("id")
        return summary

    @staticmethod
    def _broadcast_summary(
        broadcast: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "broadcast_ref": f"broadcast_{index}",
            "name": broadcast.get("name", ""),
            "state": broadcast.get("state", ""),
            "type": broadcast.get("type", ""),
            "created": broadcast.get("created"),
        }
        if include_ids:
            summary["broadcast_id"] = broadcast.get("id")
        return summary

    @staticmethod
    def _campaign_summary(
        campaign: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "campaign_ref": f"campaign_{index}",
            "name": campaign.get("name", ""),
            "state": campaign.get("state", ""),
            "type": campaign.get("type", ""),
            "created": campaign.get("created"),
        }
        if include_ids:
            summary["campaign_id"] = campaign.get("id")
        return summary

    # MARK: - People (Track API)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def identify(self, customer_id: str, attributes: dict[str, Any]) -> dict[str, Any]:
        """Create or update a person (``PUT /api/v1/customers/{id}``).

        Use to register a user before tracking events. Returns ``{"id":
        ..., "status": <http_status>}``.
        """
        if not customer_id:
            raise ValueError("customer_id must be a non-empty string")
        response = self._require_track().put(
            f"/api/v1/customers/{customer_id}",
            json=attributes or {},
        )
        return {"id": customer_id, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_customer(self, customer_id: str) -> dict[str, Any]:
        """Permanently delete a person and all their events. Destructive — confirm first.

        Unsubscribes the person from all future messages.
        """
        if not customer_id:
            raise ValueError("customer_id must be a non-empty string")
        response = self._require_track().delete(f"/api/v1/customers/{customer_id}")
        return {"id": customer_id, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def track_event(
        self,
        customer_id: str,
        *,
        name: str,
        data: dict[str, Any] | None = None,
        timestamp: int | None = None,
    ) -> dict[str, Any]:
        """Track an event for a person.

        Events drive campaign triggers. ``timestamp`` is Unix seconds.
        """
        if not customer_id or not name:
            raise ValueError("customer_id and name must be non-empty")
        body: dict[str, Any] = {"name": name}
        if data is not None:
            body["data"] = data
        if timestamp is not None:
            body["timestamp"] = timestamp
        response = self._require_track().post(
            f"/api/v1/customers/{customer_id}/events",
            json=body,
        )
        return {"customer_id": customer_id, "name": name, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def track_anonymous_event(
        self,
        *,
        name: str,
        data: dict[str, Any] | None = None,
        anonymous_id: str | None = None,
    ) -> dict[str, Any]:
        """Track an anonymous event (no identified person required).

        Useful for landing-page events before sign-up.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        body: dict[str, Any] = {"name": name}
        if data is not None:
            body["data"] = data
        if anonymous_id is not None:
            body["anonymous_id"] = anonymous_id
        response = self._require_track().post("/api/v1/events", json=body)
        return {"name": name, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def send_transactional(
        self,
        *,
        transactional_message_id: str | int,
        to: str,
        identifiers: dict[str, str],
        message_data: dict[str, Any] | None = None,
        from_address: str | None = None,
        subject: str | None = None,
        body: str | None = None,
    ) -> dict[str, Any]:
        """Send a transactional via the App API. Irreversible once sent.

        Marked destructive because emails cannot be unsent. Always confirm
        recipients with the user first.
        """
        if not to or not identifiers:
            raise ValueError("to and identifiers must be non-empty")
        payload: dict[str, Any] = {
            "transactional_message_id": transactional_message_id,
            "to": to,
            "identifiers": identifiers,
        }
        if message_data is not None:
            payload["message_data"] = message_data
        if from_address is not None:
            payload["from"] = from_address
        if subject is not None:
            payload["subject"] = subject
        if body is not None:
            payload["body"] = body
        return self._require_app().post("/v1/send/email", json=payload).json()

    # MARK: - App API: segments, broadcasts, exports

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_SEGMENTS_OUTPUT)
    def list_segments(
        self,
        *,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List segments with compact summaries (App API).

        Returns compact summaries with ``segment_ref`` plus name, type,
        state. Raw segment IDs are omitted by default.
        """
        payload: dict[str, Any] = self._require_app().get("/v1/segments").json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("segments") or []
        summaries = [
            self._segment_summary(cast("dict[str, Any]", s), index=i, include_ids=include_ids)
            for i, s in enumerate(items, start=1)
            if isinstance(s, dict)
        ]
        return {"segments": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_BROADCASTS_OUTPUT)
    def list_broadcasts(
        self,
        *,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List newsletters / broadcasts with compact summaries (App API).

        Returns compact summaries with ``broadcast_ref`` plus name, state.
        Raw broadcast IDs are omitted by default.
        """
        payload: dict[str, Any] = self._require_app().get("/v1/broadcasts").json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("broadcasts") or []
        summaries = [
            self._broadcast_summary(cast("dict[str, Any]", b), index=i, include_ids=include_ids)
            for i, b in enumerate(items, start=1)
            if isinstance(b, dict)
        ]
        return {"broadcasts": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def trigger_broadcast(
        self,
        broadcast_id: int,
        *,
        ids: list[str] | None = None,
        emails: list[str] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Trigger a broadcast to a list of recipients. Irreversible once sent.

        Marked destructive — every recipient will receive the broadcast
        email. Always confirm with the user first.
        """
        body: dict[str, Any] = {}
        if ids is not None:
            body["ids"] = ids
        if emails is not None:
            body["emails"] = emails
        if data is not None:
            body["data"] = data
        return (
            self._require_app()
            .post(
                f"/v1/campaigns/{broadcast_id}/triggers",
                json=body,
            )
            .json()
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_CAMPAIGNS_OUTPUT)
    def list_campaigns(
        self,
        *,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List campaigns with compact summaries.

        Returns compact summaries with ``campaign_ref`` plus name, state.
        Raw campaign IDs are omitted by default.
        """
        payload: dict[str, Any] = self._require_app().get("/v1/campaigns").json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("campaigns") or []
        summaries = [
            self._campaign_summary(cast("dict[str, Any]", c), index=i, include_ids=include_ids)
            for i, c in enumerate(items, start=1)
            if isinstance(c, dict)
        ]
        return {"campaigns": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_customer(
        self,
        *,
        email: str | None = None,
        customer_id: str | None = None,
    ) -> dict[str, Any]:
        """Look up a customer by ID or email via the App API.

        Email is the user-facing identifier — prefer it. Returns the raw
        Customer.io profile.
        """
        if not email and not customer_id:
            raise ValueError("provide email or customer_id")
        if customer_id is not None:
            return self._require_app().get(f"/v1/customers/{customer_id}/attributes").json()
        assert email is not None
        return (
            self._require_app()
            .get(
                "/v1/customers",
                params={"email": email},
            )
            .json()
        )
