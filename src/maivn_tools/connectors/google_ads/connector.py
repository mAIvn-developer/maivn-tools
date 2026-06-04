"""Google Ads REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.base import AuthStrategy
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

# Default Google Ads API version. Google releases roughly monthly and sunsets
# each major version ~12 months after release, keeping ~4 versions live at a
# time. v17 was sunset on 2025-06-04; v24 is the latest supported release as of
# 2026-05-31. Callers should track the release/sunset cadence and bump this.
_API_VERSION = "v24"


# MARK: Helpers


def _coerce_customer_id(candidate: Any) -> str:
    """Best-effort lookup of a Google Ads customer ID.

    Accepts a raw ID string, or a dict (looks up ``customer_id`` / ``id``
    / ``resourceName``), or a list of such dicts. ``resourceName`` is parsed
    from ``customers/{id}`` form. Returns the cleaned numeric string with
    dashes stripped.
    """
    if isinstance(candidate, str):
        return candidate.replace("-", "")
    if isinstance(candidate, dict):
        mapping = cast("dict[str, Any]", candidate)
        for key in ("customer_id", "id"):
            value: Any = mapping.get(key)
            if isinstance(value, str):
                return value.replace("-", "")
        resource: Any = mapping.get("resourceName")
        if isinstance(resource, str) and resource.startswith("customers/"):
            return resource.split("/", 1)[1].split("/", 1)[0]
        return ""
    if isinstance(candidate, list | tuple):
        items = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in items:
            result = _coerce_customer_id(item)
            if result:
                return result
    return ""


# MARK: Auth strategy


class _GoogleAdsAuth(AuthStrategy):
    """Adds OAuth bearer + developer token + optional login customer."""

    mode = AuthMode.OAUTH2_AUTH_CODE

    def __init__(
        self,
        access_token: str,
        developer_token: str,
        login_customer_id: str | None,
    ) -> None:
        self._access_token = access_token
        self._developer_token = developer_token
        self._login_customer_id = login_customer_id

    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        headers = dict(request.get("headers") or {})
        headers["Authorization"] = f"Bearer {self._access_token}"
        headers["developer-token"] = self._developer_token
        if self._login_customer_id:
            headers["login-customer-id"] = self._login_customer_id
        request["headers"] = headers
        return request

    def describe(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "scheme": "google-ads-oauth"}


# MARK: Tool set


@toolset(prefix="google_ads")
class GoogleAdsToolSet:
    """A connector for the Google Ads REST API.

    Args:
        access_token: OAuth 2.0 access token for the manager / login user.
        developer_token: Manager-account developer token.
        login_customer_id: Manager / MCC customer ID for cross-account calls.
        api_version: API version path segment (default ``"v24"``).
    """

    metadata = ProviderMetadata(
        name="google_ads",
        display_name="Google Ads",
        version="0.1.0",
        description="Customers, campaigns, ad groups, ads, GAQL queries, and budgets.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developers.google.com/google-ads/api/rest",
        homepage_url="https://ads.google.com/",
        tags=("marketing", "ads"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        developer_token: str,
        login_customer_id: str | None = None,
        api_version: str = _API_VERSION,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token or not developer_token:
            raise ValueError("access_token and developer_token are required")
        self.connection = connection
        self._version = api_version
        self._client = HttpClient(
            base_url="https://googleads.googleapis.com",
            auth=_GoogleAdsAuth(access_token, developer_token, login_customer_id),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _path(self, suffix: str) -> str:
        return f"/{self._version}{suffix}"

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_accessible_customers(self) -> dict[str, Any]:
        """List customer resource names the auth user can access.

        Best first tool when you don't know which Google Ads customer to
        operate on. Returns ``{"resourceNames": ["customers/1234567890",
        ...]}``. The trailing numeric ID is what subsequent tools take as
        ``customer_id``.
        """
        return self._client.get(self._path("/customers:listAccessibleCustomers")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search(
        self,
        *,
        customer_id: Any,
        query: str,
        page_size: int = 1000,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """Run a GAQL search.

        Best general-purpose tool for reading campaigns, ad groups, ads,
        metrics, etc. ``query`` is a GAQL string (e.g. ``"SELECT
        campaign.id, campaign.name, metrics.clicks FROM campaign WHERE
        segments.date DURING LAST_7_DAYS"``). ``customer_id`` accepts a
        raw string, a list dict with ``customer_id`` / ``resourceName``
        keys, or a list of such items. Returns the raw GAQL response with
        ``results``, ``fieldMask``, and ``nextPageToken``.
        """
        cid = _coerce_customer_id(customer_id)
        if not cid or not query:
            raise ValueError("customer_id and query are required")
        body: dict[str, Any] = {"query": query, "pageSize": page_size}
        if page_token is not None:
            body["pageToken"] = page_token
        return self._client.post(
            self._path(f"/customers/{cid}/googleAds:search"),
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_stream(
        self,
        *,
        customer_id: Any,
        query: str,
    ) -> dict[str, Any]:
        """Run a streaming GAQL search.

        Use this for large result sets that would otherwise require
        multiple paginated :meth:`search` calls. Same input as
        :meth:`search` minus pagination.
        """
        cid = _coerce_customer_id(customer_id)
        if not cid or not query:
            raise ValueError("customer_id and query are required")
        return self._client.post(
            self._path(f"/customers/{cid}/googleAds:searchStream"),
            json={"query": query},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def mutate_campaigns(
        self,
        *,
        customer_id: Any,
        operations: list[dict[str, Any]],
        partial_failure: bool = False,
        validate_only: bool = False,
    ) -> dict[str, Any]:
        """Create, update, or remove campaigns.

        ``operations`` is a list of GA mutate-operation dicts (each with
        a ``create``, ``update``, or ``remove`` key). Set
        ``validate_only=True`` to dry-run without applying changes.
        Always confirm large or removal operations with the user first.
        """
        cid = _coerce_customer_id(customer_id)
        if not cid or not operations:
            raise ValueError("customer_id and operations are required")
        return self._client.post(
            self._path(f"/customers/{cid}/campaigns:mutate"),
            json={
                "operations": operations,
                "partialFailure": partial_failure,
                "validateOnly": validate_only,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def mutate_ad_groups(
        self,
        *,
        customer_id: Any,
        operations: list[dict[str, Any]],
        partial_failure: bool = False,
    ) -> dict[str, Any]:
        """Create, update, or remove ad groups.

        See :meth:`mutate_campaigns` for the operations dict shape.
        """
        cid = _coerce_customer_id(customer_id)
        if not cid or not operations:
            raise ValueError("customer_id and operations are required")
        return self._client.post(
            self._path(f"/customers/{cid}/adGroups:mutate"),
            json={
                "operations": operations,
                "partialFailure": partial_failure,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def mutate_ad_group_ads(
        self,
        *,
        customer_id: Any,
        operations: list[dict[str, Any]],
        partial_failure: bool = False,
    ) -> dict[str, Any]:
        """Create, update, or remove ad-group ads.

        See :meth:`mutate_campaigns` for the operations dict shape.
        """
        cid = _coerce_customer_id(customer_id)
        if not cid or not operations:
            raise ValueError("customer_id and operations are required")
        return self._client.post(
            self._path(f"/customers/{cid}/adGroupAds:mutate"),
            json={
                "operations": operations,
                "partialFailure": partial_failure,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def mutate_campaign_budgets(
        self,
        *,
        customer_id: Any,
        operations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create, update, or remove campaign budgets.

        Budgets are shared resources - removing a budget that other
        campaigns reference will fail. Use a GAQL search on
        ``campaign_budget`` to inventory before mutating.
        """
        cid = _coerce_customer_id(customer_id)
        if not cid or not operations:
            raise ValueError("customer_id and operations are required")
        return self._client.post(
            self._path(f"/customers/{cid}/campaignBudgets:mutate"),
            json={"operations": operations},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upload_click_conversions(
        self,
        *,
        customer_id: Any,
        conversions: list[dict[str, Any]],
        partial_failure: bool = True,
    ) -> dict[str, Any]:
        """Upload offline click conversions.

        ``conversions`` is a list of conversion dicts (each typically
        contains ``conversion_action``, ``gclid`` or ``gbraid`` /
        ``wbraid``, ``conversion_date_time``, and ``conversion_value``).
        """
        cid = _coerce_customer_id(customer_id)
        if not cid or not conversions:
            raise ValueError("customer_id and conversions are required")
        return self._client.post(
            self._path(f"/customers/{cid}:uploadClickConversions"),
            json={
                "conversions": conversions,
                "partialFailure": partial_failure,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upload_offline_user_data(
        self,
        *,
        customer_id: Any,
        operations: list[dict[str, Any]],
        enable_partial_failure: bool = True,
    ) -> dict[str, Any]:
        """Upload offline user data (e.g. Customer Match audience members).

        Each operation is typically a ``create`` with a ``userIdentifier``
        list. Hashed email / phone follows Google's preprocessing rules.
        """
        cid = _coerce_customer_id(customer_id)
        if not cid or not operations:
            raise ValueError("customer_id and operations are required")
        return self._client.post(
            self._path(f"/customers/{cid}:uploadUserData"),
            json={
                "operations": operations,
                "enablePartialFailure": enable_partial_failure,
            },
        ).json()
