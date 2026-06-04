"""eBay REST APIs connector (Browse / Sell / Inventory)."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: - Constants

# eBay ReasonForRefundEnum (Sell Fulfillment API). One of these values must be
# passed to issueRefund; the API rejects any other string.
_REFUND_REASONS = frozenset(
    {
        "BUYER_CANCEL",
        "SELLER_CANCEL",
        "ITEM_NOT_RECEIVED",
        "BUYER_REMORSE",
        "NOT_AS_DESCRIBED",
        "GENERAL_ADJUSTMENT",
        "SHIPPING_DISCOUNT",
    }
)


@toolset(prefix="ebay")
class EbayToolSet:
    """A connector for the eBay REST APIs."""

    metadata = ProviderMetadata(
        name="ebay",
        display_name="eBay",
        version="0.1.0",
        description="Listings, orders, inventory, and item browsing.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.ebay.com/api-docs/static/rest-request-components.html",
        homepage_url="https://www.ebay.com/",
        tags=("ecommerce", "marketplace"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        marketplace_id: str = "EBAY_US",
        base_url: str = "https://api.ebay.com",
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
                "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
                "Content-Language": "en-US",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Summary helpers

    @staticmethod
    def _as_dict(value: object) -> dict[str, Any]:
        """Return ``value`` as a ``dict`` when it is one, else an empty dict."""
        return cast("dict[str, Any]", value) if isinstance(value, dict) else {}

    @staticmethod
    def _item_summary(
        item: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        price = EbayToolSet._as_dict(item.get("price"))
        summary: dict[str, Any] = {
            "item_ref": f"item_{index}",
            "title": item.get("title", ""),
            "price_value": price.get("value", ""),
            "price_currency": price.get("currency", ""),
            "condition": item.get("condition", ""),
            "buying_options": item.get("buyingOptions", []),
            "item_web_url": item.get("itemWebUrl", ""),
        }
        if include_ids:
            summary["item_id"] = item.get("itemId", "")
            summary["legacy_item_id"] = item.get("legacyItemId", "")
        return summary

    @staticmethod
    def _order_summary(
        order: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        buyer = EbayToolSet._as_dict(order.get("buyer"))
        pricing = EbayToolSet._as_dict(order.get("pricingSummary"))
        total = EbayToolSet._as_dict(pricing.get("total"))
        summary: dict[str, Any] = {
            "order_ref": f"order_{index}",
            "creation_date": order.get("creationDate", ""),
            "order_fulfillment_status": order.get("orderFulfillmentStatus", ""),
            "order_payment_status": order.get("orderPaymentStatus", ""),
            "buyer_username": buyer.get("username", ""),
            "total_value": total.get("value", ""),
            "total_currency": total.get("currency", ""),
        }
        if include_ids:
            summary["order_id"] = order.get("orderId", "")
            summary["legacy_order_id"] = order.get("legacyOrderId", "")
        return summary

    # MARK: - Browse

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_items(
        self,
        *,
        q: str | None = None,
        category_ids: list[str] | None = None,
        limit: int = 10,
        offset: int = 0,
        filter: str | None = None,
        sort: str | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """Search the eBay Browse API.

        Best first tool for item discovery. Returns compact summaries with
        ``item_ref`` plus title, price, condition, buying options, and
        item web URL. Raw eBay item IDs are omitted by default — set
        ``include_ids=True`` when ``get_item`` needs them.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if q is not None:
            params["q"] = q
        if category_ids is not None:
            params["category_ids"] = ",".join(category_ids)
        if filter is not None:
            params["filter"] = filter
        if sort is not None:
            params["sort"] = sort
        payload: dict[str, Any] = self._client.get(
            "/buy/browse/v1/item_summary/search",
            params=params,
        ).json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("itemSummaries") or []
        summaries = [
            self._item_summary(cast("dict[str, Any]", it), index=i, include_ids=include_ids)
            for i, it in enumerate(items, start=1)
            if isinstance(it, dict)
        ]
        return {
            "items": summaries,
            "count": len(summaries),
            "total": payload.get("total"),
            "next": payload.get("next"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_item(self, item_id: str) -> dict[str, Any]:
        """Return full details for one Browse item by item ID.

        Use after ``search_items(include_ids=True)``.
        """
        if not item_id:
            raise ValueError("item_id must be a non-empty string")
        return self._client.get(f"/buy/browse/v1/item/{item_id}").json()

    # MARK: - Inventory

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_inventory_items(self, *, limit: int = 25, offset: int = 0) -> dict[str, Any]:
        """List seller inventory items.

        Returns the raw provider payload. Each item carries its
        user-facing ``sku``.
        """
        return self._client.get(
            "/sell/inventory/v1/inventory_item",
            params={"limit": limit, "offset": offset},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upsert_inventory_item(self, sku: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Create or update an inventory item by SKU.

        Returns ``{"sku": ..., "status": <http_status>}``. SKU is
        user-facing.
        """
        if not sku:
            raise ValueError("sku must be a non-empty string")
        response = self._client.put(
            f"/sell/inventory/v1/inventory_item/{sku}",
            json=payload,
        )
        return {"sku": sku, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_offer(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create an offer (a listing draft) for an inventory item.

        Returns the new offer resource with its ``offerId``.
        """
        if not payload:
            raise ValueError("payload must be non-empty")
        return self._client.post("/sell/inventory/v1/offer", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def publish_offer(self, offer_id: str) -> dict[str, Any]:
        """Publish an offer (creates the active eBay listing).

        Returns the listing ID. Confirm with the user before publishing —
        once live, the listing is visible to buyers.
        """
        if not offer_id:
            raise ValueError("offer_id must be a non-empty string")
        return self._client.post(
            f"/sell/inventory/v1/offer/{offer_id}/publish",
            json={},
        ).json()

    # MARK: - Orders & fulfillment

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_orders(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        filter: str | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List seller orders (Fulfillment API).

        Best first tool for seller order triage. Returns compact summaries
        with ``order_ref`` plus creation_date, fulfillment/payment status,
        buyer username, total. Raw eBay order IDs are omitted by default
        — set ``include_ids=True`` when ``issue_refund`` / ``get_order``
        needs them.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if filter is not None:
            params["filter"] = filter
        payload: dict[str, Any] = self._client.get(
            "/sell/fulfillment/v1/order",
            params=params,
        ).json()
        if include_raw:
            return payload
        orders: list[Any] = payload.get("orders") or []
        summaries = [
            self._order_summary(cast("dict[str, Any]", o), index=i, include_ids=include_ids)
            for i, o in enumerate(orders, start=1)
            if isinstance(o, dict)
        ]
        return {
            "orders": summaries,
            "count": len(summaries),
            "total": payload.get("total"),
            "next": payload.get("next"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_order(self, order_id: str) -> dict[str, Any]:
        """Return full details for one order.

        Use after ``list_orders(include_ids=True)``.
        """
        if not order_id:
            raise ValueError("order_id must be a non-empty string")
        return self._client.get(f"/sell/fulfillment/v1/order/{order_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def issue_refund(
        self,
        order_id: str,
        *,
        reason_for_refund: str,
        order_level_refund_amount: dict[str, Any] | None = None,
        refund_items: list[dict[str, Any]] | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """Issue a refund for an order. Destructive — confirm with the user first.

        ``reason_for_refund`` must be a valid eBay ReasonForRefundEnum value:
        ``BUYER_CANCEL``, ``SELLER_CANCEL``, ``ITEM_NOT_RECEIVED``,
        ``BUYER_REMORSE``, ``NOT_AS_DESCRIBED``, ``GENERAL_ADJUSTMENT``,
        ``SHIPPING_DISCOUNT``.

        A refund amount is required. For a whole-order refund pass
        ``order_level_refund_amount`` as ``{"value": "12.99", "currency":
        "USD"}``. For line-item refunds pass ``refund_items`` as a list of
        ``{"refundAmount": {"value": ..., "currency": ...}, ...}`` entries.
        Provide exactly one of the two. Returns the refund resource.
        """
        if not order_id or not reason_for_refund:
            raise ValueError("order_id and reason_for_refund must be non-empty")
        if reason_for_refund not in _REFUND_REASONS:
            raise ValueError(f"reason_for_refund must be one of {sorted(_REFUND_REASONS)}")
        if not order_level_refund_amount and not refund_items:
            raise ValueError(
                "a refund amount is required: pass order_level_refund_amount or refund_items"
            )
        body: dict[str, Any] = {"reasonForRefund": reason_for_refund}
        if order_level_refund_amount is not None:
            body["orderLevelRefundAmount"] = order_level_refund_amount
        if refund_items is not None:
            body["refundItems"] = refund_items
        if comment is not None:
            body["comment"] = comment
        return self._client.post(
            f"/sell/fulfillment/v1/order/{order_id}/issue_refund",
            json=body,
        ).json()
