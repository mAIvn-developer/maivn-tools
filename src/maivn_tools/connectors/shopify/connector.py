# pyright: strict
"""Shopify Admin REST API connector."""

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import (
    LIST_CUSTOMERS_OUTPUT,
    LIST_ORDERS_OUTPUT,
    LIST_PRODUCTS_OUTPUT,
)

# MARK: Constants

# Current stable Admin API version. Shopify supports each version for ~12 months,
# so track the latest stable each quarter. See:
# https://shopify.dev/docs/api/admin-rest/usage/versioning
_API_VERSION = "2026-01"


# MARK: Helpers


def _coerce_resource_id(candidate: Any, *, field: str) -> str | int:
    """Accept a dict from list/get or a raw ID and return the ID.

    Tolerates the natural output shape of ``list_*`` / ``get_*`` tools so
    downstream write tools don't require the agent to extract IDs by hand.
    """
    type_name = type(candidate).__name__
    if isinstance(candidate, dict):
        candidate_dict = cast(dict[str, Any], candidate)
        for key in (field, "id"):
            value: Any = candidate_dict.get(key)
            if isinstance(value, str | int) and value:
                return value
        nested: Any = (
            candidate_dict.get("product")
            or candidate_dict.get("order")
            or candidate_dict.get("customer")
        )
        if isinstance(nested, dict):
            return _coerce_resource_id(nested, field=field)
    if isinstance(candidate, str | int) and candidate:
        return candidate
    raise ValueError(f"{field} is required (got: {type_name})")


# MARK: ToolSet


@toolset(prefix="shopify")
class ShopifyToolSet:
    """A connector for the Shopify Admin REST API.

    Args:
        shop: Shop subdomain, e.g. ``"acme"`` (becomes ``acme.myshopify.com``).
        access_token: Shopify admin access token (set in the
            ``X-Shopify-Access-Token`` header).
        api_version: Admin API version, e.g. ``"2026-01"``.
    """

    metadata = ProviderMetadata(
        name="shopify",
        display_name="Shopify",
        version="0.1.0",
        description="Products, customers, orders, fulfillments, and inventory.",
        auth_modes=(AuthMode.API_KEY, AuthMode.OAUTH2_AUTH_CODE),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://shopify.dev/docs/api/admin-rest",
        homepage_url="https://www.shopify.com/",
        tags=("ecommerce",),
    )

    def __init__(
        self,
        *,
        shop: str,
        access_token: str,
        api_version: str = _API_VERSION,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not shop or not access_token:
            raise ValueError("shop and access_token are required")
        self.connection = connection
        self._api_version = api_version
        self._client = HttpClient(
            base_url=f"https://{shop}.myshopify.com",
            auth=ApiKeyAuth(access_token, header="X-Shopify-Access-Token"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _path(self, suffix: str) -> str:
        return f"/admin/api/{self._api_version}{suffix}"

    @staticmethod
    def _product_summary(
        product: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        variants: list[Any] = product.get("variants") or []
        raw_first_variant: Any = variants[0] if variants else {}
        first_variant: dict[str, Any] = (
            cast(dict[str, Any], raw_first_variant) if isinstance(raw_first_variant, dict) else {}
        )
        summary: dict[str, Any] = {
            "product_ref": f"product_{index}",
            "title": product.get("title", ""),
            "status": product.get("status", ""),
            "vendor": product.get("vendor", ""),
            "product_type": product.get("product_type", ""),
            "sku": first_variant.get("sku", ""),
            "price": first_variant.get("price", ""),
            "inventory_quantity": product.get("total_inventory") or 0,
        }
        if include_ids:
            summary["product_id"] = product.get("id")
        return summary

    @staticmethod
    def _order_summary(
        order: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        customer: Any = order.get("customer") or {}
        customer_name = ""
        if isinstance(customer, dict):
            customer_obj = cast(dict[str, Any], customer)
            first: Any = customer_obj.get("first_name") or ""
            last: Any = customer_obj.get("last_name") or ""
            customer_name = f"{first} {last}".strip() or str(customer_obj.get("email", ""))
        summary: dict[str, Any] = {
            "order_ref": f"order_{index}",
            "order_number": order.get("name") or f"#{order.get('order_number', '')}",
            "customer_name": customer_name,
            "total_price": order.get("total_price", ""),
            "currency": order.get("currency", ""),
            "financial_status": order.get("financial_status", ""),
            "fulfillment_status": order.get("fulfillment_status") or "unfulfilled",
            "created_at": order.get("created_at", ""),
        }
        if include_ids:
            summary["order_id"] = order.get("id")
        return summary

    @staticmethod
    def _customer_summary(
        customer: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        first = customer.get("first_name") or ""
        last = customer.get("last_name") or ""
        full_name = f"{first} {last}".strip()
        summary: dict[str, Any] = {
            "customer_ref": f"customer_{index}",
            "name": full_name or customer.get("email", ""),
            "email": customer.get("email", ""),
            "orders_count": customer.get("orders_count", 0),
            "total_spent": customer.get("total_spent", ""),
            "state": customer.get("state", ""),
        }
        if include_ids:
            summary["customer_id"] = customer.get("id")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_shop(self) -> dict[str, Any]:
        """Return shop info (name, domain, currency, plan).

        Use once at startup to confirm the access token is valid and to read
        the shop's primary currency before quoting order totals.
        """
        return cast(dict[str, Any], self._client.get(self._path("/shop.json")).json())

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_PRODUCTS_OUTPUT)
    def list_products(
        self,
        *,
        limit: int = 25,
        page_info: str | None = None,
        status: str | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List storefront products.

        Best first tool for catalog exploration. Returns compact summaries
        with a stable ``product_ref`` (``product_1``, ``product_2``, ...)
        plus user-facing fields: title, status, vendor, sku, price. Raw
        Shopify product IDs are omitted by default — they are internal
        handles. Set ``include_ids=True`` only when ``update_product`` or
        ``delete_product`` needs them; set ``include_raw=True`` to return
        the unmodified provider payload. ``page_info`` is the opaque cursor
        Shopify returns in the ``Link`` response header.
        """
        if limit < 1 or limit > 250:
            raise ValueError("limit must be between 1 and 250")
        params: dict[str, Any] = {"limit": limit}
        if page_info is not None:
            params["page_info"] = page_info
        if status is not None:
            params["status"] = status
        payload: dict[str, Any] = self._client.get(
            self._path("/products.json"), params=params
        ).json()
        if include_raw:
            return payload
        products: list[Any] = payload.get("products") or []
        summaries = [
            self._product_summary(cast(dict[str, Any], p), index=i, include_ids=include_ids)
            for i, p in enumerate(products, start=1)
            if isinstance(p, dict)
        ]
        return {"products": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_product(self, product_id: int | str) -> dict[str, Any]:
        """Return full details for one product by ID.

        Use after ``list_products(include_ids=True)`` when you need
        descriptions, all variants, images, or metafields.
        """
        if not product_id:
            raise ValueError("product_id is required")
        return cast(
            dict[str, Any],
            self._client.get(self._path(f"/products/{product_id}.json")).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_product(self, product: dict[str, Any]) -> dict[str, Any]:
        """Create a product.

        ``product`` must contain at least a ``title``. Returns the new
        product resource (including the server-assigned ID).
        """
        if not product:
            raise ValueError("product must be non-empty")
        return cast(
            dict[str, Any],
            self._client.post(
                self._path("/products.json"),
                json={"product": product},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_product(
        self,
        product_id: Any,
        product: dict[str, Any],
    ) -> dict[str, Any]:
        """Update fields on an existing product.

        Tolerant inputs: ``product_id`` may be a raw ID or a dict returned
        by ``list_products(include_ids=True)`` / ``get_product``. Returns
        the updated product resource.
        """
        if not product:
            raise ValueError("product must be non-empty")
        resolved_id = _coerce_resource_id(product_id, field="product_id")
        return cast(
            dict[str, Any],
            self._client.put(
                self._path(f"/products/{resolved_id}.json"),
                json={"product": {"id": resolved_id, **product}},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_product(self, product_id: Any) -> dict[str, Any]:
        """Permanently delete a product. Destructive — confirm with the user first.

        Tolerant inputs: ``product_id`` may be a raw ID or a dict returned
        by ``list_products(include_ids=True)`` / ``get_product``.
        """
        if product_id in (None, "", 0):
            raise ValueError("product_id is required")
        resolved_id = _coerce_resource_id(product_id, field="product_id")
        self._client.delete(self._path(f"/products/{resolved_id}.json"))
        return {"id": resolved_id, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_ORDERS_OUTPUT)
    def list_orders(
        self,
        *,
        status: str = "any",
        limit: int = 25,
        financial_status: str | None = None,
        fulfillment_status: str | None = None,
        page_info: str | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List orders with compact, human-readable summaries.

        Best first tool for order triage. Returns compact summaries with a
        stable ``order_ref`` plus user-facing fields: order_number,
        customer_name, total_price, currency, financial_status,
        fulfillment_status. Raw Shopify order IDs are omitted by default —
        set ``include_ids=True`` when ``cancel_order`` / ``get_order`` will
        consume them, or ``include_raw=True`` for the unmodified payload.
        """
        if limit < 1 or limit > 250:
            raise ValueError("limit must be between 1 and 250")
        params: dict[str, Any] = {"status": status, "limit": limit}
        if financial_status is not None:
            params["financial_status"] = financial_status
        if fulfillment_status is not None:
            params["fulfillment_status"] = fulfillment_status
        if page_info is not None:
            params["page_info"] = page_info
        payload: dict[str, Any] = self._client.get(self._path("/orders.json"), params=params).json()
        if include_raw:
            return payload
        orders: list[Any] = payload.get("orders") or []
        summaries = [
            self._order_summary(cast(dict[str, Any], o), index=i, include_ids=include_ids)
            for i, o in enumerate(orders, start=1)
            if isinstance(o, dict)
        ]
        return {"orders": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_order(self, order_id: int | str) -> dict[str, Any]:
        """Return one order with all line items, addresses, and transactions.

        Use after ``list_orders(include_ids=True)`` to pull the full order
        record for refund/fulfillment work.
        """
        if not order_id:
            raise ValueError("order_id is required")
        return cast(
            dict[str, Any],
            self._client.get(self._path(f"/orders/{order_id}.json")).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_order(self, order: dict[str, Any]) -> dict[str, Any]:
        """Create an order (draft or with payment).

        Returns the new order resource. Use sparingly in agent loops —
        confirm line items, customer, and totals with the user first.
        """
        if not order:
            raise ValueError("order must be non-empty")
        return cast(
            dict[str, Any],
            self._client.post(
                self._path("/orders.json"),
                json={"order": order},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def cancel_order(
        self,
        order_id: Any,
        *,
        reason: str | None = None,
        refund: bool | None = None,
        restock: bool | None = None,
    ) -> dict[str, Any]:
        """Cancel an order. Destructive — confirm with the user first.

        Tolerant inputs: ``order_id`` may be a raw ID or a dict returned by
        ``list_orders(include_ids=True)`` / ``get_order``. ``reason`` is one
        of ``customer``, ``fraud``, ``inventory``, ``declined``, ``other``.
        """
        if order_id in (None, "", 0):
            raise ValueError("order_id is required")
        resolved_id = _coerce_resource_id(order_id, field="order_id")
        body: dict[str, Any] = {}
        if reason is not None:
            body["reason"] = reason
        if refund is not None:
            body["refund"] = refund
        if restock is not None:
            body["restock"] = restock
        return cast(
            dict[str, Any],
            self._client.post(
                self._path(f"/orders/{resolved_id}/cancel.json"),
                json=body or None,
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_CUSTOMERS_OUTPUT)
    def list_customers(
        self,
        *,
        limit: int = 25,
        page_info: str | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List customers with compact summaries.

        Returns compact summaries with a stable ``customer_ref`` plus
        user-facing fields: name, email, orders_count, total_spent. Raw
        customer IDs are omitted by default — set ``include_ids=True`` when
        downstream tools need them.
        """
        if limit < 1 or limit > 250:
            raise ValueError("limit must be between 1 and 250")
        params: dict[str, Any] = {"limit": limit}
        if page_info is not None:
            params["page_info"] = page_info
        payload: dict[str, Any] = self._client.get(
            self._path("/customers.json"), params=params
        ).json()
        if include_raw:
            return payload
        customers: list[Any] = payload.get("customers") or []
        summaries = [
            self._customer_summary(cast(dict[str, Any], c), index=i, include_ids=include_ids)
            for i, c in enumerate(customers, start=1)
            if isinstance(c, dict)
        ]
        return {"customers": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_customer(self, customer: dict[str, Any]) -> dict[str, Any]:
        """Create a customer (``email`` is required).

        Returns the new customer resource.
        """
        if not customer:
            raise ValueError("customer must be non-empty")
        return cast(
            dict[str, Any],
            self._client.post(
                self._path("/customers.json"),
                json={"customer": customer},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_customers(self, query: str, *, limit: int = 10) -> dict[str, Any]:
        """Search customers using Shopify search syntax.

        Example queries: ``email:alice@example.com``, ``last_name:Smith``,
        or a free-text token to fuzzy-match. Returns the raw provider
        payload — use ``list_customers`` for summary mode.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        return cast(
            dict[str, Any],
            self._client.get(
                self._path("/customers/search.json"),
                params={"query": query, "limit": limit},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_inventory_levels(
        self,
        *,
        location_ids: list[int] | None = None,
        inventory_item_ids: list[int] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List inventory levels.

        Returns the raw Shopify payload — provide ``location_ids`` and/or
        ``inventory_item_ids`` to scope the response.
        """
        params: dict[str, Any] = {"limit": limit}
        if location_ids is not None:
            params["location_ids"] = ",".join(str(x) for x in location_ids)
        if inventory_item_ids is not None:
            params["inventory_item_ids"] = ",".join(str(x) for x in inventory_item_ids)
        return cast(
            dict[str, Any],
            self._client.get(
                self._path("/inventory_levels.json"),
                params=params,
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def set_inventory_level(
        self,
        *,
        inventory_item_id: int,
        location_id: int,
        available: int,
    ) -> dict[str, Any]:
        """Set the absolute available count for an inventory item at a location.

        Returns the updated inventory level. Use for stock counts after
        receiving shipments; use ``adjust_inventory`` (not in this surface)
        for relative deltas.
        """
        return cast(
            dict[str, Any],
            self._client.post(
                self._path("/inventory_levels/set.json"),
                json={
                    "inventory_item_id": inventory_item_id,
                    "location_id": location_id,
                    "available": available,
                },
            ).json(),
        )

    def _list_fulfillment_orders(self, order_id: int | str) -> list[dict[str, Any]]:
        """Return the open fulfillment orders for an order.

        The order-scoped ``/orders/{id}/fulfillments.json`` create endpoint was
        removed in API version 2022-07; the Fulfillment Orders workflow is the
        only supported REST path. See:
        https://shopify.dev/changelog/some-endpoint-deprecations-on-the-fulfillment-api-and-the-introduction-of-fulfillment-order-api
        """
        payload: dict[str, Any] = self._client.get(
            self._path(f"/orders/{order_id}/fulfillment_orders.json")
        ).json()
        orders: list[Any] = payload.get("fulfillment_orders") or []
        return [cast(dict[str, Any], fo) for fo in orders if isinstance(fo, dict)]

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_fulfillment(
        self,
        *,
        order_id: int | str,
        tracking_info: dict[str, Any] | None = None,
        notify_customer: bool | None = None,
        line_items_by_fulfillment_order: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a fulfillment for an order (marks items as shipped).

        Uses the Fulfillment Orders workflow (the legacy order-scoped
        ``/orders/{id}/fulfillments.json`` endpoint was removed in API version
        2022-07). When ``line_items_by_fulfillment_order`` is omitted, every
        open fulfillment order on the order is fulfilled in full.

        Args:
            order_id: The order to fulfill.
            tracking_info: Optional ``{"number", "url", "company"}`` tracking
                details. REST supports a single tracking number/URL.
            notify_customer: Whether Shopify emails the customer.
            line_items_by_fulfillment_order: Explicit
                ``[{"fulfillment_order_id": ..., "fulfillment_order_line_items":
                [...]}]`` selection. If omitted, resolved automatically from the
                order's open fulfillment orders.

        Returns the new fulfillment resource.
        """
        if not order_id:
            raise ValueError("order_id is required")
        if line_items_by_fulfillment_order is None:
            fulfillment_orders = self._list_fulfillment_orders(order_id)
            line_items_by_fulfillment_order = [
                {"fulfillment_order_id": fo["id"]}
                for fo in fulfillment_orders
                if fo.get("id") is not None
            ]
            if not line_items_by_fulfillment_order:
                raise ValueError(f"order {order_id} has no open fulfillment orders")
        fulfillment: dict[str, Any] = {
            "line_items_by_fulfillment_order": line_items_by_fulfillment_order,
        }
        if tracking_info is not None:
            fulfillment["tracking_info"] = tracking_info
        if notify_customer is not None:
            fulfillment["notify_customer"] = notify_customer
        return cast(
            dict[str, Any],
            self._client.post(
                self._path("/fulfillments.json"),
                json={"fulfillment": fulfillment},
            ).json(),
        )
