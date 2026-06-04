"""Stripe API connector."""
# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# Default pinned Stripe API version. Pinning makes response shapes
# deterministic; this is a current Basil release. In Basil the Subscription
# object's top-level ``current_period_start``/``current_period_end`` were
# removed and moved to ``items.data[].current_period_*``.
_API_VERSION = "2025-03-31.basil"


def _flatten(prefix: str, value: Any, out: list[tuple[str, str]]) -> None:
    """Encode nested dict/list values to Stripe's form-style flat keys."""
    if isinstance(value, dict):
        for k, v in cast("dict[Any, Any]", value).items():
            _flatten(f"{prefix}[{k}]", v, out)
    elif isinstance(value, list):
        for i, v in enumerate(cast("list[Any]", value)):
            _flatten(f"{prefix}[{i}]", v, out)
    elif isinstance(value, bool):
        out.append((prefix, "true" if value else "false"))
    elif value is None:
        out.append((prefix, ""))
    else:
        out.append((prefix, str(value)))


def stripe_form_encode(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert a structured dict to Stripe's repeated-key form encoding."""
    flat: list[tuple[str, str]] = []
    for key, value in payload.items():
        _flatten(key, value, flat)
    result: dict[str, Any] = {}
    for key, value in flat:
        if key in result:
            existing = result[key]
            if isinstance(existing, list):
                cast("list[Any]", existing).append(value)
            else:
                result[key] = [existing, value]
        else:
            result[key] = value
    return result


def _format_amount(amount_minor: Any, currency: Any) -> str:
    """Format Stripe minor-unit amounts as ``"12.34 USD"`` strings."""
    try:
        amount_int = int(amount_minor)
    except (TypeError, ValueError):
        return ""
    code = str(currency or "").upper()
    return f"{amount_int / 100:.2f} {code}".rstrip()


def _coerce_id(candidate: Any, *, prefix: str | None = None) -> str:
    """Resolve a raw ID from the dict/list returned by list/get tools.

    Accepts the dict from a list/get tool, the raw ID string, or a list of
    dicts (returns the first matching ID). ``prefix`` filters for Stripe IDs
    like ``cus_``, ``sub_``, ``in_`` when scanning generic dicts.
    """
    if isinstance(candidate, str) and candidate:
        return candidate

    def _scan(value: Any) -> str | None:
        if isinstance(value, str):
            if prefix is None or value.startswith(prefix):
                return value
            return None
        if isinstance(value, dict):
            value_dict = cast("dict[Any, Any]", value)
            for key in ("id", "subscription_id", "customer_id", "invoice_id", "payment_intent_id"):
                inner = value_dict.get(key)
                if isinstance(inner, str):
                    if prefix is None or inner.startswith(prefix):
                        return inner
            for nested in value_dict.values():
                if isinstance(nested, dict | list | tuple):
                    found = _scan(nested)
                    if found is not None:
                        return found
            return None
        if isinstance(value, list | tuple):
            for item in cast("list[Any] | tuple[Any, ...]", value):
                found = _scan(item)
                if found is not None:
                    return found
        return None

    found = _scan(candidate)
    if found is not None:
        return found
    raise ValueError("could not resolve a Stripe ID from the given input")


@toolset(prefix="stripe")
class StripeToolSet:
    """A connector for the Stripe REST API.

    Plug into an Agent with ``agent.add_toolset(StripeToolSet(api_key=...))``
    and the agent can answer ordinary user questions about customers,
    subscriptions, invoices, charges, disputes, and Checkout sessions.
    """

    metadata = ProviderMetadata(
        name="stripe",
        display_name="Stripe",
        version="0.1.0",
        description="Customers, subscriptions, invoices, charges, disputes, checkout.",
        auth_modes=(AuthMode.BEARER, AuthMode.API_KEY),
        capabilities=frozenset(
            {ProviderCapability.READ, ProviderCapability.WRITE, ProviderCapability.PAGINATION}
        ),
        documentation_url="https://stripe.com/docs/api",
        homepage_url="https://stripe.com/",
        tags=("payments", "billing"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        api_version: str | None = _API_VERSION,
        base_url: str = "https://api.stripe.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        headers: dict[str, str] = {"Accept": "application/json"}
        if api_version is not None:
            headers["Stripe-Version"] = api_version
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(api_key),
            transport=transport,
            default_headers=headers,
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _form_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client.post(path, params=stripe_form_encode(payload)).json()

    # MARK: - Customers

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_customers(
        self,
        *,
        email: str | None = None,
        limit: int = 10,
        starting_after: str | None = None,
        ending_before: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Stripe customers.

        Best first tool when the user mentions a customer by name or email.
        Returns compact summaries with a stable ``customer_ref``
        (``customer_1``, ``customer_2``, ...) that is safe to show in final
        answers. ``email`` filters server-side. Use ``starting_after`` /
        ``ending_before`` for cursor pagination.

        Raw Stripe ``customer_id`` values (``cus_...``) are omitted by
        default. They are internal handles, not user-friendly. Set
        ``include_ids=True`` only when a follow-up tool such as
        :meth:`update_customer` or :meth:`list_invoices` needs the raw ID.

        Returns ``{"customers": [...], "has_more": bool, "next_cursor": str
        | None}``.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if email is not None:
            params["email"] = email
        if starting_after is not None:
            params["starting_after"] = starting_after
        if ending_before is not None:
            params["ending_before"] = ending_before
        payload: dict[str, Any] = self._client.get("/v1/customers", params=params).json()
        customers: list[Any] = payload.get("data", [])
        summaries: list[dict[str, Any]] = []
        for index, customer in enumerate(customers, start=1):
            if not isinstance(customer, dict):
                continue
            customer = cast("dict[str, Any]", customer)
            summary: dict[str, Any] = {
                "customer_ref": f"customer_{index}",
                "name": customer.get("name") or "",
                "email": customer.get("email") or "",
                "description": customer.get("description") or "",
                "currency": (customer.get("currency") or "").upper(),
                "delinquent": bool(customer.get("delinquent")),
                "created": customer.get("created"),
            }
            balance = customer.get("balance")
            if isinstance(balance, int):
                summary["balance"] = _format_amount(balance, customer.get("currency"))
            if include_ids:
                summary["customer_id"] = customer.get("id", "")
            summaries.append(summary)
        last_id = ""
        if summaries and customers and isinstance(customers[-1], dict):
            last_id = cast("dict[str, Any]", customers[-1]).get("id", "") or ""
        return {
            "customers": summaries,
            "has_more": bool(payload.get("has_more")),
            "next_cursor": last_id or None,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_customer(self, customer_id: str) -> dict[str, Any]:
        """Fetch one customer's full record by raw Stripe ID.

        ``customer_id`` must be a raw ``cus_...`` ID. Use this after
        :meth:`list_customers` with ``include_ids=True`` if you need fields
        beyond the summary (addresses, tax info, metadata).
        """
        if not customer_id:
            raise ValueError("customer_id must be a non-empty string")
        return self._client.get(f"/v1/customers/{customer_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_customer(self, **fields: Any) -> dict[str, Any]:
        """Create a Stripe customer.

        Pass standard Stripe customer fields as keyword args: ``email``,
        ``name``, ``description``, ``phone``, ``address={...}``,
        ``metadata={...}``. Returns the new customer resource with its
        ``id`` (a ``cus_...`` handle for follow-up calls).
        """
        if not fields:
            raise ValueError("at least one field is required")
        return self._form_post("/v1/customers", fields)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_customer(self, customer_id: Any, **fields: Any) -> dict[str, Any]:
        """Update a Stripe customer.

        ``customer_id`` accepts either the raw ``cus_...`` ID or the dict
        returned by :meth:`get_customer` / a single :meth:`list_customers`
        entry (with ``include_ids=True``). Returns the updated customer
        resource.
        """
        resolved = _coerce_id(customer_id, prefix="cus_")
        if not fields:
            raise ValueError("at least one field is required")
        return self._form_post(f"/v1/customers/{resolved}", fields)

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_customer(self, customer_id: Any) -> dict[str, Any]:
        """Permanently delete a customer.

        Destructive — confirm with the user before calling. ``customer_id``
        accepts the raw ID or the dict from a list/get tool.
        """
        resolved = _coerce_id(customer_id, prefix="cus_")
        return self._client.delete(f"/v1/customers/{resolved}").json()

    # MARK: - Subscriptions

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_subscriptions(
        self,
        *,
        customer: str | None = None,
        status: str | None = None,
        limit: int = 10,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Stripe subscriptions.

        Returns compact summaries with a stable ``subscription_ref``
        (``subscription_1``, ...). Each entry includes the customer handle,
        status, price/currency, current period, and cancellation hints.
        Pass ``status`` (``active``, ``trialing``, ``past_due``, ``canceled``)
        to narrow the search. Raw IDs are omitted unless ``include_ids=True``.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if customer is not None:
            params["customer"] = customer
        if status is not None:
            params["status"] = status
        payload: dict[str, Any] = self._client.get("/v1/subscriptions", params=params).json()
        subscriptions: list[Any] = payload.get("data", [])
        summaries: list[dict[str, Any]] = []
        for index, sub in enumerate(subscriptions, start=1):
            if not isinstance(sub, dict):
                continue
            sub = cast("dict[str, Any]", sub)
            sub_items = sub.get("items")
            items: list[Any] = (
                cast("dict[str, Any]", sub_items).get("data", [])
                if isinstance(sub_items, dict)
                else []
            )
            price_entries: list[str] = []
            currency = ""
            for item in items:
                if not isinstance(item, dict):
                    continue
                item = cast("dict[str, Any]", item)
                price_value = item.get("price")
                price: dict[str, Any] = (
                    cast("dict[str, Any]", price_value) if isinstance(price_value, dict) else {}
                )
                qty = item.get("quantity")
                unit = _format_amount(price.get("unit_amount"), price.get("currency"))
                if unit:
                    qty_str = f" x{qty}" if isinstance(qty, int) and qty != 1 else ""
                    price_entries.append(f"{unit}{qty_str}")
                if not currency:
                    currency = str(price.get("currency") or "").upper()
            # In the Basil API version the Subscription's top-level
            # current_period_start/end were removed and moved to each
            # item (items.data[].current_period_*). Read from the first
            # item, falling back to the top-level fields for accounts
            # still pinned to pre-Basil versions.
            first_item: dict[str, Any] = (
                cast("dict[str, Any]", items[0]) if items and isinstance(items[0], dict) else {}
            )
            period_start = first_item.get("current_period_start")
            if period_start is None:
                period_start = sub.get("current_period_start")
            period_end = first_item.get("current_period_end")
            if period_end is None:
                period_end = sub.get("current_period_end")
            summary: dict[str, Any] = {
                "subscription_ref": f"subscription_{index}",
                "status": sub.get("status", ""),
                "currency": currency,
                "pricing": "; ".join(price_entries),
                "current_period_start": period_start,
                "current_period_end": period_end,
                "cancel_at_period_end": bool(sub.get("cancel_at_period_end")),
            }
            if include_ids:
                summary["subscription_id"] = sub.get("id", "")
                summary["customer_id"] = sub.get("customer", "")
            summaries.append(summary)
        last_id = ""
        if subscriptions and isinstance(subscriptions[-1], dict):
            last_id = cast("dict[str, Any]", subscriptions[-1]).get("id", "") or ""
        return {
            "subscriptions": summaries,
            "has_more": bool(payload.get("has_more")),
            "next_cursor": last_id or None,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_subscription(
        self,
        *,
        customer: str,
        items: list[dict[str, Any]],
        **fields: Any,
    ) -> dict[str, Any]:
        """Create a subscription.

        ``items`` is a list of ``{"price": "price_..."}`` (with optional
        ``quantity``). Returns the new subscription resource.
        """
        if not customer or not items:
            raise ValueError("customer and items must be non-empty")
        body = {"customer": customer, "items": items, **fields}
        return self._form_post("/v1/subscriptions", body)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def cancel_subscription(
        self,
        subscription_id: Any,
        *,
        invoice_now: bool | None = None,
        prorate: bool | None = None,
    ) -> dict[str, Any]:
        """Cancel a subscription.

        Destructive: the subscription stops billing. ``subscription_id``
        accepts the raw ``sub_...`` ID or the dict from :meth:`list_subscriptions`
        (with ``include_ids=True``). Confirm with the user before calling.
        """
        resolved = _coerce_id(subscription_id, prefix="sub_")
        params: dict[str, Any] = {}
        if invoice_now is not None:
            params["invoice_now"] = str(invoice_now).lower()
        if prorate is not None:
            params["prorate"] = str(prorate).lower()
        return self._client.delete(
            f"/v1/subscriptions/{resolved}",
            params=params or None,
        ).json()

    # MARK: - Invoices

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_invoices(
        self,
        *,
        customer: str | None = None,
        status: str | None = None,
        limit: int = 10,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List invoices.

        Returns compact summaries with ``invoice_ref``, total amount
        (formatted with currency), status, due date, and a customer
        reference. ``status`` accepts ``draft``, ``open``, ``paid``,
        ``void``, ``uncollectible``. Raw IDs are omitted unless
        ``include_ids=True``.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if customer is not None:
            params["customer"] = customer
        if status is not None:
            params["status"] = status
        payload: dict[str, Any] = self._client.get("/v1/invoices", params=params).json()
        invoices: list[Any] = payload.get("data", [])
        summaries: list[dict[str, Any]] = []
        for index, invoice in enumerate(invoices, start=1):
            if not isinstance(invoice, dict):
                continue
            invoice = cast("dict[str, Any]", invoice)
            currency = invoice.get("currency") or ""
            summary: dict[str, Any] = {
                "invoice_ref": f"invoice_{index}",
                "number": invoice.get("number") or "",
                "status": invoice.get("status", ""),
                "total": _format_amount(invoice.get("total"), currency),
                "amount_due": _format_amount(invoice.get("amount_due"), currency),
                "amount_paid": _format_amount(invoice.get("amount_paid"), currency),
                "currency": str(currency).upper(),
                "customer_email": invoice.get("customer_email") or "",
                "due_date": invoice.get("due_date"),
                "created": invoice.get("created"),
            }
            if include_ids:
                summary["invoice_id"] = invoice.get("id", "")
                summary["customer_id"] = invoice.get("customer", "")
            summaries.append(summary)
        last_id = ""
        if invoices and isinstance(invoices[-1], dict):
            last_id = cast("dict[str, Any]", invoices[-1]).get("id", "") or ""
        return {
            "invoices": summaries,
            "has_more": bool(payload.get("has_more")),
            "next_cursor": last_id or None,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_invoice(self, *, customer: str, **fields: Any) -> dict[str, Any]:
        """Create a draft invoice. Returns the new invoice resource."""
        if not customer:
            raise ValueError("customer must be a non-empty string")
        return self._form_post("/v1/invoices", {"customer": customer, **fields})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def finalize_invoice(self, invoice_id: Any) -> dict[str, Any]:
        """Finalize a draft invoice (transitions it to ``open``).

        ``invoice_id`` accepts the raw ``in_...`` ID or a dict from
        :meth:`list_invoices` with ``include_ids=True``. Returns the
        finalized invoice resource.
        """
        resolved = _coerce_id(invoice_id, prefix="in_")
        return self._client.post(f"/v1/invoices/{resolved}/finalize").json()

    # MARK: - Payment intents & refunds

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_payment_intent(
        self,
        *,
        amount: int,
        currency: str,
        customer: str | None = None,
        payment_method: str | None = None,
        confirm: bool | None = None,
        idempotency_key: str | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """Create a PaymentIntent.

        ``amount`` is in minor units (e.g. cents for USD). ``currency`` is
        an ISO-4217 code. Returns the new PaymentIntent resource. Confirm
        recipient and amount with the user before calling.
        """
        if amount < 1 or not currency:
            raise ValueError("amount must be > 0 and currency must be non-empty")
        body: dict[str, Any] = {"amount": amount, "currency": currency, **fields}
        if customer is not None:
            body["customer"] = customer
        if payment_method is not None:
            body["payment_method"] = payment_method
        if confirm is not None:
            body["confirm"] = confirm
        response = self._client.post(
            "/v1/payment_intents",
            params=stripe_form_encode(body),
            idempotency_key=idempotency_key,
        )
        return response.json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def confirm_payment_intent(self, payment_intent_id: str, **fields: Any) -> dict[str, Any]:
        """Confirm a PaymentIntent and return the updated resource."""
        if not payment_intent_id:
            raise ValueError("payment_intent_id must be a non-empty string")
        return self._form_post(
            f"/v1/payment_intents/{payment_intent_id}/confirm",
            fields,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def refund_charge(
        self,
        *,
        charge: Any | None = None,
        payment_intent: Any | None = None,
        amount: int | None = None,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Refund a charge or PaymentIntent. Destructive — money moves back to the customer.

        Provide exactly one of ``charge`` (``ch_...``) or ``payment_intent``
        (``pi_...``); both accept raw IDs or dicts returned by list/get tools.
        ``amount`` is optional and is in the original currency's minor units;
        omit it for a full refund. Always confirm with the user before
        calling. Returns the new refund resource.
        """
        if not charge and not payment_intent:
            raise ValueError("provide charge or payment_intent")
        body: dict[str, Any] = {}
        if charge is not None:
            body["charge"] = _coerce_id(charge, prefix="ch_")
        if payment_intent is not None:
            body["payment_intent"] = _coerce_id(payment_intent, prefix="pi_")
        if amount is not None:
            body["amount"] = amount
        if reason is not None:
            body["reason"] = reason
        response = self._client.post(
            "/v1/refunds",
            params=stripe_form_encode(body),
            idempotency_key=idempotency_key,
        )
        return response.json()

    # MARK: - Charges & disputes

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_charges(
        self,
        *,
        customer: str | None = None,
        limit: int = 10,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List charges.

        Returns compact summaries with ``charge_ref``, amount (formatted
        with currency), status, captured/refunded flags, and customer/
        receipt email. Raw IDs are omitted unless ``include_ids=True``.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if customer is not None:
            params["customer"] = customer
        payload: dict[str, Any] = self._client.get("/v1/charges", params=params).json()
        charges: list[Any] = payload.get("data", [])
        summaries: list[dict[str, Any]] = []
        for index, charge in enumerate(charges, start=1):
            if not isinstance(charge, dict):
                continue
            charge = cast("dict[str, Any]", charge)
            currency = charge.get("currency") or ""
            summary: dict[str, Any] = {
                "charge_ref": f"charge_{index}",
                "amount": _format_amount(charge.get("amount"), currency),
                "amount_refunded": _format_amount(charge.get("amount_refunded"), currency),
                "currency": str(currency).upper(),
                "status": charge.get("status", ""),
                "captured": bool(charge.get("captured")),
                "refunded": bool(charge.get("refunded")),
                "description": charge.get("description") or "",
                "receipt_email": charge.get("receipt_email") or "",
                "created": charge.get("created"),
            }
            if include_ids:
                summary["charge_id"] = charge.get("id", "")
                summary["customer_id"] = charge.get("customer", "")
                summary["payment_intent_id"] = charge.get("payment_intent", "")
            summaries.append(summary)
        last_id = ""
        if charges and isinstance(charges[-1], dict):
            last_id = cast("dict[str, Any]", charges[-1]).get("id", "") or ""
        return {
            "charges": summaries,
            "has_more": bool(payload.get("has_more")),
            "next_cursor": last_id or None,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_disputes(self, *, limit: int = 10) -> dict[str, Any]:
        """List disputes (chargebacks).

        Returns ``{"disputes": [...]}``. Each entry summarizes the dispute
        amount, status, reason, and the underlying charge reference.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        payload: dict[str, Any] = self._client.get("/v1/disputes", params={"limit": limit}).json()
        disputes: list[Any] = payload.get("data", [])
        summaries: list[dict[str, Any]] = []
        for index, dispute in enumerate(disputes, start=1):
            if not isinstance(dispute, dict):
                continue
            dispute = cast("dict[str, Any]", dispute)
            currency = dispute.get("currency") or ""
            evidence_details_value = dispute.get("evidence_details")
            evidence_details: dict[str, Any] = (
                cast("dict[str, Any]", evidence_details_value)
                if isinstance(evidence_details_value, dict)
                else {}
            )
            summary: dict[str, Any] = {
                "dispute_ref": f"dispute_{index}",
                "amount": _format_amount(dispute.get("amount"), currency),
                "currency": str(currency).upper(),
                "status": dispute.get("status", ""),
                "reason": dispute.get("reason", ""),
                "evidence_due_by": evidence_details.get("due_by"),
                "is_charge_refundable": bool(dispute.get("is_charge_refundable")),
                "created": dispute.get("created"),
            }
            summaries.append(summary)
        return {
            "disputes": summaries,
            "has_more": bool(payload.get("has_more")),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_dispute(self, dispute_id: str, **fields: Any) -> dict[str, Any]:
        """Update a dispute (submit evidence). Returns the updated dispute."""
        if not dispute_id:
            raise ValueError("dispute_id must be a non-empty string")
        return self._form_post(f"/v1/disputes/{dispute_id}", fields)

    # MARK: - Checkout & products

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_checkout_session(self, **fields: Any) -> dict[str, Any]:
        """Create a Checkout Session.

        Returns the session resource — its ``url`` is the customer-facing
        link. Pass ``line_items``, ``mode``, ``success_url``,
        ``cancel_url``, etc. as keyword args.
        """
        if not fields:
            raise ValueError("at least one field is required")
        return self._form_post("/v1/checkout/sessions", fields)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_products(self, *, active: bool | None = None, limit: int = 10) -> dict[str, Any]:
        """List Stripe products.

        Returns the raw Stripe page (``data``, ``has_more``, ``url``).
        ``active=True`` filters to active products only.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if active is not None:
            params["active"] = str(active).lower()
        return self._client.get("/v1/products", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_prices(self, *, product: str | None = None, limit: int = 10) -> dict[str, Any]:
        """List Stripe prices.

        Returns the raw Stripe page. Pass ``product`` (a ``prod_...`` ID)
        to filter to prices on a specific product.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if product is not None:
            params["product"] = product
        return self._client.get("/v1/prices", params=params).json()

    # MARK: - Balance

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_balance(self) -> dict[str, Any]:
        """Return the current Stripe account balance.

        Returns ``{"available": [...], "pending": [...]}``. Each entry has
        ``amount`` (minor units) and ``currency``.
        """
        return self._client.get("/v1/balance").json()
