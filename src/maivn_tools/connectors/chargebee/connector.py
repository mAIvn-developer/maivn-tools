"""Chargebee API v2 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Helpers


def _format_amount(amount_minor: Any, currency: Any) -> str:
    """Format a Chargebee minor-unit amount as ``"12.34 USD"``."""
    if amount_minor is None:
        return ""
    try:
        amount_int = int(amount_minor)
    except (TypeError, ValueError):
        return ""
    code = str(currency or "").upper()
    return f"{amount_int / 100:.2f} {code}".strip()


def _coerce_id(candidate: Any, *, keys: tuple[str, ...] = ("id",)) -> str:
    """Resolve a raw Chargebee ID from a dict/string/list."""
    if isinstance(candidate, str) and candidate:
        return candidate
    if isinstance(candidate, dict):
        mapping = cast(dict[Any, Any], candidate)
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, str) and value:
                return value
        for nested in mapping.values():
            if isinstance(nested, dict | list | tuple):
                try:
                    return _coerce_id(nested, keys=keys)
                except ValueError:
                    continue
    if isinstance(candidate, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in sequence:
            try:
                return _coerce_id(item, keys=keys)
            except ValueError:
                continue
    raise ValueError("could not resolve a Chargebee ID from the given input")


# MARK: ToolSet


@toolset(prefix="chargebee")
class ChargebeeToolSet:
    """A connector for the Chargebee API v2.

    Plug into an Agent with ``agent.add_toolset(ChargebeeToolSet(site=...,
    api_key=...))`` and the agent can answer questions about customers,
    subscriptions, invoices, and plans.
    """

    metadata = ProviderMetadata(
        name="chargebee",
        display_name="Chargebee",
        version="0.1.0",
        description="Subscriptions, customers, invoices, plans, and credit notes.",
        auth_modes=(AuthMode.BASIC,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://apidocs.chargebee.com/docs/api",
        homepage_url="https://www.chargebee.com/",
        tags=("billing", "subscriptions"),
    )

    def __init__(
        self,
        *,
        site: str,
        api_key: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not site or not api_key:
            raise ValueError("site and api_key are required")
        self.connection = connection
        self._client = HttpClient(
            base_url=f"https://{site}.chargebee.com",
            auth=BasicAuth(api_key, ""),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_customers(
        self,
        *,
        limit: int = 10,
        offset: str | None = None,
        first_name: str | None = None,
        email: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Chargebee customers.

        Returns compact summaries with ``customer_ref``, name, company,
        email, status, and currency. Raw Chargebee IDs are omitted unless
        ``include_ids=True``.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if offset is not None:
            params["offset"] = offset
        if first_name is not None:
            params["first_name[is]"] = first_name
        if email is not None:
            params["email[is]"] = email
        payload: Any = self._client.get(
            "/api/v2/customers",
            params=params,
        ).json()
        body: dict[str, Any] = cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
        rows: list[Any] = body.get("list", [])
        summaries: list[dict[str, Any]] = []
        for index, entry in enumerate(rows, start=1):
            entry_dict: dict[str, Any] = (
                cast(dict[str, Any], entry) if isinstance(entry, dict) else {}
            )
            customer = entry_dict.get("customer", {})
            if not isinstance(customer, dict):
                continue
            customer = cast(dict[str, Any], customer)
            name = (
                f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
                or customer.get("company", "")
            )
            summary: dict[str, Any] = {
                "customer_ref": f"customer_{index}",
                "name": name,
                "company": customer.get("company", ""),
                "email": customer.get("email", ""),
                "phone": customer.get("phone", ""),
                "status": customer.get("card_status", ""),
                "auto_collection": customer.get("auto_collection", ""),
                "currency": (customer.get("preferred_currency_code") or "").upper(),
            }
            if include_ids:
                summary["customer_id"] = customer.get("id", "")
            summaries.append(summary)
        return {
            "customers": summaries,
            "next_offset": body.get("next_offset"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_customer(self, customer_id: str) -> dict[str, Any]:
        """Return one Chargebee customer by ID."""
        if not customer_id:
            raise ValueError("customer_id must be a non-empty string")
        return self._client.get(f"/api/v2/customers/{customer_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_customer(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a Chargebee customer (form-encoded params).

        Returns the new customer envelope. Pass standard Chargebee
        customer fields (``first_name``, ``last_name``, ``email``, etc.)
        as a dict.
        """
        if not params:
            raise ValueError("params must be non-empty")
        return self._client.post("/api/v2/customers", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_subscriptions(
        self,
        *,
        limit: int = 10,
        status: str | None = None,
        customer_id: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Chargebee subscriptions.

        Returns compact summaries with ``subscription_ref``, status,
        plan/price refs, billing period, total dues (formatted with
        currency), and current term boundaries. Raw IDs are omitted unless
        ``include_ids=True``.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status[is]"] = status
        if customer_id is not None:
            params["customer_id[is]"] = customer_id
        payload: Any = self._client.get("/api/v2/subscriptions", params=params).json()
        body: dict[str, Any] = cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
        rows: list[Any] = body.get("list", [])
        summaries: list[dict[str, Any]] = []
        for index, entry in enumerate(rows, start=1):
            entry_dict: dict[str, Any] = (
                cast(dict[str, Any], entry) if isinstance(entry, dict) else {}
            )
            subscription = entry_dict.get("subscription", {})
            if not isinstance(subscription, dict):
                continue
            subscription = cast(dict[str, Any], subscription)
            items: Any = subscription.get("subscription_items", [])
            currency: Any = subscription.get("currency_code") or ""
            item_names: list[str] = []
            item_list: list[Any] = cast(list[Any], items) if isinstance(items, list) else []
            for item in item_list:
                if isinstance(item, dict):
                    item_dict = cast(dict[str, Any], item)
                    if item_dict.get("item_price_id"):
                        qty: Any = item_dict.get("quantity")
                        qty_str = f" x{qty}" if isinstance(qty, int) and qty != 1 else ""
                        item_names.append(f"{item_dict['item_price_id']}{qty_str}")
            summary: dict[str, Any] = {
                "subscription_ref": f"subscription_{index}",
                "status": subscription.get("status", ""),
                "currency": str(currency).upper(),
                "items": "; ".join(item_names),
                "due_invoices_count": subscription.get("due_invoices_count"),
                "total_dues": _format_amount(subscription.get("total_dues"), currency),
                "current_term_start": subscription.get("current_term_start"),
                "current_term_end": subscription.get("current_term_end"),
                "cancel_at_term_end": bool(subscription.get("cancelled_at"))
                or bool(subscription.get("cancel_at_term_end")),
            }
            if include_ids:
                summary["subscription_id"] = subscription.get("id", "")
                summary["customer_id"] = subscription.get("customer_id", "")
            summaries.append(summary)
        return {
            "subscriptions": summaries,
            "next_offset": body.get("next_offset"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_subscription_for_customer(
        self,
        customer_id: str,
        *,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a subscription for an existing customer.

        Returns the new subscription envelope. ``params`` follows Chargebee's
        ``subscription_for_items`` form-style schema.
        """
        if not customer_id or not params:
            raise ValueError("customer_id and params must be non-empty")
        return self._client.post(
            f"/api/v2/customers/{customer_id}/subscription_for_items",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def cancel_subscription(
        self,
        subscription_id: Any,
        *,
        end_of_term: bool = False,
    ) -> dict[str, Any]:
        """Cancel a Chargebee subscription. Destructive — billing stops.

        ``subscription_id`` accepts a raw ID or a dict from
        :meth:`list_subscriptions` (with ``include_ids=True``). Confirm
        with the user before calling.
        """
        resolved = _coerce_id(subscription_id, keys=("subscription_id", "id"))
        return self._client.post(
            f"/api/v2/subscriptions/{resolved}/cancel_for_items",
            params={"end_of_term": str(end_of_term).lower()},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_invoices(
        self,
        *,
        limit: int = 10,
        status: str | None = None,
        customer_id: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Chargebee invoices.

        Returns compact summaries with ``invoice_ref``, total/amount-due
        (formatted with currency), status, date, and customer reference.
        Raw IDs are omitted unless ``include_ids=True``.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status[is]"] = status
        if customer_id is not None:
            params["customer_id[is]"] = customer_id
        payload: Any = self._client.get("/api/v2/invoices", params=params).json()
        body: dict[str, Any] = cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
        rows: list[Any] = body.get("list", [])
        summaries: list[dict[str, Any]] = []
        for index, entry in enumerate(rows, start=1):
            entry_dict: dict[str, Any] = (
                cast(dict[str, Any], entry) if isinstance(entry, dict) else {}
            )
            invoice = entry_dict.get("invoice", {})
            if not isinstance(invoice, dict):
                continue
            invoice = cast(dict[str, Any], invoice)
            currency: Any = invoice.get("currency_code") or ""
            summary: dict[str, Any] = {
                "invoice_ref": f"invoice_{index}",
                "status": invoice.get("status", ""),
                "total": _format_amount(invoice.get("total"), currency),
                "amount_due": _format_amount(invoice.get("amount_due"), currency),
                "amount_paid": _format_amount(invoice.get("amount_paid"), currency),
                "currency": str(currency).upper(),
                "date": invoice.get("date"),
                "due_date": invoice.get("due_date"),
            }
            if include_ids:
                summary["invoice_id"] = invoice.get("id", "")
                summary["customer_id"] = invoice.get("customer_id", "")
            summaries.append(summary)
        return {
            "invoices": summaries,
            "next_offset": body.get("next_offset"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_plans(self, *, limit: int = 10) -> dict[str, Any]:
        """List item prices (plans). Returns the raw Chargebee response."""
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        return self._client.get(
            "/api/v2/item_prices",
            params={"limit": limit},
        ).json()
