# pyright: strict
"""WooCommerce REST API v3 connector."""

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import (
    LIST_CUSTOMERS_OUTPUT,
    LIST_ORDERS_OUTPUT,
    LIST_PRODUCTS_OUTPUT,
)

# MARK: Helpers


def _coerce_resource_id(candidate: Any, *, field: str) -> str | int:
    """Accept a dict from list/get or a raw ID and return the ID."""
    if isinstance(candidate, dict):
        mapping = cast(dict[str, Any], candidate)
        for key in (field, "id"):
            value: Any = mapping.get(key)
            if isinstance(value, str | int) and value:
                return value
    if isinstance(candidate, str | int) and candidate:
        return candidate
    type_name = type(cast(object, candidate)).__name__
    raise ValueError(f"{field} is required (got: {type_name})")


# MARK: ToolSet


@toolset(prefix="woo")
class WooCommerceToolSet:
    """A connector for the WooCommerce REST API v3."""

    metadata = ProviderMetadata(
        name="woocommerce",
        display_name="WooCommerce",
        version="0.1.0",
        description="Products, customers, orders, coupons, and reports.",
        auth_modes=(AuthMode.BASIC,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://woocommerce.github.io/woocommerce-rest-api-docs/",
        homepage_url="https://woocommerce.com/",
        tags=("ecommerce", "wordpress"),
    )

    def __init__(
        self,
        *,
        site_url: str,
        consumer_key: str,
        consumer_secret: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not site_url or not consumer_key or not consumer_secret:
            raise ValueError("site_url, consumer_key, and consumer_secret are required")
        self.connection = connection
        self._client = HttpClient(
            base_url=site_url.rstrip("/"),
            auth=BasicAuth(consumer_key, consumer_secret),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @staticmethod
    def _product_summary(
        product: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "product_ref": f"product_{index}",
            "name": product.get("name", ""),
            "sku": product.get("sku", ""),
            "price": product.get("price", ""),
            "status": product.get("status", ""),
            "stock_status": product.get("stock_status", ""),
            "stock_quantity": product.get("stock_quantity"),
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
        raw_billing: Any = order.get("billing") or {}
        billing: dict[str, Any] = (
            cast(dict[str, Any], raw_billing) if isinstance(raw_billing, dict) else {}
        )
        first = billing.get("first_name") or ""
        last = billing.get("last_name") or ""
        email = billing.get("email") or ""
        summary: dict[str, Any] = {
            "order_ref": f"order_{index}",
            "order_number": order.get("number") or order.get("id", ""),
            "customer_name": f"{first} {last}".strip() or email,
            "customer_email": email,
            "total": order.get("total", ""),
            "currency": order.get("currency", ""),
            "status": order.get("status", ""),
            "date_created": order.get("date_created", ""),
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
        summary: dict[str, Any] = {
            "customer_ref": f"customer_{index}",
            "name": f"{first} {last}".strip() or customer.get("email", ""),
            "email": customer.get("email", ""),
            "username": customer.get("username", ""),
            "role": customer.get("role", ""),
        }
        if include_ids:
            summary["customer_id"] = customer.get("id")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_PRODUCTS_OUTPUT)
    def list_products(
        self,
        *,
        per_page: int = 25,
        page: int = 1,
        search: str | None = None,
        status: str | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List storefront products.

        Best first tool for catalog exploration. Returns compact summaries
        with a stable ``product_ref`` plus user-facing fields: name, sku,
        price, status. Raw WooCommerce product IDs are omitted by default
        — set ``include_ids=True`` for downstream ``update_product`` /
        ``delete_product`` calls, or ``include_raw=True`` for the
        unmodified payload.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        if search is not None:
            params["search"] = search
        if status is not None:
            params["status"] = status
        payload: Any = self._client.get(
            "/wp-json/wc/v3/products",
            params=params,
        ).json()
        if include_raw:
            return cast(dict[str, Any], payload)
        products: list[Any] = (
            cast(list[Any], payload)
            if isinstance(payload, list)
            else cast(list[Any], payload.get("products") or [])
        )
        summaries = [
            self._product_summary(cast(dict[str, Any], p), index=i, include_ids=include_ids)
            for i, p in enumerate(products, start=1)
            if isinstance(p, dict)
        ]
        return {"products": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_product(self, product_id: int | str) -> dict[str, Any]:
        """Return full details for one product by ID.

        Use after ``list_products(include_ids=True)`` for description,
        variations, images, and metadata.
        """
        if not product_id:
            raise ValueError("product_id is required")
        return self._client.get(f"/wp-json/wc/v3/products/{product_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_product(self, product: dict[str, Any]) -> dict[str, Any]:
        """Create a product (requires at least ``name``).

        Returns the new product resource (with its server-assigned ID).
        """
        if not product:
            raise ValueError("product must be non-empty")
        return self._client.post(
            "/wp-json/wc/v3/products",
            json=product,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_product(self, product_id: Any, fields: dict[str, Any]) -> dict[str, Any]:
        """Update fields on an existing product.

        Tolerant inputs: ``product_id`` may be a raw ID or a dict returned
        by ``list_products(include_ids=True)`` / ``get_product``. Returns
        the updated product resource.
        """
        if not fields:
            raise ValueError("fields must be non-empty")
        resolved_id = _coerce_resource_id(product_id, field="product_id")
        return self._client.put(
            f"/wp-json/wc/v3/products/{resolved_id}",
            json=fields,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_product(self, product_id: Any, *, force: bool = False) -> dict[str, Any]:
        """Delete a product (sends to trash by default; force=True permanently deletes).

        Destructive — confirm with the user first. Tolerant inputs:
        ``product_id`` may be a raw ID or a dict returned by
        ``list_products(include_ids=True)`` / ``get_product``.
        """
        if product_id in (None, "", 0):
            raise ValueError("product_id is required")
        resolved_id = _coerce_resource_id(product_id, field="product_id")
        return self._client.delete(
            f"/wp-json/wc/v3/products/{resolved_id}",
            params={"force": str(force).lower()},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_ORDERS_OUTPUT)
    def list_orders(
        self,
        *,
        per_page: int = 25,
        page: int = 1,
        status: str | None = None,
        customer: int | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List orders with compact summaries.

        Returns compact summaries with ``order_ref`` plus order_number,
        customer_name, customer_email, total, currency, status. Raw
        WooCommerce order IDs are omitted by default — set
        ``include_ids=True`` when ``update_order`` needs them.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        if status is not None:
            params["status"] = status
        if customer is not None:
            params["customer"] = customer
        payload: Any = self._client.get(
            "/wp-json/wc/v3/orders",
            params=params,
        ).json()
        if include_raw:
            return cast(dict[str, Any], payload)
        orders: list[Any] = (
            cast(list[Any], payload)
            if isinstance(payload, list)
            else cast(list[Any], payload.get("orders") or [])
        )
        summaries = [
            self._order_summary(cast(dict[str, Any], o), index=i, include_ids=include_ids)
            for i, o in enumerate(orders, start=1)
            if isinstance(o, dict)
        ]
        return {"orders": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_order(self, order: dict[str, Any]) -> dict[str, Any]:
        """Create an order.

        Confirm line items and customer with the user before calling.
        Returns the new order resource.
        """
        if not order:
            raise ValueError("order must be non-empty")
        return self._client.post("/wp-json/wc/v3/orders", json=order).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_order(self, order_id: Any, fields: dict[str, Any]) -> dict[str, Any]:
        """Update an order (e.g. set status to ``completed``, ``cancelled``).

        Tolerant inputs: ``order_id`` may be a raw ID or a dict returned by
        ``list_orders(include_ids=True)``. Setting ``status=cancelled``
        cancels the order; agents should confirm before doing so.
        """
        if not fields:
            raise ValueError("fields must be non-empty")
        resolved_id = _coerce_resource_id(order_id, field="order_id")
        return self._client.put(
            f"/wp-json/wc/v3/orders/{resolved_id}",
            json=fields,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_CUSTOMERS_OUTPUT)
    def list_customers(
        self,
        *,
        per_page: int = 25,
        page: int = 1,
        search: str | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List customers with compact summaries.

        Returns compact summaries with ``customer_ref`` plus name, email,
        username, role. Raw IDs omitted by default.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        if search is not None:
            params["search"] = search
        payload: Any = self._client.get(
            "/wp-json/wc/v3/customers",
            params=params,
        ).json()
        if include_raw:
            return cast(dict[str, Any], payload)
        customers: list[Any] = (
            cast(list[Any], payload)
            if isinstance(payload, list)
            else cast(list[Any], payload.get("customers") or [])
        )
        summaries = [
            self._customer_summary(cast(dict[str, Any], c), index=i, include_ids=include_ids)
            for i, c in enumerate(customers, start=1)
            if isinstance(c, dict)
        ]
        return {"customers": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_coupon(self, coupon: dict[str, Any]) -> dict[str, Any]:
        """Create a coupon (requires ``code`` and ``discount_type``).

        Returns the new coupon resource.
        """
        if not coupon:
            raise ValueError("coupon must be non-empty")
        return self._client.post("/wp-json/wc/v3/coupons", json=coupon).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_reports(self) -> dict[str, Any]:
        """List available report types.

        Returns metadata about the report endpoints (sales, top sellers,
        etc.) — use the returned ``slug`` to query a specific report.
        """
        return self._client.get("/wp-json/wc/v3/reports").json()
