"""Amazon Selling Partner API (SP-API) connector.

SP-API requires LWA (Login with Amazon) access tokens. This connector
takes a pre-issued bearer token and lets callers supply a custom
``AuthStrategy`` if their setup requires request signing.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...auth.base import AuthStrategy
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_ORDERS_OUTPUT

# MARK: ToolSet


@toolset(prefix="amzn_seller")
class AmazonSellerToolSet:
    """A connector for Amazon SP-API."""

    metadata = ProviderMetadata(
        name="amazon_seller",
        display_name="Amazon Seller Central (SP-API)",
        version="0.1.0",
        description="Orders, inventory, listings, reports via SP-API.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE, AuthMode.BEARER),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer-docs.amazon.com/sp-api/",
        homepage_url="https://sellercentral.amazon.com/",
        tags=("ecommerce", "marketplace"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        region_endpoint: str = "https://sellingpartnerapi-na.amazon.com",
        auth: AuthStrategy | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=region_endpoint.rstrip("/"),
            auth=auth or ApiKeyAuth(access_token, header="x-amz-access-token"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @staticmethod
    def _order_summary(
        order: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        buyer_raw: object = order.get("BuyerInfo") or {}
        total_raw: object = order.get("OrderTotal") or {}
        buyer: dict[str, Any] = (
            cast("dict[str, Any]", buyer_raw) if isinstance(buyer_raw, dict) else {}
        )
        total: dict[str, Any] = (
            cast("dict[str, Any]", total_raw) if isinstance(total_raw, dict) else {}
        )
        summary: dict[str, Any] = {
            "order_ref": f"order_{index}",
            "amazon_order_id": order.get("AmazonOrderId", ""),
            "purchase_date": order.get("PurchaseDate", ""),
            "order_status": order.get("OrderStatus", ""),
            "fulfillment_channel": order.get("FulfillmentChannel", ""),
            "buyer_email": buyer.get("BuyerEmail", ""),
            "total_amount": total.get("Amount", ""),
            "total_currency": total.get("CurrencyCode", ""),
            "number_of_items_shipped": order.get("NumberOfItemsShipped", 0),
            "number_of_items_unshipped": order.get("NumberOfItemsUnshipped", 0),
        }
        if include_ids:
            summary["amazon_order_id_raw"] = order.get("AmazonOrderId", "")
            summary["seller_order_id"] = order.get("SellerOrderId", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_ORDERS_OUTPUT)
    def list_orders(
        self,
        *,
        marketplace_ids: list[str],
        created_after: str,
        created_before: str | None = None,
        order_statuses: list[str] | None = None,
        next_token: str | None = None,
        max_results: int = 25,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List orders via the Orders v0 API.

        Best first tool for Amazon order triage. Returns compact summaries
        with ``order_ref`` plus amazon_order_id (user-facing), purchase
        date, status, total, currency. Note: Amazon order IDs are
        user-facing — they appear on packing slips and in Seller Central
        — so the amazon_order_id is always shown. Set ``include_ids=True``
        for SellerOrderId or ``include_raw=True`` for the full payload.
        Preserves the ``NextToken`` pagination cursor.
        """
        if not marketplace_ids or not created_after:
            raise ValueError("marketplace_ids and created_after must be non-empty")
        params: dict[str, Any] = {
            "MarketplaceIds": ",".join(marketplace_ids),
            "CreatedAfter": created_after,
            "MaxResultsPerPage": max_results,
        }
        if created_before is not None:
            params["CreatedBefore"] = created_before
        if order_statuses is not None:
            params["OrderStatuses"] = ",".join(order_statuses)
        if next_token is not None:
            params["NextToken"] = next_token
        payload: dict[str, Any] = self._client.get("/orders/v0/orders", params=params).json()
        if include_raw:
            return payload
        orders_payload: dict[str, Any] = payload.get("payload") or {}
        orders: list[Any] = orders_payload.get("Orders") or []
        summaries = [
            self._order_summary(cast("dict[str, Any]", o), index=i, include_ids=include_ids)
            for i, o in enumerate(orders, start=1)
            if isinstance(o, dict)
        ]
        return {
            "orders": summaries,
            "count": len(summaries),
            "next_token": orders_payload.get("NextToken"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_order(self, order_id: str) -> dict[str, Any]:
        """Return one order by Amazon order ID.

        Amazon order IDs like ``123-1234567-1234567`` are user-facing.
        """
        if not order_id:
            raise ValueError("order_id must be a non-empty string")
        return self._client.get(f"/orders/v0/orders/{order_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_order_items(self, order_id: str) -> dict[str, Any]:
        """Return line items of an order.

        Use after ``list_orders`` / ``get_order`` to inspect what was
        purchased. Returns the raw provider payload.
        """
        if not order_id:
            raise ValueError("order_id must be a non-empty string")
        return self._client.get(
            f"/orders/v0/orders/{order_id}/orderItems",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_inventory_summaries(
        self,
        *,
        marketplace_ids: list[str],
        granularity_type: str = "Marketplace",
        granularity_id: str | None = None,
    ) -> dict[str, Any]:
        """Get FBA inventory summaries.

        Returns the raw inventory summaries payload from SP-API. Use
        ``granularity_id`` to scope to a specific marketplace. SP-API
        requires ``granularityId`` for ``getInventorySummaries``; when
        ``granularity_type == 'Marketplace'`` and ``granularity_id`` is
        omitted, it defaults to the single ``marketplace_ids`` entry.
        """
        if not marketplace_ids:
            raise ValueError("marketplace_ids must be non-empty")
        resolved_granularity_id = granularity_id
        if resolved_granularity_id is None and granularity_type == "Marketplace":
            if len(marketplace_ids) != 1:
                raise ValueError(
                    "granularity_id is required when granularity_type=='Marketplace' "
                    "and more than one marketplace_id is supplied",
                )
            resolved_granularity_id = marketplace_ids[0]
        params: dict[str, Any] = {
            "marketplaceIds": ",".join(marketplace_ids),
            "granularityType": granularity_type,
        }
        if resolved_granularity_id is not None:
            params["granularityId"] = resolved_granularity_id
        return self._client.get(
            "/fba/inventory/v1/summaries",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_catalog_item(
        self,
        asin: str,
        *,
        marketplace_ids: list[str],
        included_data: list[str] | None = None,
    ) -> dict[str, Any]:
        """Look up an item in the catalog by ASIN.

        ASINs are user-facing Amazon identifiers. ``included_data`` may
        contain ``summaries``, ``attributes``, ``images``, ``salesRanks``,
        etc. Returns the raw catalog item resource.
        """
        if not asin or not marketplace_ids:
            raise ValueError("asin and marketplace_ids must be non-empty")
        params: dict[str, Any] = {"marketplaceIds": ",".join(marketplace_ids)}
        if included_data is not None:
            params["includedData"] = ",".join(included_data)
        return self._client.get(
            f"/catalog/2022-04-01/items/{asin}",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_catalog_items(
        self,
        *,
        marketplace_ids: list[str],
        keywords: str | None = None,
        identifiers: list[str] | None = None,
        identifiers_type: str | None = None,
        page_size: int = 10,
    ) -> dict[str, Any]:
        """Search the Amazon catalog by keywords or identifiers.

        ``identifiers_type`` is one of ``ASIN``, ``EAN``, ``GTIN``,
        ``ISBN``, ``MINSAN``, ``SKU``, ``UPC``. Returns the raw provider
        payload.
        """
        if not marketplace_ids:
            raise ValueError("marketplace_ids must be non-empty")
        params: dict[str, Any] = {
            "marketplaceIds": ",".join(marketplace_ids),
            "pageSize": page_size,
        }
        if keywords is not None:
            params["keywords"] = keywords
        if identifiers is not None:
            params["identifiers"] = ",".join(identifiers)
        if identifiers_type is not None:
            params["identifiersType"] = identifiers_type
        return self._client.get(
            "/catalog/2022-04-01/items",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_report(
        self,
        *,
        report_type: str,
        marketplace_ids: list[str],
        data_start_time: str | None = None,
        data_end_time: str | None = None,
    ) -> dict[str, Any]:
        """Request a report (e.g. ``GET_FLAT_FILE_OPEN_LISTINGS_DATA``).

        Returns ``{"reportId": ...}``. The report is generated
        asynchronously — poll with ``get_report`` and download the
        document when ``processingStatus`` is ``DONE``.
        """
        if not report_type or not marketplace_ids:
            raise ValueError("report_type and marketplace_ids must be non-empty")
        body: dict[str, Any] = {
            "reportType": report_type,
            "marketplaceIds": marketplace_ids,
        }
        if data_start_time is not None:
            body["dataStartTime"] = data_start_time
        if data_end_time is not None:
            body["dataEndTime"] = data_end_time
        return self._client.post("/reports/2021-06-30/reports", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_report(self, report_id: str) -> dict[str, Any]:
        """Return one report's status and metadata.

        Check ``processingStatus`` — when it's ``DONE``, the
        ``reportDocumentId`` is ready to fetch.
        """
        if not report_id:
            raise ValueError("report_id must be a non-empty string")
        return self._client.get(f"/reports/2021-06-30/reports/{report_id}").json()
