"""Walmart Marketplace API connector.

Walmart Marketplace expects a ``WM_SEC.ACCESS_TOKEN`` header obtained from
the token endpoint plus several correlation headers. This connector takes
a pre-issued access token and lets callers extend headers as needed.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.base import NoAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Helpers


def _as_dict(value: Any) -> dict[str, Any]:
    """Return ``value`` as a typed dict if it is a mapping, else an empty dict."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    """Return ``value`` as a typed list if it is a sequence, else an empty list."""
    return cast("list[Any]", value) if isinstance(value, list) else []


def _coerce_sku(candidate: Any) -> str:
    """Accept a dict from list/get or a raw SKU and return the SKU."""
    if isinstance(candidate, dict):
        candidate_dict = cast("dict[str, Any]", candidate)
        for key in ("sku", "product_sku"):
            value: Any = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
    if isinstance(candidate, str) and candidate:
        return candidate
    type_name: str = type(cast(object, candidate)).__name__
    raise ValueError(f"sku is required (got: {type_name})")


# MARK: ToolSet


@toolset(prefix="walmart")
class WalmartMarketplaceToolSet:
    """A connector for the Walmart Marketplace v3 API."""

    metadata = ProviderMetadata(
        name="walmart_marketplace",
        display_name="Walmart Marketplace",
        version="0.1.0",
        description="Items, orders, inventory, and reports.",
        auth_modes=(AuthMode.OAUTH2_CLIENT_CREDENTIALS,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.walmart.com/api/us/mp/feeds",
        homepage_url="https://marketplace.walmart.com/",
        tags=("ecommerce", "marketplace"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        consumer_id: str | None = None,
        channel_type: str | None = None,
        base_url: str = "https://marketplace.walmartapis.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self.connection = connection
        headers: dict[str, str] = {
            "Accept": "application/json",
            "WM_SEC.ACCESS_TOKEN": access_token,
            "WM_QOS.CORRELATION_ID": "00000000-0000-0000-0000-000000000000",
            "WM_SVC.NAME": "Walmart Marketplace",
        }
        if consumer_id is not None:
            headers["WM_CONSUMER.ID"] = consumer_id
        if channel_type is not None:
            headers["WM_CONSUMER.CHANNEL.TYPE"] = channel_type
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=NoAuth(),
            transport=transport,
            default_headers=headers,
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @staticmethod
    def _item_summary(
        item: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "item_ref": f"item_{index}",
            "sku": item.get("sku", ""),
            "product_name": item.get("productName", ""),
            "price": item.get("price"),
            "publish_status": item.get("publishedStatus", ""),
            "lifecycle_status": item.get("lifecycleStatus", ""),
        }
        if include_ids:
            summary["wpid"] = item.get("wpid", "")
            summary["gtin"] = item.get("gtin", "")
        return summary

    @staticmethod
    def _order_summary(
        order: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        shipping_info: dict[str, Any] = _as_dict(order.get("shippingInfo"))
        postal_addr: dict[str, Any] = _as_dict(shipping_info.get("postalAddress"))
        summary: dict[str, Any] = {
            "order_ref": f"order_{index}",
            "purchase_order_id": order.get("purchaseOrderId", ""),
            "customer_order_id": order.get("customerOrderId", ""),
            "order_date": order.get("orderDate", ""),
            "customer_name": postal_addr.get("name", ""),
            "customer_email_id": order.get("customerEmailId", ""),
        }
        if include_ids:
            summary["purchase_order_id_raw"] = order.get("purchaseOrderId", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_items(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        next_cursor: str | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List items in the catalog.

        Best first tool for catalog exploration. Returns compact summaries
        with ``item_ref`` plus sku (user-facing), product_name, price,
        status. Raw WPIDs are omitted by default. Pass ``next_cursor`` to
        page beyond the first ~200 items; the returned ``next_cursor`` is
        the token for the following page.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if next_cursor is not None:
            params["nextCursor"] = next_cursor
        payload: dict[str, Any] = self._client.get(
            "/v3/items",
            params=params,
        ).json()
        if include_raw:
            return payload
        block: dict[str, Any] = _as_dict(payload.get("ItemResponses"))
        item_list: list[Any] = _as_list(block.get("ItemResponse"))
        summaries: list[dict[str, Any]] = [
            self._item_summary(cast("dict[str, Any]", it), index=i, include_ids=include_ids)
            for i, it in enumerate(item_list, start=1)
            if isinstance(it, dict)
        ]
        return {
            "items": summaries,
            "count": len(summaries),
            "total_items": block.get("totalItems"),
            "next_cursor": block.get("nextCursor"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_item(self, sku: str) -> dict[str, Any]:
        """Return full details for one item by SKU.

        SKU is the user-facing identifier.
        """
        if not sku:
            raise ValueError("sku must be a non-empty string")
        return self._client.get(f"/v3/items/{sku}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def retire_item(self, sku: Any) -> dict[str, Any]:
        """Retire (permanently delist) an item. Destructive — confirm with the user first.

        Tolerant inputs: ``sku`` may be a raw string or a dict returned
        by ``list_items`` / ``get_item``.
        """
        resolved_sku = _coerce_sku(sku)
        return self._client.delete(f"/v3/items/{resolved_sku}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_orders(
        self,
        *,
        created_start_date: str,
        created_end_date: str | None = None,
        status: str | None = None,
        limit: int = 20,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List orders.

        Best first tool for Walmart order triage. Returns compact
        summaries with ``order_ref`` plus purchase_order_id and
        customer_order_id (both user-facing), order_date, customer name.
        Dates are ISO ``YYYY-MM-DD``.
        """
        if not created_start_date:
            raise ValueError("created_start_date is required")
        params: dict[str, Any] = {
            "createdStartDate": created_start_date,
            "limit": limit,
        }
        if created_end_date is not None:
            params["createdEndDate"] = created_end_date
        if status is not None:
            params["status"] = status
        payload: dict[str, Any] = self._client.get("/v3/orders", params=params).json()
        if include_raw:
            return payload
        list_block: dict[str, Any] = _as_dict(payload.get("list"))
        elements: dict[str, Any] = _as_dict(list_block.get("elements"))
        order_list: list[Any] = _as_list(elements.get("order"))
        summaries: list[dict[str, Any]] = [
            self._order_summary(cast("dict[str, Any]", o), index=i, include_ids=include_ids)
            for i, o in enumerate(order_list, start=1)
            if isinstance(o, dict)
        ]
        meta: dict[str, Any] = _as_dict(list_block.get("meta"))
        return {
            "orders": summaries,
            "count": len(summaries),
            "next_cursor": meta.get("nextCursor"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_order(self, purchase_order_id: str) -> dict[str, Any]:
        """Return one order by purchase order ID.

        Purchase order IDs are user-facing.
        """
        if not purchase_order_id:
            raise ValueError("purchase_order_id must be a non-empty string")
        return self._client.get(f"/v3/orders/{purchase_order_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def acknowledge_order(self, purchase_order_id: str) -> dict[str, Any]:
        """Acknowledge that the seller has received an order.

        Required step before fulfillment.
        """
        if not purchase_order_id:
            raise ValueError("purchase_order_id must be a non-empty string")
        return self._client.post(
            f"/v3/orders/{purchase_order_id}/acknowledge",
            json={},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_inventory(self, sku: str) -> dict[str, Any]:
        """Return inventory for a SKU."""
        if not sku:
            raise ValueError("sku must be a non-empty string")
        return self._client.get(
            "/v3/inventory",
            params={"sku": sku},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def set_inventory(
        self,
        *,
        sku: str,
        quantity: int,
        unit: str = "EACH",
    ) -> dict[str, Any]:
        """Update inventory for a SKU (absolute count).

        Returns the inventory record.
        """
        if not sku:
            raise ValueError("sku must be a non-empty string")
        return self._client.put(
            "/v3/inventory",
            params={"sku": sku},
            json={
                "sku": sku,
                "quantity": {"unit": unit, "amount": quantity},
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_feeds(self, *, feed_id: str | None = None) -> dict[str, Any]:
        """List feeds (or one feed if ``feed_id`` is provided).

        Useful for checking processing status of price/inventory/listing
        updates.
        """
        params: dict[str, Any] = {}
        if feed_id is not None:
            params["feedId"] = feed_id
        return self._client.get(
            "/v3/feeds",
            params=params or None,
        ).json()
