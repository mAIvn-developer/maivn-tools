# pyright: strict
"""Meta Marketing API connector (Facebook / Instagram Ads)."""

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

_API_VERSION = "v25.0"


# MARK: Helpers


def _coerce_id(candidate: Any, *, key: str) -> Any:
    """Best-effort lookup of an ID from a dict/list/scalar input."""
    if candidate is None:
        return None
    if isinstance(candidate, int | str):
        return candidate
    if isinstance(candidate, dict):
        mapping = cast("dict[str, Any]", candidate)
        for k in (key, "id", "campaign_id", "ad_account_id", "ad_id", "adset_id"):
            value: Any = mapping.get(k)
            if isinstance(value, int | str):
                return value
        return None
    if isinstance(candidate, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in sequence:
            value = _coerce_id(item, key=key)
            if value is not None:
                return value
    return None


# MARK: Tool set


@toolset(prefix="meta_ads")
class MetaAdsToolSet:
    """A connector for the Meta Marketing API.

    Args:
        access_token: System-user / ad-account access token.
        graph_version: Graph version (default ``"v25.0"``).
    """

    metadata = ProviderMetadata(
        name="meta_ads",
        display_name="Meta Ads",
        version="0.1.0",
        description="Ad accounts, campaigns, ad sets, ads, audiences, and insights.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url=("https://developers.facebook.com/docs/marketing-apis/"),
        homepage_url="https://www.facebook.com/business/",
        tags=("marketing", "ads", "meta"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        graph_version: str = _API_VERSION,
        base_url: str = "https://graph.facebook.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self.connection = connection
        self._version = graph_version
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(access_token, query_param="access_token"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _path(self, suffix: str) -> str:
        return f"/{self._version}{suffix}"

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_ad_accounts(
        self,
        *,
        user_id: str = "me",
        fields: list[str] | None = None,
        limit: int = 10,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List ad accounts owned / accessible by a user.

        Best first tool for finding an ad account. Returns compact
        summaries: ``account_ref`` (``account_1``, ``account_2``, ...),
        ``name``, ``account_status``, ``currency``, ``timezone_name``,
        ``business_name``. Raw provider IDs are omitted by default - they
        are internal handles (e.g. ``act_123``). Set ``include_ids=True``
        when a follow-up tool (e.g. :meth:`list_campaigns`) needs the raw
        ``ad_account_id``.
        """
        params: dict[str, Any] = {"limit": limit}
        if fields is None:
            fields = [
                "name",
                "account_status",
                "currency",
                "timezone_name",
                "business_name",
            ]
        params["fields"] = ",".join(fields)
        raw: Any = self._client.get(self._path(f"/{user_id}/adaccounts"), params=params).json()
        payload: dict[str, Any] = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
        results: list[Any] = payload.get("data", [])
        summaries: list[dict[str, Any]] = []
        for index, account in enumerate(results, start=1):
            if not isinstance(account, dict):
                continue
            account_data = cast("dict[str, Any]", account)
            summary: dict[str, Any] = {
                "account_ref": f"account_{index}",
                "name": account_data.get("name", ""),
                "account_status": account_data.get("account_status"),
                "currency": account_data.get("currency", ""),
                "timezone_name": account_data.get("timezone_name", ""),
                "business_name": account_data.get("business_name", ""),
            }
            if include_ids:
                summary["ad_account_id"] = account_data.get("id", "")
            summaries.append(summary)
        return {
            "accounts": summaries,
            "paging": payload.get("paging"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_ad_account(
        self,
        ad_account_id: Any,
        *,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return one ad account's raw record.

        Accepts a raw account ID string (e.g. ``"act_123"``) or an
        account dict returned by :meth:`list_ad_accounts` (with
        ``include_ids=True``).
        """
        resolved_id = _coerce_id(ad_account_id, key="ad_account_id")
        if not resolved_id:
            raise ValueError("ad_account_id is required")
        params: dict[str, Any] = {}
        if fields is not None:
            params["fields"] = ",".join(fields)
        return self._client.get(self._path(f"/{resolved_id}"), params=params or None).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_campaigns(
        self,
        ad_account_id: Any,
        *,
        fields: list[str] | None = None,
        limit: int = 10,
        effective_status: list[str] | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List campaigns in an ad account.

        Best first tool for finding a campaign to pause / update.
        Returns compact summaries: ``campaign_ref``, ``name``,
        ``status``, ``effective_status``, ``objective``, ``daily_budget``,
        ``lifetime_budget``, ``start_time``, ``stop_time``. Raw IDs are
        omitted by default; set ``include_ids=True`` when a follow-up
        tool (:meth:`update_campaign`, :meth:`delete_campaign`) needs the
        raw ``campaign_id``.
        """
        account = _coerce_id(ad_account_id, key="ad_account_id")
        if not account:
            raise ValueError("ad_account_id is required")
        params: dict[str, Any] = {"limit": limit}
        if fields is None:
            fields = [
                "name",
                "status",
                "effective_status",
                "objective",
                "daily_budget",
                "lifetime_budget",
                "start_time",
                "stop_time",
            ]
        params["fields"] = ",".join(fields)
        if effective_status is not None:
            params["effective_status"] = effective_status
        raw: Any = self._client.get(self._path(f"/{account}/campaigns"), params=params).json()
        payload: dict[str, Any] = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
        results: list[Any] = payload.get("data", [])
        summaries: list[dict[str, Any]] = []
        for index, campaign in enumerate(results, start=1):
            if not isinstance(campaign, dict):
                continue
            campaign_data = cast("dict[str, Any]", campaign)
            summary: dict[str, Any] = {
                "campaign_ref": f"campaign_{index}",
                "name": campaign_data.get("name", ""),
                "status": campaign_data.get("status", ""),
                "effective_status": campaign_data.get("effective_status", ""),
                "objective": campaign_data.get("objective", ""),
                "daily_budget": campaign_data.get("daily_budget"),
                "lifetime_budget": campaign_data.get("lifetime_budget"),
                "start_time": campaign_data.get("start_time", ""),
                "stop_time": campaign_data.get("stop_time", ""),
            }
            if include_ids:
                summary["campaign_id"] = campaign_data.get("id", "")
            summaries.append(summary)
        return {
            "campaigns": summaries,
            "paging": payload.get("paging"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_campaign(
        self,
        ad_account_id: Any,
        *,
        name: str,
        objective: str,
        status: str = "PAUSED",
        special_ad_categories: list[str] | None = None,
        daily_budget: int | None = None,
        lifetime_budget: int | None = None,
    ) -> dict[str, Any]:
        """Create a campaign.

        ``status`` defaults to ``"PAUSED"`` so newly created campaigns
        don't immediately spend. Switch to ``"ACTIVE"`` only after
        confirming budget, objective, and creative are correct.
        """
        account = _coerce_id(ad_account_id, key="ad_account_id")
        if not account or not name or not objective:
            raise ValueError("ad_account_id, name, and objective are required")
        if status not in {"ACTIVE", "PAUSED", "ARCHIVED", "DELETED"}:
            raise ValueError("invalid status")
        body: dict[str, Any] = {
            "name": name,
            "objective": objective,
            "status": status,
            "special_ad_categories": special_ad_categories or [],
        }
        if daily_budget is not None:
            body["daily_budget"] = daily_budget
        if lifetime_budget is not None:
            body["lifetime_budget"] = lifetime_budget
        return self._client.post(self._path(f"/{account}/campaigns"), params=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_campaign(
        self,
        campaign_id: Any,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a campaign.

        ``campaign_id`` may be the raw ID or a campaign dict returned by
        :meth:`list_campaigns` (with ``include_ids=True``). ``fields`` is a
        partial-update dict (e.g. ``{"status": "PAUSED"}`` to pause).
        """
        resolved_id = _coerce_id(campaign_id, key="campaign_id")
        if not resolved_id or not fields:
            raise ValueError("campaign_id and fields are required")
        return self._client.post(self._path(f"/{resolved_id}"), params=fields).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_campaign(self, campaign_id: Any) -> dict[str, Any]:
        """Archive (delete) a campaign.

        Destructive: Meta soft-archives the campaign and it stops
        serving. Confirm with the user first. Accepts a raw ID or a
        campaign dict (with ``include_ids=True``).
        """
        resolved_id = _coerce_id(campaign_id, key="campaign_id")
        if not resolved_id:
            raise ValueError("campaign_id is required")
        return self._client.delete(self._path(f"/{resolved_id}")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_ad_sets(
        self,
        ad_account_id: Any,
        *,
        fields: list[str] | None = None,
        limit: int = 10,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List ad sets in an ad account.

        Returns compact summaries: ``ad_set_ref``, ``name``, ``status``,
        ``effective_status``, ``daily_budget``, ``lifetime_budget``,
        ``optimization_goal``, ``billing_event``. Raw IDs are omitted by
        default; set ``include_ids=True`` when needed.
        """
        account = _coerce_id(ad_account_id, key="ad_account_id")
        if not account:
            raise ValueError("ad_account_id is required")
        params: dict[str, Any] = {"limit": limit}
        if fields is None:
            fields = [
                "name",
                "status",
                "effective_status",
                "daily_budget",
                "lifetime_budget",
                "optimization_goal",
                "billing_event",
            ]
        params["fields"] = ",".join(fields)
        raw: Any = self._client.get(self._path(f"/{account}/adsets"), params=params).json()
        payload: dict[str, Any] = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
        results: list[Any] = payload.get("data", [])
        summaries: list[dict[str, Any]] = []
        for index, ad_set in enumerate(results, start=1):
            if not isinstance(ad_set, dict):
                continue
            ad_set_data = cast("dict[str, Any]", ad_set)
            summary: dict[str, Any] = {
                "ad_set_ref": f"ad_set_{index}",
                "name": ad_set_data.get("name", ""),
                "status": ad_set_data.get("status", ""),
                "effective_status": ad_set_data.get("effective_status", ""),
                "daily_budget": ad_set_data.get("daily_budget"),
                "lifetime_budget": ad_set_data.get("lifetime_budget"),
                "optimization_goal": ad_set_data.get("optimization_goal", ""),
                "billing_event": ad_set_data.get("billing_event", ""),
            }
            if include_ids:
                summary["ad_set_id"] = ad_set_data.get("id", "")
            summaries.append(summary)
        return {
            "ad_sets": summaries,
            "paging": payload.get("paging"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_ads(
        self,
        ad_account_id: Any,
        *,
        fields: list[str] | None = None,
        limit: int = 10,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List ads in an ad account.

        Returns compact summaries: ``ad_ref``, ``name``, ``status``,
        ``effective_status``, ``created_time``, ``updated_time``. Raw IDs
        are omitted by default.
        """
        account = _coerce_id(ad_account_id, key="ad_account_id")
        if not account:
            raise ValueError("ad_account_id is required")
        params: dict[str, Any] = {"limit": limit}
        if fields is None:
            fields = [
                "name",
                "status",
                "effective_status",
                "created_time",
                "updated_time",
            ]
        params["fields"] = ",".join(fields)
        raw: Any = self._client.get(self._path(f"/{account}/ads"), params=params).json()
        payload: dict[str, Any] = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
        results: list[Any] = payload.get("data", [])
        summaries: list[dict[str, Any]] = []
        for index, ad in enumerate(results, start=1):
            if not isinstance(ad, dict):
                continue
            ad_data = cast("dict[str, Any]", ad)
            summary: dict[str, Any] = {
                "ad_ref": f"ad_{index}",
                "name": ad_data.get("name", ""),
                "status": ad_data.get("status", ""),
                "effective_status": ad_data.get("effective_status", ""),
                "created_time": ad_data.get("created_time", ""),
                "updated_time": ad_data.get("updated_time", ""),
            }
            if include_ids:
                summary["ad_id"] = ad_data.get("id", "")
            summaries.append(summary)
        return {
            "ads": summaries,
            "paging": payload.get("paging"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_insights(
        self,
        node_id: Any,
        *,
        level: str = "ad",
        fields: list[str] | None = None,
        time_range: dict[str, str] | None = None,
        breakdowns: list[str] | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Return insights for an ad account, campaign, ad set, or ad.

        ``node_id`` is the ID of the entity to report on (or a dict
        returned by a list tool, with ``include_ids=True``). ``level``
        must be one of ``account``, ``campaign``, ``adset``, or ``ad``.
        ``time_range`` is ``{"since": "YYYY-MM-DD", "until":
        "YYYY-MM-DD"}``. Returns the raw insights ``data`` array.
        """
        resolved_id = _coerce_id(node_id, key="id")
        if not resolved_id:
            raise ValueError("node_id is required")
        if level not in {"account", "campaign", "adset", "ad"}:
            raise ValueError("level must be account/campaign/adset/ad")
        params: dict[str, Any] = {"level": level, "limit": limit}
        if fields is not None:
            params["fields"] = ",".join(fields)
        if time_range is not None:
            import json as _json

            params["time_range"] = _json.dumps(time_range)
        if breakdowns is not None:
            params["breakdowns"] = ",".join(breakdowns)
        return self._client.get(self._path(f"/{resolved_id}/insights"), params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_custom_audiences(
        self,
        ad_account_id: Any,
        *,
        fields: list[str] | None = None,
        limit: int = 10,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List custom audiences in an ad account.

        Returns compact summaries: ``audience_ref``, ``name``,
        ``description``, ``subtype``, ``approximate_count``,
        ``time_created``, ``time_updated``. Raw IDs are omitted by
        default; set ``include_ids=True`` when needed.
        """
        account = _coerce_id(ad_account_id, key="ad_account_id")
        if not account:
            raise ValueError("ad_account_id is required")
        params: dict[str, Any] = {"limit": limit}
        if fields is None:
            fields = [
                "name",
                "description",
                "subtype",
                "approximate_count",
                "time_created",
                "time_updated",
            ]
        params["fields"] = ",".join(fields)
        raw: Any = self._client.get(self._path(f"/{account}/customaudiences"), params=params).json()
        payload: dict[str, Any] = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
        results: list[Any] = payload.get("data", [])
        summaries: list[dict[str, Any]] = []
        for index, audience in enumerate(results, start=1):
            if not isinstance(audience, dict):
                continue
            audience_data = cast("dict[str, Any]", audience)
            summary: dict[str, Any] = {
                "audience_ref": f"audience_{index}",
                "name": audience_data.get("name", ""),
                "description": audience_data.get("description", ""),
                "subtype": audience_data.get("subtype", ""),
                "approximate_count": audience_data.get("approximate_count"),
                "time_created": audience_data.get("time_created", ""),
                "time_updated": audience_data.get("time_updated", ""),
            }
            if include_ids:
                summary["audience_id"] = audience_data.get("id", "")
            summaries.append(summary)
        return {
            "audiences": summaries,
            "paging": payload.get("paging"),
        }
