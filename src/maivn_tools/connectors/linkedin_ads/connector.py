"""LinkedIn Marketing Developer Platform connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

# Current LinkedIn Marketing API monthly version (YYYYMM). Versions are
# supported for a rolling minimum of one year; refresh this on a monthly
# cadence to stay within the support window (a deprecated/sunset version
# header returns an error response).
_API_VERSION = "202605"


# MARK: Rest.li helpers


def _restli_date(date: dict[str, int]) -> str:
    """Render a ``{year, month, day}`` dict as a Rest.li date tuple.

    LinkedIn expects ``(year:Y,month:M,day:D)`` (day/end may be omitted).
    """
    parts: list[str] = []
    for key in ("year", "month", "day"):
        value = date.get(key)
        if value is not None:
            parts.append(f"{key}:{value}")
    return "(" + ",".join(parts) + ")"


def _restli_date_range(date_range: dict[str, dict[str, int]]) -> str:
    """Render a ``{start, end}`` dict as a Rest.li dateRange tuple.

    Example: ``(start:(year:2024,month:1,day:1),end:(year:2024,month:6,day:30))``.
    The ``end`` is optional (an open-ended range).
    """
    parts: list[str] = []
    start = date_range.get("start")
    if isinstance(start, dict):
        parts.append(f"start:{_restli_date(start)}")
    end = date_range.get("end")
    if isinstance(end, dict):
        parts.append(f"end:{_restli_date(end)}")
    return "(" + ",".join(parts) + ")"


def _restli_urn_list(urns: list[str]) -> str:
    """Render a list of URNs as a Rest.li ``List(urn1,urn2)`` value."""
    return "List(" + ",".join(urns) + ")"


# MARK: ID / payload coercion helpers


def _coerce_int_id(candidate: Any, *, key: str) -> int | None:
    """Best-effort lookup of an integer ID from a dict/list/scalar input.

    LinkedIn ad account / campaign IDs are numeric. Accepts a raw int or
    str, or a dict (looks up ``key`` / ``id``), or a list of such dicts.
    """
    if candidate is None:
        return None
    if isinstance(candidate, int):
        return candidate
    if isinstance(candidate, str):
        try:
            return int(candidate)
        except ValueError:
            return None
    if isinstance(candidate, dict):
        typed_candidate = cast(dict[str, Any], candidate)
        for k in (key, "id"):
            value: Any = typed_candidate.get(k)
            coerced = _coerce_int_id(value, key=key)
            if coerced is not None:
                return coerced
        return None
    if isinstance(candidate, list | tuple):
        typed_items = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in typed_items:
            value = _coerce_int_id(item, key=key)
            if value is not None:
                return value
    return None


def _payload_dict(value: Any) -> dict[str, Any]:
    """Return ``value`` as a ``dict[str, Any]`` when it is a dict, else ``{}``."""
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    return {}


def _payload_elements(payload: dict[str, Any]) -> list[Any]:
    """Return the ``elements`` list from a decoded payload, else an empty list."""
    elements: Any = payload.get("elements", [])
    if isinstance(elements, list):
        return cast("list[Any]", elements)
    return []


# MARK: ToolSet


@toolset(prefix="linkedin_ads")
class LinkedInAdsToolSet:
    """A connector for LinkedIn's Marketing Developer Platform.

    Args:
        access_token: OAuth 2.0 access token.
        linkedin_version: Monthly version header (e.g. ``"202605"``).
    """

    metadata = ProviderMetadata(
        name="linkedin_ads",
        display_name="LinkedIn Ads",
        version="0.1.0",
        description="Ad accounts, campaigns, creatives, audiences, and analytics.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url=("https://learn.microsoft.com/en-us/linkedin/marketing/"),
        homepage_url="https://www.linkedin.com/marketing-solutions/",
        tags=("marketing", "ads"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        linkedin_version: str = _API_VERSION,
        base_url: str = "https://api.linkedin.com",
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
                "LinkedIn-Version": linkedin_version,
                "X-Restli-Protocol-Version": "2.0.0",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_ad_accounts(
        self,
        *,
        q: str = "search",
        search: dict[str, Any] | None = None,
        count: int = 10,
        start: int = 0,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search ad accounts.

        Best first tool for finding a LinkedIn ad account. Returns
        compact summaries: ``account_ref`` (``account_1``, ``account_2``,
        ...), ``name``, ``status``, ``type``, ``currency``,
        ``reference``. Raw numeric IDs are omitted by default - they are
        internal handles. Set ``include_ids=True`` when a follow-up tool
        (e.g. :meth:`list_campaigns`) needs the raw ``ad_account_id``.
        """
        params: dict[str, Any] = {"q": q, "count": count, "start": start}
        if search is not None:
            import json as _json

            params["search"] = _json.dumps(search)
        payload = _payload_dict(
            self._client.get(
                "/rest/adAccounts",
                params=params,
                headers={"X-RestLi-Method": "FINDER"},
            ).json()
        )
        elements = _payload_elements(payload)
        summaries: list[dict[str, Any]] = []
        for index, account in enumerate(elements, start=1):
            if not isinstance(account, dict):
                continue
            account_dict = cast(dict[str, Any], account)
            summary: dict[str, Any] = {
                "account_ref": f"account_{index}",
                "name": account_dict.get("name", ""),
                "status": account_dict.get("status", ""),
                "type": account_dict.get("type", ""),
                "currency": account_dict.get("currency", ""),
                "reference": account_dict.get("reference", ""),
            }
            if include_ids:
                summary["ad_account_id"] = account_dict.get("id")
            summaries.append(summary)
        return {
            "accounts": summaries,
            "paging": payload.get("paging"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_ad_account(self, ad_account_id: Any) -> dict[str, Any]:
        """Return one ad account's raw record.

        Accepts a raw integer ID or an account dict returned by
        :meth:`list_ad_accounts` (with ``include_ids=True``).
        """
        resolved_id = _coerce_int_id(ad_account_id, key="ad_account_id")
        if not resolved_id:
            raise ValueError("ad_account_id is required")
        return _payload_dict(self._client.get(f"/rest/adAccounts/{resolved_id}").json())

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_campaigns(
        self,
        ad_account_id: Any,
        *,
        page_size: int = 100,
        page_token: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List campaigns in an ad account.

        Best first tool for finding a campaign. Returns compact
        summaries: ``campaign_ref``, ``name``, ``status``, ``type``,
        ``cost_type``, ``daily_budget``, ``unit_cost``, ``locale``. Raw
        numeric IDs are omitted by default; set ``include_ids=True`` when
        a follow-up tool (e.g. :meth:`update_campaign`) needs the raw
        ``campaign_id``.

        Cursor-based pagination: ``page_size`` (default 100, max 1000)
        and ``page_token`` (pass the ``next_page_token`` from a prior
        response). Index-based ``count``/``start`` is no longer supported.
        """
        account = _coerce_int_id(ad_account_id, key="ad_account_id")
        if not account:
            raise ValueError("ad_account_id is required")
        params: dict[str, Any] = {
            "q": "search",
            "pageSize": min(page_size, 1000),
        }
        if page_token:
            params["pageToken"] = page_token
        payload = _payload_dict(
            self._client.get(
                f"/rest/adAccounts/{account}/adCampaigns",
                params=params,
                headers={"X-RestLi-Method": "FINDER"},
            ).json()
        )
        elements = _payload_elements(payload)
        summaries: list[dict[str, Any]] = []
        for index, campaign in enumerate(elements, start=1):
            if not isinstance(campaign, dict):
                continue
            campaign_dict = cast(dict[str, Any], campaign)
            summary: dict[str, Any] = {
                "campaign_ref": f"campaign_{index}",
                "name": campaign_dict.get("name", ""),
                "status": campaign_dict.get("status", ""),
                "type": campaign_dict.get("type", ""),
                "cost_type": campaign_dict.get("costType", ""),
                "daily_budget": campaign_dict.get("dailyBudget"),
                "unit_cost": campaign_dict.get("unitCost"),
                "locale": campaign_dict.get("locale"),
            }
            if include_ids:
                summary["campaign_id"] = campaign_dict.get("id")
            summaries.append(summary)
        metadata = _payload_dict(payload.get("metadata"))
        next_page_token: Any = metadata.get("nextPageToken")
        return {
            "campaigns": summaries,
            "next_page_token": next_page_token,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_campaign(
        self,
        *,
        ad_account_id: Any,
        campaign_id: Any,
    ) -> dict[str, Any]:
        """Return one campaign's raw record.

        Both IDs accept a raw int / str or a dict returned by the
        corresponding list tool (with ``include_ids=True``).
        """
        account = _coerce_int_id(ad_account_id, key="ad_account_id")
        campaign = _coerce_int_id(campaign_id, key="campaign_id")
        if not account or not campaign:
            raise ValueError("ad_account_id and campaign_id are required")
        return _payload_dict(
            self._client.get(f"/rest/adAccounts/{account}/adCampaigns/{campaign}").json()
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_campaign(
        self,
        *,
        ad_account_id: Any,
        campaign_id: Any,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Partial-update a campaign.

        ``patch`` is a partial-update dict (e.g. ``{"status": "PAUSED"}``
        to pause). Both IDs accept a raw int / str or a dict (with
        ``include_ids=True``).
        """
        account = _coerce_int_id(ad_account_id, key="ad_account_id")
        campaign = _coerce_int_id(campaign_id, key="campaign_id")
        if not account or not campaign or not patch:
            raise ValueError("ad_account_id, campaign_id, and patch are required")
        return _payload_dict(
            self._client.post(
                f"/rest/adAccounts/{account}/adCampaigns/{campaign}",
                json={"patch": {"$set": patch}},
                headers={"X-RestLi-Method": "PARTIAL_UPDATE"},
            ).json()
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_creatives(
        self,
        ad_account_id: Any,
        *,
        page_size: int = 100,
        page_token: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List creatives (ads).

        Returns compact summaries: ``creative_ref``, ``status``,
        ``campaign``, ``review_status``, ``created_at``, ``last_modified_at``.
        Raw IDs are omitted by default; set ``include_ids=True`` when
        needed.

        Cursor-based pagination: ``page_size`` (default 100, max 1000)
        and ``page_token`` (pass the ``next_page_token`` from a prior
        response). Index-based ``count``/``start`` is no longer supported.
        """
        account = _coerce_int_id(ad_account_id, key="ad_account_id")
        if not account:
            raise ValueError("ad_account_id is required")
        params: dict[str, Any] = {
            "q": "criteria",
            "pageSize": min(page_size, 1000),
        }
        if page_token:
            params["pageToken"] = page_token
        payload = _payload_dict(
            self._client.get(
                f"/rest/adAccounts/{account}/creatives",
                params=params,
                headers={"X-RestLi-Method": "FINDER"},
            ).json()
        )
        elements = _payload_elements(payload)
        summaries: list[dict[str, Any]] = []
        for index, creative in enumerate(elements, start=1):
            if not isinstance(creative, dict):
                continue
            creative_dict = cast(dict[str, Any], creative)
            summary: dict[str, Any] = {
                "creative_ref": f"creative_{index}",
                "status": creative_dict.get("status", ""),
                "campaign": creative_dict.get("campaign", ""),
                "review_status": creative_dict.get("reviewStatus", ""),
                "created_at": creative_dict.get("createdAt"),
                "last_modified_at": creative_dict.get("lastModifiedAt"),
            }
            if include_ids:
                summary["creative_id"] = creative_dict.get("id")
            summaries.append(summary)
        metadata = _payload_dict(payload.get("metadata"))
        next_page_token: Any = metadata.get("nextPageToken")
        return {
            "creatives": summaries,
            "next_page_token": next_page_token,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def ad_analytics(
        self,
        *,
        pivot: str,
        date_range: dict[str, dict[str, int]],
        time_granularity: str = "DAILY",
        accounts: list[str] | None = None,
        campaigns: list[str] | None = None,
        creatives: list[str] | None = None,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run an ad analytics finder query.

        ``pivot`` is one of ``ACCOUNT``, ``CAMPAIGN``, ``CAMPAIGN_GROUP``,
        ``CREATIVE``, ``MEMBER_COMPANY_SIZE``, ``MEMBER_INDUSTRY``.
        ``date_range`` is ``{"start": {"year": 2026, "month": 1, "day": 1},
        "end": {...}}``. Returns the raw analytics ``elements``.
        """
        if not pivot or not date_range:
            raise ValueError("pivot and date_range are required")
        if pivot not in {
            "ACCOUNT",
            "CAMPAIGN",
            "CAMPAIGN_GROUP",
            "CREATIVE",
            "MEMBER_COMPANY_SIZE",
            "MEMBER_INDUSTRY",
        }:
            raise ValueError("invalid pivot")
        params: dict[str, Any] = {
            "q": "analytics",
            "pivot": pivot,
            "timeGranularity": time_granularity,
            "dateRange": _restli_date_range(date_range),
        }
        if accounts is not None:
            params["accounts"] = _restli_urn_list(accounts)
        if campaigns is not None:
            params["campaigns"] = _restli_urn_list(campaigns)
        if creatives is not None:
            params["creatives"] = _restli_urn_list(creatives)
        if fields is not None:
            params["fields"] = ",".join(fields)
        return _payload_dict(
            self._client.get(
                "/rest/adAnalytics",
                params=params,
                headers={"X-RestLi-Method": "FINDER"},
            ).json()
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_dmp_segments(
        self,
        *,
        account: str,
        count: int = 10,
        start: int = 0,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Data Management Platform (matched-audience) segments.

        ``account`` is a URN (e.g. ``"urn:li:sponsoredAccount:1234"``).
        Returns compact summaries: ``segment_ref``, ``name``,
        ``description``, ``status``, ``type``, ``audience_size_lower``,
        ``audience_size_upper``. Raw segment IDs/URNs are omitted by
        default; set ``include_ids=True`` when a follow-up tool (e.g.
        :meth:`add_users_to_dmp_segment`) needs the raw ``segment_id``.
        """
        if not account:
            raise ValueError("account is required")
        payload = _payload_dict(
            self._client.get(
                "/rest/dmpSegments",
                params={
                    "q": "account",
                    "account": account,
                    "count": count,
                    "start": start,
                },
                headers={"X-RestLi-Method": "FINDER"},
            ).json()
        )
        elements = _payload_elements(payload)
        summaries: list[dict[str, Any]] = []
        for index, segment in enumerate(elements, start=1):
            if not isinstance(segment, dict):
                continue
            segment_dict = cast(dict[str, Any], segment)
            summary: dict[str, Any] = {
                "segment_ref": f"segment_{index}",
                "name": segment_dict.get("name", ""),
                "description": segment_dict.get("description", ""),
                "status": segment_dict.get("status", ""),
                "type": segment_dict.get("type", ""),
                "audience_size_lower": segment_dict.get("audienceSizeLowerBound"),
                "audience_size_upper": segment_dict.get("audienceSizeUpperBound"),
            }
            if include_ids:
                summary["segment_id"] = segment_dict.get("id")
                summary["segment_urn"] = segment_dict.get("segment")
            summaries.append(summary)
        return {
            "segments": summaries,
            "paging": payload.get("paging"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_users_to_dmp_segment(
        self,
        *,
        segment_id: Any,
        users: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Append users to a DMP segment (e.g. matched-audience uploads).

        ``segment_id`` may be a raw string ID or a segment dict returned
        by :meth:`list_dmp_segments` (with ``include_ids=True``).
        ``users`` is a list of user dicts (each typically contains an
        ``action`` and identifiers like ``email`` / ``firstName``).
        """
        resolved_id: Any
        if isinstance(segment_id, dict):
            segment_dict = cast(dict[str, Any], segment_id)
            resolved_id = segment_dict.get("segment_id") or segment_dict.get("id")
        elif isinstance(segment_id, list | tuple):
            typed_items = cast("list[Any] | tuple[Any, ...]", segment_id)
            resolved_id = None
            for item in typed_items:
                if isinstance(item, dict):
                    item_dict = cast(dict[str, Any], item)
                    candidate: Any = item_dict.get("segment_id") or item_dict.get("id")
                    if candidate:
                        resolved_id = candidate
                        break
                elif isinstance(item, str):
                    resolved_id = item
                    break
        else:
            resolved_id = segment_id
        if not resolved_id or not users:
            raise ValueError("segment_id and users are required")
        return _payload_dict(
            self._client.post(
                f"/rest/dmpSegments/{resolved_id}/users",
                json={"elements": users},
            ).json()
        )
