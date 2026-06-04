"""Klaviyo API connector (Profiles, Lists, Events, Campaigns, Flows)."""

# pyright: strict

from __future__ import annotations

from typing import Any, TypeGuard, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: - Constants

# Current stable Klaviyo API revision. Klaviyo dates each revision and keeps it
# stable for ~1 year before a deprecation window; new integrations should track
# the latest stable revision. See the versioning & deprecation policy docs.
_API_REVISION = "2025-04-15"


# MARK: - Helpers


def _as_dict(value: Any) -> dict[str, Any]:
    """Return ``value`` if it is a mapping, otherwise an empty dict.

    Used to coerce loosely typed JSON:API fields (``attributes``, ``links``)
    decoded from untyped HTTP responses into a typed mapping.
    """
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _is_mapping(value: Any) -> TypeGuard[dict[str, Any]]:
    """Narrow an untyped JSON:API resource to a typed mapping for summaries."""
    return isinstance(value, dict)


@toolset(prefix="klaviyo")
class KlaviyoToolSet:
    """A connector for the Klaviyo API."""

    metadata = ProviderMetadata(
        name="klaviyo",
        display_name="Klaviyo",
        version="0.1.0",
        description="Profiles, lists, campaigns, flows, and event tracking.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developers.klaviyo.com/en/reference/api_overview",
        homepage_url="https://www.klaviyo.com/",
        tags=("email", "marketing"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        revision: str = _API_REVISION,
        base_url: str = "https://a.klaviyo.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="Authorization", prefix="Klaviyo-API-Key"),
            transport=transport,
            default_headers={
                "Accept": "application/vnd.api+json",
                "Content-Type": "application/vnd.api+json",
                "revision": revision,
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @staticmethod
    def _profile_summary(
        profile: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        attrs = _as_dict(profile.get("attributes") or {})
        first = attrs.get("first_name") or ""
        last = attrs.get("last_name") or ""
        email = attrs.get("email") or ""
        summary: dict[str, Any] = {
            "profile_ref": f"profile_{index}",
            "name": f"{first} {last}".strip() or email,
            "email": email,
            "phone_number": attrs.get("phone_number", ""),
            "subscriptions": attrs.get("subscriptions", {}),
        }
        if include_ids:
            summary["profile_id"] = profile.get("id", "")
        return summary

    @staticmethod
    def _list_summary(
        klist: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        attrs = _as_dict(klist.get("attributes") or {})
        summary: dict[str, Any] = {
            "list_ref": f"list_{index}",
            "name": attrs.get("name", ""),
            "created": attrs.get("created", ""),
        }
        if include_ids:
            summary["list_id"] = klist.get("id", "")
        return summary

    @staticmethod
    def _campaign_summary(
        campaign: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        attrs = _as_dict(campaign.get("attributes") or {})
        summary: dict[str, Any] = {
            "campaign_ref": f"campaign_{index}",
            "name": attrs.get("name", ""),
            "status": attrs.get("status", ""),
            "created_at": attrs.get("created_at", ""),
            "send_time": attrs.get("send_time", ""),
        }
        if include_ids:
            summary["campaign_id"] = campaign.get("id", "")
        return summary

    @staticmethod
    def _flow_summary(
        flow: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        attrs = _as_dict(flow.get("attributes") or {})
        summary: dict[str, Any] = {
            "flow_ref": f"flow_{index}",
            "name": attrs.get("name", ""),
            "status": attrs.get("status", ""),
            "trigger_type": attrs.get("trigger_type", ""),
        }
        if include_ids:
            summary["flow_id"] = flow.get("id", "")
        return summary

    # MARK: - Profiles

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_profiles(
        self,
        *,
        filter: str | None = None,
        sort: str | None = None,
        page_cursor: str | None = None,
        page_size: int = 20,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List profiles using JSON:API filter/sort/cursor syntax.

        Returns compact summaries with ``profile_ref`` plus name, email,
        phone, subscription state. Raw profile IDs are omitted by default
        — set ``include_ids=True`` when ``get_profile`` /
        ``update_profile`` needs them. Filter syntax example:
        ``equals(email,'x@y')``.
        """
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")
        params: dict[str, Any] = {"page[size]": page_size}
        if filter is not None:
            params["filter"] = filter
        if sort is not None:
            params["sort"] = sort
        if page_cursor is not None:
            params["page[cursor]"] = page_cursor
        payload: dict[str, Any] = self._client.get("/api/profiles", params=params).json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries = [
            self._profile_summary(p, index=i, include_ids=include_ids)
            for i, p in enumerate(items, start=1)
            if _is_mapping(p)
        ]
        links = _as_dict(payload.get("links") or {})
        return {
            "profiles": summaries,
            "count": len(summaries),
            "next_cursor": links.get("next"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_profile(self, profile_id: str) -> dict[str, Any]:
        """Return a profile by ID.

        Use after ``list_profiles(include_ids=True)``.
        """
        if not profile_id:
            raise ValueError("profile_id must be a non-empty string")
        return self._client.get(f"/api/profiles/{profile_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_profile(
        self,
        *,
        email: str | None = None,
        phone_number: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a profile.

        Returns the new profile resource (with its server-assigned ID).
        """
        if not email and not phone_number:
            raise ValueError("provide email or phone_number")
        attrs: dict[str, Any] = dict(attributes or {})
        if email is not None:
            attrs["email"] = email
        if phone_number is not None:
            attrs["phone_number"] = phone_number
        return self._client.post(
            "/api/profiles",
            json={"data": {"type": "profile", "attributes": attrs}},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_profile(self, profile_id: str, attributes: dict[str, Any]) -> dict[str, Any]:
        """Patch a profile's attributes.

        Returns the updated profile resource.
        """
        if not profile_id or not attributes:
            raise ValueError("profile_id and attributes must be non-empty")
        return self._client.patch(
            f"/api/profiles/{profile_id}",
            json={
                "data": {
                    "type": "profile",
                    "id": profile_id,
                    "attributes": attributes,
                }
            },
        ).json()

    # MARK: - Lists

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_lists(
        self,
        *,
        page_size: int = 20,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List subscriber lists with compact summaries.

        Returns compact summaries with ``list_ref`` plus name. Raw list
        IDs are omitted by default — set ``include_ids=True`` when
        ``add_profiles_to_list`` / ``remove_profiles_from_list`` needs
        them.
        """
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")
        payload: dict[str, Any] = self._client.get(
            "/api/lists",
            params={"page[size]": page_size},
        ).json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries = [
            self._list_summary(lst, index=i, include_ids=include_ids)
            for i, lst in enumerate(items, start=1)
            if _is_mapping(lst)
        ]
        return {"lists": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_list(self, *, name: str) -> dict[str, Any]:
        """Create a list.

        Returns the new list resource.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        return self._client.post(
            "/api/lists",
            json={"data": {"type": "list", "attributes": {"name": name}}},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_profiles_to_list(self, list_id: str, profile_ids: list[str]) -> dict[str, Any]:
        """Add profiles to a list (subscribes them).

        Returns ``{"list_id": ..., "added": [...], "status": ...}``.
        """
        if not list_id or not profile_ids:
            raise ValueError("list_id and profile_ids must be non-empty")
        response = self._client.post(
            f"/api/lists/{list_id}/relationships/profiles",
            json={"data": [{"type": "profile", "id": pid} for pid in profile_ids]},
        )
        return {"list_id": list_id, "added": profile_ids, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def remove_profiles_from_list(self, list_id: str, profile_ids: list[str]) -> dict[str, Any]:
        """Remove profiles from a list. Destructive — confirm with the user first.

        Unsubscribes the profiles from the list's mailings.
        """
        if not list_id or not profile_ids:
            raise ValueError("list_id and profile_ids must be non-empty")
        response = self._client.delete(
            f"/api/lists/{list_id}/relationships/profiles",
            json={"data": [{"type": "profile", "id": pid} for pid in profile_ids]},
        )
        return {"list_id": list_id, "removed": profile_ids, "status": response.status}

    # MARK: - Events

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def track_event(
        self,
        *,
        metric_name: str,
        profile_email: str | None = None,
        profile_id: str | None = None,
        properties: dict[str, Any] | None = None,
        value: float | None = None,
        time: str | None = None,
    ) -> dict[str, Any]:
        """Send an event to Klaviyo.

        Use to track conversions, page views, custom workflow triggers.
        """
        if not metric_name:
            raise ValueError("metric_name must be a non-empty string")
        if not profile_email and not profile_id:
            raise ValueError("provide profile_email or profile_id")
        profile: dict[str, Any] = {"type": "profile", "attributes": {}}
        if profile_email is not None:
            profile["attributes"]["email"] = profile_email
        if profile_id is not None:
            profile["id"] = profile_id
        attributes: dict[str, Any] = {
            "metric": {"data": {"type": "metric", "attributes": {"name": metric_name}}},
            "profile": {"data": profile},
            "properties": properties if properties is not None else {},
        }
        if value is not None:
            attributes["value"] = value
        if time is not None:
            attributes["time"] = time
        return self._client.post(
            "/api/events",
            json={"data": {"type": "event", "attributes": attributes}},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_metrics(self) -> dict[str, Any]:
        """List metric (event) types.

        Returns the raw Klaviyo payload — each metric has ``id``, ``name``,
        ``integration``.
        """
        return self._client.get("/api/metrics").json()

    # MARK: - Campaigns & flows

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_campaigns(
        self,
        *,
        filter: str | None = None,
        page_size: int = 20,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List campaigns with compact summaries.

        Returns compact summaries with ``campaign_ref`` plus name, status,
        send_time. Klaviyo requires a channel filter — example:
        ``any(messages.channel,['email'])``.
        """
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")
        params: dict[str, Any] = {"page[size]": page_size}
        if filter is not None:
            params["filter"] = filter
        payload: dict[str, Any] = self._client.get("/api/campaigns", params=params).json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries = [
            self._campaign_summary(c, index=i, include_ids=include_ids)
            for i, c in enumerate(items, start=1)
            if _is_mapping(c)
        ]
        return {"campaigns": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        """Return one campaign.

        Use after ``list_campaigns(include_ids=True)``.
        """
        if not campaign_id:
            raise ValueError("campaign_id must be a non-empty string")
        return self._client.get(f"/api/campaigns/{campaign_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_flows(
        self,
        *,
        page_size: int = 20,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List flows (automation sequences) with compact summaries.

        Returns compact summaries with ``flow_ref`` plus name, status,
        trigger_type.
        """
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")
        payload: dict[str, Any] = self._client.get(
            "/api/flows",
            params={"page[size]": page_size},
        ).json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries = [
            self._flow_summary(f, index=i, include_ids=include_ids)
            for i, f in enumerate(items, start=1)
            if _is_mapping(f)
        ]
        return {"flows": summaries, "count": len(summaries)}
