# pyright: strict
"""Adobe Commerce (Magento) REST API V1 connector."""

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.bearer import BearerTokenAuth
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


def _coerce_sku(candidate: Any) -> str:
    """Accept a dict from list/get or a raw SKU string and return the SKU."""
    if isinstance(candidate, dict):
        mapping = cast(dict[str, Any], candidate)
        for key in ("sku", "product_sku"):
            value = mapping.get(key)
            if isinstance(value, str) and value:
                return value
    if isinstance(candidate, str) and candidate:
        return candidate
    type_name = type(cast(object, candidate)).__name__
    raise ValueError(f"sku is required (got: {type_name})")


# MARK: ToolSet


@toolset(prefix="magento")
class MagentoToolSet:
    """A connector for Magento / Adobe Commerce V1 REST API."""

    metadata = ProviderMetadata(
        name="magento",
        display_name="Adobe Commerce (Magento)",
        version="0.1.0",
        description="Products, customers, orders, and inventory.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.adobe.com/commerce/webapi/rest/",
        homepage_url="https://business.adobe.com/products/magento/magento-commerce.html",
        tags=("ecommerce",),
    )

    def __init__(
        self,
        *,
        base_url: str,
        access_token: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not base_url or not access_token:
            raise ValueError("base_url and access_token are required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(access_token),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
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
            "price": product.get("price"),
            "status": product.get("status"),
            "type_id": product.get("type_id", ""),
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
        first = order.get("customer_firstname") or ""
        last = order.get("customer_lastname") or ""
        email = order.get("customer_email") or ""
        summary: dict[str, Any] = {
            "order_ref": f"order_{index}",
            "order_number": order.get("increment_id") or order.get("entity_id", ""),
            "customer_name": f"{first} {last}".strip() or email,
            "customer_email": email,
            "grand_total": order.get("grand_total", ""),
            "currency": order.get("order_currency_code", ""),
            "status": order.get("status", ""),
            "created_at": order.get("created_at", ""),
        }
        if include_ids:
            summary["order_id"] = order.get("entity_id")
        return summary

    @staticmethod
    def _customer_summary(
        customer: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        first = customer.get("firstname") or ""
        last = customer.get("lastname") or ""
        summary: dict[str, Any] = {
            "customer_ref": f"customer_{index}",
            "name": f"{first} {last}".strip() or customer.get("email", ""),
            "email": customer.get("email", ""),
            "group_id": customer.get("group_id"),
        }
        if include_ids:
            summary["customer_id"] = customer.get("id")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_PRODUCTS_OUTPUT)
    def list_products(
        self,
        *,
        page_size: int = 20,
        current_page: int = 1,
        filters: list[dict[str, str]] | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List products with optional search criteria filters.

        Best first tool for catalog exploration. Returns compact summaries
        with ``product_ref`` plus name, sku, price, status. Each
        ``filters`` entry is a dict like ``{"field": "name", "value": "Hat",
        "condition_type": "like"}``. Raw IDs are omitted by default.
        """
        params: dict[str, Any] = {
            "searchCriteria[pageSize]": page_size,
            "searchCriteria[currentPage]": current_page,
        }
        if filters:
            for i, f in enumerate(filters):
                for k, v in f.items():
                    # Magento's GET query string requires snake_case keys
                    # (filter_groups / condition_type); camelCase variants are
                    # silently ignored, returning the full unfiltered page.
                    key = "condition_type" if k in ("condition_type", "conditionType") else k
                    params[f"searchCriteria[filter_groups][0][filters][{i}][{key}]"] = v
        payload: dict[str, Any] = self._client.get(
            "/rest/V1/products",
            params=params,
        ).json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("items") or []
        summaries: list[dict[str, Any]] = [
            self._product_summary(cast(dict[str, Any], p), index=i, include_ids=include_ids)
            for i, p in enumerate(items, start=1)
            if isinstance(p, dict)
        ]
        return {
            "products": summaries,
            "count": len(summaries),
            "total_count": payload.get("total_count"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_product(self, sku: str) -> dict[str, Any]:
        """Return full details for one product by SKU.

        SKUs are user-facing identifiers — use them in final answers.
        """
        if not sku:
            raise ValueError("sku must be a non-empty string")
        from urllib.parse import quote

        return self._client.get(f"/rest/V1/products/{quote(sku, safe='')}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upsert_product(self, product: dict[str, Any]) -> dict[str, Any]:
        """Create or update a product (requires ``sku`` inside ``product``).

        Returns the new/updated product resource.
        """
        if not product:
            raise ValueError("product must be non-empty")
        sku = product.get("sku")
        if not sku:
            raise ValueError("product.sku is required")
        from urllib.parse import quote

        return self._client.put(
            f"/rest/V1/products/{quote(sku, safe='')}",
            json={"product": product},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_product(self, sku: Any) -> dict[str, Any]:
        """Permanently delete a product by SKU. Destructive — confirm with the user first.

        Tolerant inputs: ``sku`` may be a raw string or a dict returned by
        ``list_products`` / ``get_product``.
        """
        resolved_sku = _coerce_sku(sku)
        from urllib.parse import quote

        return self._client.delete(
            f"/rest/V1/products/{quote(resolved_sku, safe='')}",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_ORDERS_OUTPUT)
    def list_orders(
        self,
        *,
        page_size: int = 20,
        current_page: int = 1,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List orders with compact summaries.

        Returns compact summaries with ``order_ref`` plus order_number
        (increment_id), customer_name, grand_total, status. Raw IDs
        omitted by default.
        """
        payload: dict[str, Any] = self._client.get(
            "/rest/V1/orders",
            params={
                "searchCriteria[pageSize]": page_size,
                "searchCriteria[currentPage]": current_page,
            },
        ).json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("items") or []
        summaries: list[dict[str, Any]] = [
            self._order_summary(cast(dict[str, Any], o), index=i, include_ids=include_ids)
            for i, o in enumerate(items, start=1)
            if isinstance(o, dict)
        ]
        return {
            "orders": summaries,
            "count": len(summaries),
            "total_count": payload.get("total_count"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_order(self, order_id: int) -> dict[str, Any]:
        """Return one order by its internal entity_id.

        Use after ``list_orders(include_ids=True)``.
        """
        return self._client.get(f"/rest/V1/orders/{order_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_CUSTOMERS_OUTPUT)
    def list_customers(
        self,
        *,
        page_size: int = 20,
        current_page: int = 1,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List customers with compact summaries.

        Returns compact summaries with ``customer_ref`` plus name, email,
        group_id.
        """
        payload: dict[str, Any] = self._client.get(
            "/rest/V1/customers/search",
            params={
                "searchCriteria[pageSize]": page_size,
                "searchCriteria[currentPage]": current_page,
            },
        ).json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("items") or []
        summaries: list[dict[str, Any]] = [
            self._customer_summary(cast(dict[str, Any], c), index=i, include_ids=include_ids)
            for i, c in enumerate(items, start=1)
            if isinstance(c, dict)
        ]
        return {
            "customers": summaries,
            "count": len(summaries),
            "total_count": payload.get("total_count"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def set_stock_item(
        self,
        *,
        sku: str,
        qty: float,
        is_in_stock: bool = True,
        item_id: int | None = None,
    ) -> dict[str, Any]:
        """Update inventory for a SKU's stock item.

        Returns the inventory record. Use for absolute stock counts after
        receiving shipments. When ``item_id`` is omitted it is resolved via
        ``GET /V1/stockItems/{sku}`` (the stock item id is not guaranteed to
        be ``1``).
        """
        if not sku:
            raise ValueError("sku must be a non-empty string")
        from urllib.parse import quote

        quoted_sku = quote(sku, safe="")
        resolved_item_id = item_id
        if resolved_item_id is None:
            stock: dict[str, Any] = self._client.get(f"/rest/V1/stockItems/{quoted_sku}").json()
            resolved_item_id = stock.get("item_id")
        if resolved_item_id is None:
            raise ValueError(f"could not resolve stock item_id for sku {sku!r}")

        return self._client.put(
            f"/rest/V1/products/{quoted_sku}/stockItems/{resolved_item_id}",
            json={
                "stockItem": {"qty": qty, "is_in_stock": is_in_stock},
            },
        ).json()
