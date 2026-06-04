"""TikTok Business API connector (Ads)."""

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


def _coerce_id(candidate: Any, *, key: str) -> Any:
    """Best-effort lookup of an ID from a dict/list/scalar input."""
    if candidate is None:
        return None
    if isinstance(candidate, int | str):
        return candidate
    if isinstance(candidate, dict):
        mapping = cast("dict[Any, Any]", candidate)
        for k in (key, "id", "campaign_id", "ad_id", "adgroup_id", "advertiser_id"):
            value: Any = mapping.get(k)
            if isinstance(value, int | str):
                return value
        return None
    if isinstance(candidate, list | tuple):
        items = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in items:
            resolved: Any = _coerce_id(item, key=key)
            if resolved is not None:
                return resolved
    return None


# MARK: ToolSet


@toolset(prefix="tiktok_ads")
class TikTokAdsToolSet:
    """A connector for the TikTok Business / Ads API v1.3.

    Args:
        access_token: Long-lived access token from the TikTok Business
            OAuth flow (sent via the ``Access-Token`` header).
    """

    metadata = ProviderMetadata(
        name="tiktok_ads",
        display_name="TikTok Ads",
        version="0.1.0",
        description="Advertisers, campaigns, ad groups, ads, reporting, and audiences.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://business-api.tiktok.com/portal/docs",
        homepage_url="https://ads.tiktok.com/",
        tags=("marketing", "ads", "social"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        base_url: str = "https://business-api.tiktok.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(access_token, header="Access-Token"),
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
    def list_advertisers(
        self,
        *,
        app_id: str,
        secret: str,
    ) -> dict[str, Any]:
        """List advertisers authorized for an app + secret pair.

        Use this once to discover advertiser accounts (``advertiser_id``)
        that subsequent tools take as input. Returns ``{"code": ...,
        "message": ..., "data": {"list": [...]}}``.
        """
        if not app_id or not secret:
            raise ValueError("app_id and secret are required")
        return cast(
            "dict[str, Any]",
            self._client.get(
                "/open_api/v1.3/oauth2/advertiser/get/",
                params={"app_id": app_id, "secret": secret},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_advertiser_info(
        self,
        *,
        advertiser_ids: list[str],
    ) -> dict[str, Any]:
        """Return advertiser-level info (name, currency, timezone, etc.).

        Returns the raw TikTok response with one entry per advertiser ID.
        """
        if not advertiser_ids:
            raise ValueError("advertiser_ids is required")
        import json as _json

        return cast(
            "dict[str, Any]",
            self._client.get(
                "/open_api/v1.3/advertiser/info/",
                params={"advertiser_ids": _json.dumps(advertiser_ids)},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_campaigns(
        self,
        *,
        advertiser_id: str,
        filtering: dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 10,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List campaigns.

        Best first tool for finding a campaign to pause / update.
        Returns compact summaries: ``campaign_ref`` (``campaign_1``,
        ``campaign_2``, ...), ``campaign_name``, ``operation_status``,
        ``status``, ``budget_mode``, ``budget``, ``objective_type``,
        ``create_time``, ``modify_time``. Raw TikTok IDs are omitted by
        default - they are internal handles. Set ``include_ids=True`` when
        a follow-up tool (e.g. :meth:`update_campaign`,
        :meth:`update_campaign_status`) needs the raw ``campaign_id``.
        """
        if not advertiser_id:
            raise ValueError("advertiser_id is required")
        import json as _json

        params: dict[str, Any] = {
            "advertiser_id": advertiser_id,
            "page": page,
            "page_size": page_size,
        }
        if filtering is not None:
            params["filtering"] = _json.dumps(filtering)
        payload: dict[str, Any] = cast(
            "dict[str, Any]",
            self._client.get("/open_api/v1.3/campaign/get/", params=params).json(),
        )
        data: dict[str, Any] = payload.get("data", {})
        results: list[Any] = data.get("list", [])
        summaries: list[dict[str, Any]] = []
        for index, entry in enumerate(results, start=1):
            if not isinstance(entry, dict):
                continue
            campaign: dict[str, Any] = cast("dict[str, Any]", entry)
            summary: dict[str, Any] = {
                "campaign_ref": f"campaign_{index}",
                "campaign_name": campaign.get("campaign_name", ""),
                "operation_status": campaign.get("operation_status", ""),
                "status": campaign.get("status", ""),
                "budget_mode": campaign.get("budget_mode", ""),
                "budget": campaign.get("budget"),
                "objective_type": campaign.get("objective_type", ""),
                "create_time": campaign.get("create_time", ""),
                "modify_time": campaign.get("modify_time", ""),
            }
            if include_ids:
                summary["campaign_id"] = campaign.get("campaign_id", "")
                summary["advertiser_id"] = campaign.get("advertiser_id", "")
            summaries.append(summary)
        return {
            "campaigns": summaries,
            "page_info": data.get("page_info"),
            "code": payload.get("code"),
            "message": payload.get("message"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_campaign(
        self,
        *,
        advertiser_id: str,
        campaign_name: str,
        objective_type: str,
        budget_mode: str = "BUDGET_MODE_DAY",
        budget: float | None = None,
    ) -> dict[str, Any]:
        """Create a campaign.

        Returns the new campaign descriptor (with TikTok-assigned
        ``campaign_id``). Confirm the budget mode (daily vs. total) and
        target objective before calling.
        """
        if not advertiser_id or not campaign_name or not objective_type:
            raise ValueError("advertiser_id, campaign_name, and objective_type are required")
        body: dict[str, Any] = {
            "advertiser_id": advertiser_id,
            "campaign_name": campaign_name,
            "objective_type": objective_type,
            "budget_mode": budget_mode,
        }
        if budget is not None:
            body["budget"] = budget
        return cast(
            "dict[str, Any]",
            self._client.post("/open_api/v1.3/campaign/create/", json=body).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_campaign(
        self,
        *,
        advertiser_id: str,
        campaign_id: Any,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Update campaign attributes.

        ``campaign_id`` may be a raw string ID or a campaign dict returned
        by :meth:`list_campaigns` (with ``include_ids=True``). ``fields``
        is the partial-update dict (e.g. ``{"campaign_name": "New name"}``).
        """
        resolved_id = _coerce_id(campaign_id, key="campaign_id")
        if not advertiser_id or not resolved_id or not fields:
            raise ValueError("advertiser_id, campaign_id, and fields are required")
        return cast(
            "dict[str, Any]",
            self._client.post(
                "/open_api/v1.3/campaign/update/",
                json={
                    "advertiser_id": advertiser_id,
                    "campaign_id": resolved_id,
                    **fields,
                },
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_campaign_status(
        self,
        *,
        advertiser_id: str,
        campaign_ids: list[Any],
        operation_status: str,
    ) -> dict[str, Any]:
        """Pause, resume, or delete campaigns.

        ``operation_status`` must be one of ``ENABLE`` (resume),
        ``DISABLE`` (pause), or ``DELETE`` (archive). ``campaign_ids``
        accepts raw IDs or campaign dicts (with ``include_ids=True``).
        Confirm with the user before calling, especially for ``DELETE``.
        """
        if not advertiser_id or not campaign_ids or not operation_status:
            raise ValueError("advertiser_id, campaign_ids, and operation_status are required")
        if operation_status not in {"ENABLE", "DISABLE", "DELETE"}:
            raise ValueError("operation_status must be ENABLE/DISABLE/DELETE")
        resolved_ids: list[Any] = []
        for entry in campaign_ids:
            value = _coerce_id(entry, key="campaign_id")
            if value is not None:
                resolved_ids.append(value)
        if not resolved_ids:
            raise ValueError("campaign_ids must contain at least one valid id")
        return cast(
            "dict[str, Any]",
            self._client.post(
                "/open_api/v1.3/campaign/status/update/",
                json={
                    "advertiser_id": advertiser_id,
                    "campaign_ids": resolved_ids,
                    "operation_status": operation_status,
                },
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_ad_groups(
        self,
        *,
        advertiser_id: str,
        filtering: dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 10,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List ad groups.

        Returns compact summaries: ``ad_group_ref``, ``adgroup_name``,
        ``operation_status``, ``status``, ``budget_mode``, ``budget``,
        ``optimization_goal``, ``billing_event``, ``schedule_type``,
        ``create_time``, ``modify_time``. Raw IDs are omitted by default;
        set ``include_ids=True`` when needed.
        """
        if not advertiser_id:
            raise ValueError("advertiser_id is required")
        import json as _json

        params: dict[str, Any] = {
            "advertiser_id": advertiser_id,
            "page": page,
            "page_size": page_size,
        }
        if filtering is not None:
            params["filtering"] = _json.dumps(filtering)
        payload: dict[str, Any] = cast(
            "dict[str, Any]",
            self._client.get("/open_api/v1.3/adgroup/get/", params=params).json(),
        )
        data: dict[str, Any] = payload.get("data", {})
        results: list[Any] = data.get("list", [])
        summaries: list[dict[str, Any]] = []
        for index, entry in enumerate(results, start=1):
            if not isinstance(entry, dict):
                continue
            ad_group: dict[str, Any] = cast("dict[str, Any]", entry)
            summary: dict[str, Any] = {
                "ad_group_ref": f"ad_group_{index}",
                "adgroup_name": ad_group.get("adgroup_name", ""),
                "operation_status": ad_group.get("operation_status", ""),
                "status": ad_group.get("status", ""),
                "budget_mode": ad_group.get("budget_mode", ""),
                "budget": ad_group.get("budget"),
                "optimization_goal": ad_group.get("optimization_goal", ""),
                "billing_event": ad_group.get("billing_event", ""),
                "schedule_type": ad_group.get("schedule_type", ""),
                "create_time": ad_group.get("create_time", ""),
                "modify_time": ad_group.get("modify_time", ""),
            }
            if include_ids:
                summary["adgroup_id"] = ad_group.get("adgroup_id", "")
                summary["campaign_id"] = ad_group.get("campaign_id", "")
            summaries.append(summary)
        return {
            "ad_groups": summaries,
            "page_info": data.get("page_info"),
            "code": payload.get("code"),
            "message": payload.get("message"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_ads(
        self,
        *,
        advertiser_id: str,
        filtering: dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 10,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List ads.

        Returns compact summaries: ``ad_ref``, ``ad_name``,
        ``operation_status``, ``status``, ``ad_format``, ``create_time``,
        ``modify_time``. Raw IDs are omitted by default; set
        ``include_ids=True`` when needed.
        """
        if not advertiser_id:
            raise ValueError("advertiser_id is required")
        import json as _json

        params: dict[str, Any] = {
            "advertiser_id": advertiser_id,
            "page": page,
            "page_size": page_size,
        }
        if filtering is not None:
            params["filtering"] = _json.dumps(filtering)
        payload: dict[str, Any] = cast(
            "dict[str, Any]",
            self._client.get("/open_api/v1.3/ad/get/", params=params).json(),
        )
        data: dict[str, Any] = payload.get("data", {})
        results: list[Any] = data.get("list", [])
        summaries: list[dict[str, Any]] = []
        for index, entry in enumerate(results, start=1):
            if not isinstance(entry, dict):
                continue
            ad: dict[str, Any] = cast("dict[str, Any]", entry)
            summary: dict[str, Any] = {
                "ad_ref": f"ad_{index}",
                "ad_name": ad.get("ad_name", ""),
                "operation_status": ad.get("operation_status", ""),
                "status": ad.get("status", ""),
                "ad_format": ad.get("ad_format", ""),
                "create_time": ad.get("create_time", ""),
                "modify_time": ad.get("modify_time", ""),
            }
            if include_ids:
                summary["ad_id"] = ad.get("ad_id", "")
                summary["adgroup_id"] = ad.get("adgroup_id", "")
                summary["campaign_id"] = ad.get("campaign_id", "")
            summaries.append(summary)
        return {
            "ads": summaries,
            "page_info": data.get("page_info"),
            "code": payload.get("code"),
            "message": payload.get("message"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_reports(
        self,
        *,
        advertiser_id: str,
        report_type: str,
        data_level: str,
        dimensions: list[str],
        metrics: list[str],
        start_date: str,
        end_date: str,
        page: int = 1,
        page_size: int = 1000,
    ) -> dict[str, Any]:
        """Run a synchronous report.

        ``report_type`` is typically ``BASIC``. ``data_level`` is one of
        ``AUCTION_CAMPAIGN``, ``AUCTION_ADGROUP``, ``AUCTION_AD``.
        ``dimensions`` and ``metrics`` are lists of field names.
        ``start_date`` / ``end_date`` use ``YYYY-MM-DD``.
        """
        if (
            not advertiser_id
            or not report_type
            or not data_level
            or not dimensions
            or not metrics
            or not start_date
            or not end_date
        ):
            raise ValueError(
                "advertiser_id, report_type, data_level, dimensions, "
                "metrics, start_date, and end_date are required"
            )
        import json as _json

        return cast(
            "dict[str, Any]",
            self._client.get(
                "/open_api/v1.3/report/integrated/get/",
                params={
                    "advertiser_id": advertiser_id,
                    "report_type": report_type,
                    "data_level": data_level,
                    "dimensions": _json.dumps(dimensions),
                    "metrics": _json.dumps(metrics),
                    "start_date": start_date,
                    "end_date": end_date,
                    "page": page,
                    "page_size": page_size,
                },
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_audiences(
        self,
        *,
        advertiser_id: str,
        page: int = 1,
        page_size: int = 10,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List custom audiences.

        Returns compact summaries: ``audience_ref``, ``audience_name``,
        ``audience_type``, ``audience_subtype``, ``cover_num``,
        ``create_time``, ``calculate_type``. Raw IDs are omitted by
        default; set ``include_ids=True`` when needed.
        """
        if not advertiser_id:
            raise ValueError("advertiser_id is required")
        payload: dict[str, Any] = cast(
            "dict[str, Any]",
            self._client.get(
                "/open_api/v1.3/dmp/custom_audience/list/",
                params={
                    "advertiser_id": advertiser_id,
                    "page": page,
                    "page_size": page_size,
                },
            ).json(),
        )
        data: dict[str, Any] = payload.get("data", {})
        results: list[Any] = data.get("list", [])
        summaries: list[dict[str, Any]] = []
        for index, entry in enumerate(results, start=1):
            if not isinstance(entry, dict):
                continue
            audience: dict[str, Any] = cast("dict[str, Any]", entry)
            summary: dict[str, Any] = {
                "audience_ref": f"audience_{index}",
                "audience_name": audience.get("audience_name", ""),
                "audience_type": audience.get("audience_type", ""),
                "audience_subtype": audience.get("audience_subtype", ""),
                "cover_num": audience.get("cover_num"),
                "create_time": audience.get("create_time", ""),
                "calculate_type": audience.get("calculate_type", ""),
            }
            if include_ids:
                summary["audience_id"] = audience.get("audience_id", "")
            summaries.append(summary)
        return {
            "audiences": summaries,
            "page_info": data.get("page_info"),
            "code": payload.get("code"),
            "message": payload.get("message"),
        }
