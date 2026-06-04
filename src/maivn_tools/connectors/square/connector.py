"""Square REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

_API_VERSION = "2026-01-22"


def _format_money(money: Any) -> str:
    """Format a Square ``Money`` object as ``"12.34 USD"``."""
    if not isinstance(money, dict):
        return ""
    money_dict = cast(dict[str, Any], money)
    amount: Any = money_dict.get("amount")
    if amount is None:
        return ""
    currency: Any = money_dict.get("currency") or ""
    try:
        amount_int = int(str(amount))
    except (TypeError, ValueError):
        return ""
    return f"{amount_int / 100:.2f} {currency}".strip()


def _coerce_id(candidate: Any, *, keys: tuple[str, ...] = ("id",)) -> str:
    """Resolve a raw ID from dict/string/list returned by Square tools."""
    if isinstance(candidate, str) and candidate:
        return candidate
    if isinstance(candidate, dict):
        candidate_dict = cast(dict[str, Any], candidate)
        for key in keys:
            value: Any = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
        for nested in candidate_dict.values():
            nested_value: Any = nested
            if isinstance(nested_value, dict | list | tuple):
                try:
                    return _coerce_id(nested_value, keys=keys)
                except ValueError:
                    continue
    if isinstance(candidate, list | tuple):
        candidate_seq = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in candidate_seq:
            item_value: Any = item
            try:
                return _coerce_id(item_value, keys=keys)
            except ValueError:
                continue
    raise ValueError("could not resolve a Square ID from the given input")


@toolset(prefix="square")
class SquareToolSet:
    """A connector for the Square REST API.

    Plug into an Agent with ``agent.add_toolset(SquareToolSet(access_token=...))``
    and the agent can answer questions about customers, orders, payments,
    refunds, catalog, and inventory.

    Args:
        access_token: OAuth bearer or PAT.
        square_version: ``Square-Version`` header value.
        base_url: API root. Use the sandbox URL for testing.
    """

    metadata = ProviderMetadata(
        name="square",
        display_name="Square",
        version="0.1.0",
        description="Customers, orders, payments, refunds, catalog, inventory, locations.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE, AuthMode.BEARER),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.squareup.com/reference/square",
        homepage_url="https://squareup.com/",
        tags=("payments", "commerce", "retail"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        square_version: str = _API_VERSION,
        base_url: str = "https://connect.squareup.com",
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
                "Square-Version": square_version,
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_locations(self) -> dict[str, Any]:
        """List Square locations (stores, restaurants, kiosks).

        Returns the raw Square response with ``locations``. Each location
        has ``id``, ``name``, ``address``, and ``status``.
        """
        return self._client.get("/v2/locations").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_customers(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        sort_field: str | None = None,
        sort_order: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Square customers.

        Returns compact summaries with a stable ``customer_ref``
        (``customer_1``, ...). Each entry includes name, email, phone, and
        the customer's reference ID for follow-up tools. ``limit`` defaults
        to 25 if not provided. Raw Square IDs are omitted unless
        ``include_ids=True``.
        """
        effective_limit = 25 if limit is None else int(limit)
        if effective_limit < 1 or effective_limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": effective_limit}
        if cursor is not None:
            params["cursor"] = cursor
        if sort_field is not None:
            params["sort_field"] = sort_field
        if sort_order is not None:
            params["sort_order"] = sort_order
        payload: Any = self._client.get("/v2/customers", params=params or None).json()
        payload_dict: dict[str, Any] | None = (
            cast(dict[str, Any], payload) if isinstance(payload, dict) else None
        )
        customers: list[Any] = payload_dict.get("customers", []) if payload_dict is not None else []
        summaries: list[dict[str, Any]] = []
        for index, customer in enumerate(customers, start=1):
            if not isinstance(customer, dict):
                continue
            customer_dict = cast(dict[str, Any], customer)
            given_name: Any = customer_dict.get("given_name", "")
            family_name: Any = customer_dict.get("family_name", "")
            name: str = f"{given_name} {family_name}".strip() or customer_dict.get(
                "company_name", ""
            )
            summary: dict[str, Any] = {
                "customer_ref": f"customer_{index}",
                "name": name,
                "company": customer_dict.get("company_name", ""),
                "email": customer_dict.get("email_address", ""),
                "phone": customer_dict.get("phone_number", ""),
                "reference_id": customer_dict.get("reference_id", ""),
                "created_at": customer_dict.get("created_at"),
            }
            if include_ids:
                summary["customer_id"] = customer_dict.get("id", "")
            summaries.append(summary)
        return {
            "customers": summaries,
            "cursor": payload_dict.get("cursor") if payload_dict is not None else None,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_customer(self, customer_id: str) -> dict[str, Any]:
        """Return one customer's full record by Square ID."""
        if not customer_id:
            raise ValueError("customer_id must be a non-empty string")
        return self._client.get(f"/v2/customers/{customer_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_customer(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Create a customer. ``fields`` is the Square customer payload."""
        if not fields:
            raise ValueError("fields must be non-empty")
        return self._client.post("/v2/customers", json=fields).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_customer(self, customer_id: Any, fields: dict[str, Any]) -> dict[str, Any]:
        """Update a customer.

        ``customer_id`` accepts a raw ID string or a dict from
        :meth:`list_customers` / :meth:`get_customer` (with
        ``include_ids=True``). Returns the updated customer resource.
        """
        resolved = _coerce_id(customer_id, keys=("customer_id", "id"))
        if not fields:
            raise ValueError("fields must be non-empty")
        return self._client.put(f"/v2/customers/{resolved}", json=fields).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_customer(self, customer_id: Any) -> dict[str, Any]:
        """Permanently delete a customer.

        Destructive — confirm with the user. Accepts a raw ID or dict from
        list/get tools.
        """
        resolved = _coerce_id(customer_id, keys=("customer_id", "id"))
        return self._client.delete(f"/v2/customers/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_orders(self, query: dict[str, Any]) -> dict[str, Any]:
        """Search orders using Square's filter syntax.

        Returns the raw Square ``SearchOrders`` response. Pass
        ``{"location_ids": [...], "query": {...}}`` to filter.
        """
        if not query:
            raise ValueError("query must be non-empty")
        return self._client.post("/v2/orders/search", json=query).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_order(self, order_id: str) -> dict[str, Any]:
        """Return one order by Square ID."""
        if not order_id:
            raise ValueError("order_id must be a non-empty string")
        return self._client.get(f"/v2/orders/{order_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_order(
        self,
        *,
        location_id: str,
        order: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create an order at ``location_id``. Returns the new order."""
        if not location_id or not order:
            raise ValueError("location_id and order must be non-empty")
        body: dict[str, Any] = {"order": {**order, "location_id": location_id}}
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        return self._client.post("/v2/orders", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_payments(
        self,
        *,
        begin_time: str | None = None,
        end_time: str | None = None,
        location_id: str | None = None,
        cursor: str | None = None,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List payments processed through Square.

        Returns compact summaries with ``payment_ref``, amount (formatted
        with currency), status, receipt URL, and source type. Raw payment
        IDs are omitted unless ``include_ids=True`` (needed for
        :meth:`refund_payment`).
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if begin_time is not None:
            params["begin_time"] = begin_time
        if end_time is not None:
            params["end_time"] = end_time
        if location_id is not None:
            params["location_id"] = location_id
        if cursor is not None:
            params["cursor"] = cursor
        payload: Any = self._client.get("/v2/payments", params=params or None).json()
        payload_dict: dict[str, Any] | None = (
            cast(dict[str, Any], payload) if isinstance(payload, dict) else None
        )
        payments: list[Any] = payload_dict.get("payments", []) if payload_dict is not None else []
        summaries: list[dict[str, Any]] = []
        for index, payment in enumerate(payments, start=1):
            if not isinstance(payment, dict):
                continue
            payment_dict = cast(dict[str, Any], payment)
            summary: dict[str, Any] = {
                "payment_ref": f"payment_{index}",
                "amount": _format_money(payment_dict.get("amount_money")),
                "tip": _format_money(payment_dict.get("tip_money")),
                "status": payment_dict.get("status", ""),
                "source_type": payment_dict.get("source_type", ""),
                "note": payment_dict.get("note", ""),
                "receipt_url": payment_dict.get("receipt_url", ""),
                "created_at": payment_dict.get("created_at"),
            }
            if include_ids:
                summary["payment_id"] = payment_dict.get("id", "")
                summary["order_id"] = payment_dict.get("order_id", "")
                summary["customer_id"] = payment_dict.get("customer_id", "")
            summaries.append(summary)
        return {
            "payments": summaries,
            "cursor": payload_dict.get("cursor") if payload_dict is not None else None,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_payment(
        self,
        *,
        source_id: str,
        amount_money: dict[str, Any],
        idempotency_key: str,
        order_id: str | None = None,
        customer_id: str | None = None,
        autocomplete: bool | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Create a payment.

        ``amount_money`` is ``{"amount": <minor units>, "currency": "USD"}``.
        ``idempotency_key`` should be a unique UUID-like string. Confirm
        amount and recipient with the user before calling.
        """
        if not source_id or not amount_money or not idempotency_key:
            raise ValueError("source_id, amount_money, and idempotency_key must be non-empty")
        body: dict[str, Any] = {
            "source_id": source_id,
            "amount_money": amount_money,
            "idempotency_key": idempotency_key,
        }
        if order_id is not None:
            body["order_id"] = order_id
        if customer_id is not None:
            body["customer_id"] = customer_id
        if autocomplete is not None:
            body["autocomplete"] = autocomplete
        if note is not None:
            body["note"] = note
        return self._client.post("/v2/payments", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def refund_payment(
        self,
        *,
        idempotency_key: str,
        amount_money: dict[str, Any],
        payment_id: Any,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Refund a payment. Destructive — money moves back to the customer.

        ``payment_id`` accepts the raw ID or the dict from
        :meth:`list_payments` (with ``include_ids=True``). Always confirm
        with the user before calling. Returns the new refund resource.
        """
        resolved = _coerce_id(payment_id, keys=("payment_id", "id"))
        if not idempotency_key:
            raise ValueError("idempotency_key must be non-empty")
        if not amount_money:
            raise ValueError("amount_money must be non-empty")
        body: dict[str, Any] = {
            "idempotency_key": idempotency_key,
            "amount_money": amount_money,
            "payment_id": resolved,
        }
        if reason is not None:
            body["reason"] = reason
        return self._client.post("/v2/refunds", json=body).json()

    # MARK: - Catalog & inventory

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_catalog(self, query: dict[str, Any]) -> dict[str, Any]:
        """Search catalog objects (items, taxes, modifiers).

        Returns the raw Square catalog response.
        """
        if not query:
            raise ValueError("query must be non-empty")
        return self._client.post("/v2/catalog/search", json=query).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upsert_catalog_object(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Upsert a catalog object. Returns the upserted object."""
        if not payload:
            raise ValueError("payload must be non-empty")
        return self._client.post("/v2/catalog/object", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_inventory_counts(
        self,
        *,
        location_ids: list[str] | None = None,
        catalog_object_ids: list[str] | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Batch-read inventory counts.

        Returns ``{"counts": [...]}`` with the current quantity of each
        catalog object at each location.
        """
        body: dict[str, Any] = {}
        if location_ids is not None:
            body["location_ids"] = location_ids
        if catalog_object_ids is not None:
            body["catalog_object_ids"] = catalog_object_ids
        if cursor is not None:
            body["cursor"] = cursor
        return self._client.post(
            "/v2/inventory/counts/batch-retrieve",
            json=body,
        ).json()
