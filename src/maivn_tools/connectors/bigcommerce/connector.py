# pyright: strict
"""BigCommerce REST API connector (V2/V3)."""

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Helpers


def _coerce_resource_id(candidate: Any, *, field: str) -> str | int:
    """Accept a dict from list/get or a raw ID and return the ID."""
    if isinstance(candidate, dict):
        candidate_dict = cast(dict[str, Any], candidate)
        for key in (field, "id"):
            value: Any = candidate_dict.get(key)
            if isinstance(value, str | int) and value:
                return value
    if isinstance(candidate, str | int) and candidate:
        return candidate
    type_name = type(cast(object, candidate)).__name__
    raise ValueError(f"{field} is required (got: {type_name})")


# MARK: Connector


@toolset(prefix="bigcommerce")
class BigCommerceToolSet:
    """A connector for the BigCommerce REST API."""

    metadata = ProviderMetadata(
        name="bigcommerce",
        display_name="BigCommerce",
        version="0.1.0",
        description="Catalog products, customers, orders, and carts.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.bigcommerce.com/docs/rest",
        homepage_url="https://www.bigcommerce.com/",
        tags=("ecommerce",),
    )

    def __init__(
        self,
        *,
        store_hash: str,
        access_token: str,
        base_url: str = "https://api.bigcommerce.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not store_hash or not access_token:
            raise ValueError("store_hash and access_token are required")
        self.connection = connection
        self._store_hash = store_hash
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(access_token, header="X-Auth-Token"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _v3(self, suffix: str) -> str:
        return f"/stores/{self._store_hash}/v3{suffix}"

    def _v2(self, suffix: str) -> str:
        return f"/stores/{self._store_hash}/v2{suffix}"

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
            "is_visible": product.get("is_visible"),
            "inventory_level": product.get("inventory_level"),
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
        first = order.get("billing_address", {}).get("first_name") or ""
        last = order.get("billing_address", {}).get("last_name") or ""
        email = order.get("billing_address", {}).get("email") or ""
        summary: dict[str, Any] = {
            "order_ref": f"order_{index}",
            "order_number": order.get("id", ""),
            "customer_name": f"{first} {last}".strip() or email,
            "customer_email": email,
            "total_inc_tax": order.get("total_inc_tax", ""),
            "currency_code": order.get("currency_code", ""),
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
            "company": customer.get("company", ""),
        }
        if include_ids:
            summary["customer_id"] = customer.get("id")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_products(
        self,
        *,
        limit: int = 25,
        page: int = 1,
        sku: str | None = None,
        keyword: str | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List catalog products.

        Best first tool for catalog exploration. Returns compact summaries
        with ``product_ref`` plus name, sku, price. Raw product IDs are
        omitted by default — set ``include_ids=True`` when downstream tools
        need them, or ``include_raw=True`` for the unmodified payload.
        """
        if limit < 1 or limit > 250:
            raise ValueError("limit must be between 1 and 250")
        params: dict[str, Any] = {"limit": limit, "page": page}
        if sku is not None:
            params["sku"] = sku
        if keyword is not None:
            params["keyword"] = keyword
        payload: dict[str, Any] = self._client.get(
            self._v3("/catalog/products"), params=params
        ).json()
        if include_raw:
            return payload
        products: list[Any] = payload.get("data") or []
        summaries = [
            self._product_summary(cast(dict[str, Any], p), index=i, include_ids=include_ids)
            for i, p in enumerate(products, start=1)
            if isinstance(p, dict)
        ]
        return {
            "products": summaries,
            "count": len(summaries),
            "meta": payload.get("meta"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_product(self, product: dict[str, Any]) -> dict[str, Any]:
        """Create a product (requires ``name``, ``price``, ``weight``, ``type``).

        Returns the new product resource.
        """
        if not product:
            raise ValueError("product must be non-empty")
        return self._client.post(self._v3("/catalog/products"), json=product).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_product(self, product_id: Any, fields: dict[str, Any]) -> dict[str, Any]:
        """Update fields on a product.

        Tolerant inputs: ``product_id`` may be a raw integer ID or a dict
        returned by ``list_products(include_ids=True)``.
        """
        if not fields:
            raise ValueError("fields must be non-empty")
        resolved_id = _coerce_resource_id(product_id, field="product_id")
        return self._client.put(
            self._v3(f"/catalog/products/{resolved_id}"),
            json=fields,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_product(self, product_id: Any) -> dict[str, Any]:
        """Permanently delete a product. Destructive — confirm with the user first.

        Tolerant inputs: ``product_id`` may be a raw ID or a dict returned by
        ``list_products(include_ids=True)``.
        """
        if product_id in (None, "", 0):
            raise ValueError("product_id is required")
        resolved_id = _coerce_resource_id(product_id, field="product_id")
        self._client.delete(self._v3(f"/catalog/products/{resolved_id}"))
        return {"id": resolved_id, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_orders(
        self,
        *,
        limit: int = 25,
        page: int = 1,
        status_id: int | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List orders (v2 API).

        Returns compact summaries with ``order_ref`` plus order_number,
        customer_name, total. Raw IDs omitted by default.
        """
        if limit < 1 or limit > 250:
            raise ValueError("limit must be between 1 and 250")
        params: dict[str, Any] = {"limit": limit, "page": page}
        if status_id is not None:
            params["status_id"] = status_id
        payload: Any = self._client.get(self._v2("/orders"), params=params).json()
        if include_raw:
            return cast(dict[str, Any], payload)
        orders: list[Any] = (
            cast(list[Any], payload) if isinstance(payload, list) else (payload.get("data") or [])
        )
        summaries = [
            self._order_summary(cast(dict[str, Any], o), index=i, include_ids=include_ids)
            for i, o in enumerate(orders, start=1)
            if isinstance(o, dict)
        ]
        return {"orders": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_order(self, order_id: int) -> dict[str, Any]:
        """Return full details for one order by ID.

        Use after ``list_orders(include_ids=True)``.
        """
        return self._client.get(self._v2(f"/orders/{order_id}")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_customers(
        self,
        *,
        limit: int = 25,
        page: int = 1,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List customers with compact summaries.

        Returns compact summaries with ``customer_ref`` plus name, email,
        company. Raw IDs omitted by default.
        """
        if limit < 1 or limit > 250:
            raise ValueError("limit must be between 1 and 250")
        payload: dict[str, Any] = self._client.get(
            self._v3("/customers"),
            params={"limit": limit, "page": page},
        ).json()
        if include_raw:
            return payload
        customers: list[Any] = payload.get("data") or []
        summaries = [
            self._customer_summary(cast(dict[str, Any], c), index=i, include_ids=include_ids)
            for i, c in enumerate(customers, start=1)
            if isinstance(c, dict)
        ]
        return {"customers": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_customers(self, customers: list[dict[str, Any]]) -> dict[str, Any]:
        """Bulk-create customers (up to 10 per call).

        Each customer needs at least ``first_name``, ``last_name``,
        ``email``. Returns the new customer resources.
        """
        if not customers:
            raise ValueError("customers must be non-empty")
        return self._client.post(self._v3("/customers"), json=customers).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_cart(self, cart_id: Any) -> dict[str, Any]:
        """Return one cart by its ID.

        The BigCommerce Server Carts API has no list-all endpoint; carts are
        retrievable only by ID (obtained from a prior create/checkout flow).

        Tolerant inputs: ``cart_id`` may be a raw ID string or a dict
        containing a ``cart_id``/``id`` key. Returns the raw provider payload.
        """
        resolved_id = _coerce_resource_id(cart_id, field="cart_id")
        return self._client.get(self._v3(f"/carts/{resolved_id}")).json()
