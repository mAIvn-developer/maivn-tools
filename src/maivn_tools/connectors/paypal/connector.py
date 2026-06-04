"""PayPal REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: - Helpers


def _format_amount(amount: Any) -> str:
    """Format a PayPal amount object as ``"12.34 USD"``."""
    if not isinstance(amount, dict):
        return ""
    amount_dict = cast("dict[str, Any]", amount)
    value: Any = amount_dict.get("value", "")
    currency: Any = amount_dict.get("currency_code", "")
    return f"{value} {currency}".strip()


def _coerce_id(
    candidate: Any,
    *,
    keys: tuple[str, ...] = ("id",),
) -> str:
    """Resolve a raw PayPal ID from a dict/string/list."""
    if isinstance(candidate, str) and candidate:
        return candidate
    if isinstance(candidate, dict):
        candidate_dict = cast("dict[str, Any]", candidate)
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
    raise ValueError("could not resolve a PayPal ID from the given input")


@toolset(prefix="paypal")
class PayPalToolSet:
    """A connector for the PayPal REST API.

    Plug into an Agent with ``agent.add_toolset(PayPalToolSet(access_token=...))``
    and the agent can answer questions about orders, payments, captures,
    subscriptions, and disputes.

    Args:
        access_token: OAuth bearer token (obtained from /v1/oauth2/token).
        base_url: ``https://api-m.sandbox.paypal.com`` for sandbox or
            ``https://api-m.paypal.com`` for live.
    """

    metadata = ProviderMetadata(
        name="paypal",
        display_name="PayPal",
        version="0.1.0",
        description="Orders, payments, subscriptions, and disputes.",
        auth_modes=(AuthMode.OAUTH2_CLIENT_CREDENTIALS, AuthMode.BEARER),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.paypal.com/api/rest/",
        homepage_url="https://www.paypal.com/",
        tags=("payments",),
    )

    def __init__(
        self,
        *,
        access_token: str,
        base_url: str = "https://api-m.paypal.com",
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
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Orders

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_order(
        self,
        *,
        intent: str = "CAPTURE",
        purchase_units: list[dict[str, Any]],
        application_context: dict[str, Any] | None = None,
        payment_source: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a Checkout order.

        ``intent`` is ``CAPTURE`` (charge immediately on approval) or
        ``AUTHORIZE`` (place a hold). Each ``purchase_units`` entry has
        ``amount={"value": "10.00", "currency_code": "USD"}``. Returns the
        new order with ``id`` and approval ``links``.
        """
        if intent not in {"CAPTURE", "AUTHORIZE"}:
            raise ValueError("intent must be CAPTURE or AUTHORIZE")
        if not purchase_units:
            raise ValueError("purchase_units must be non-empty")
        body: dict[str, Any] = {"intent": intent, "purchase_units": purchase_units}
        if application_context is not None:
            body["application_context"] = application_context
        if payment_source is not None:
            body["payment_source"] = payment_source
        return self._client.post("/v2/checkout/orders", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_order(self, order_id: str) -> dict[str, Any]:
        """Return one order by PayPal order ID."""
        if not order_id:
            raise ValueError("order_id must be a non-empty string")
        return self._client.get(f"/v2/checkout/orders/{order_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def capture_order(self, order_id: str) -> dict[str, Any]:
        """Capture an authorized order (charges the buyer).

        Returns the captured order with capture details. Confirm with the
        user before calling — money moves at this point.
        """
        if not order_id:
            raise ValueError("order_id must be a non-empty string")
        return self._client.post(
            f"/v2/checkout/orders/{order_id}/capture",
            json={},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def authorize_order(self, order_id: str) -> dict[str, Any]:
        """Authorize an order (places a hold without charging).

        Returns the authorization resource. Use :meth:`capture_order` later
        to charge it, or :meth:`void_authorization` to release the hold.
        """
        if not order_id:
            raise ValueError("order_id must be a non-empty string")
        return self._client.post(
            f"/v2/checkout/orders/{order_id}/authorize",
            json={},
        ).json()

    # MARK: - Payments

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_capture(self, capture_id: str) -> dict[str, Any]:
        """Return a captured payment by capture ID."""
        if not capture_id:
            raise ValueError("capture_id must be a non-empty string")
        return self._client.get(f"/v2/payments/captures/{capture_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def refund_capture(
        self,
        capture_id: Any,
        *,
        amount: dict[str, Any] | None = None,
        note_to_payer: str | None = None,
        invoice_id: str | None = None,
    ) -> dict[str, Any]:
        """Refund a captured payment. Destructive — money returns to the buyer.

        ``capture_id`` accepts the raw ID or a dict from :meth:`get_capture`.
        ``amount`` is ``{"value": "5.00", "currency_code": "USD"}``; omit
        it for a full refund. Always confirm with the user before calling.
        """
        resolved = _coerce_id(capture_id, keys=("capture_id", "id"))
        body: dict[str, Any] = {}
        if amount is not None:
            body["amount"] = amount
        if note_to_payer is not None:
            body["note_to_payer"] = note_to_payer
        if invoice_id is not None:
            body["invoice_id"] = invoice_id
        return self._client.post(
            f"/v2/payments/captures/{resolved}/refund",
            json=body or {},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_authorization(self, authorization_id: str) -> dict[str, Any]:
        """Return an authorization by ID."""
        if not authorization_id:
            raise ValueError("authorization_id must be a non-empty string")
        return self._client.get(f"/v2/payments/authorizations/{authorization_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def void_authorization(self, authorization_id: Any) -> dict[str, Any]:
        """Void an authorization (releases the hold).

        Destructive — the authorization cannot be re-used after voiding.
        ``authorization_id`` accepts a raw ID or dict from
        :meth:`get_authorization`. Returns ``{"id": ..., "voided": True,
        "status": <http_status>}``.
        """
        resolved = _coerce_id(authorization_id, keys=("authorization_id", "id"))
        response = self._client.post(
            f"/v2/payments/authorizations/{resolved}/void",
            json={},
        )
        return {"id": resolved, "voided": True, "status": response.status}

    # MARK: - Subscriptions

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_subscription(
        self,
        *,
        plan_id: str,
        subscriber: dict[str, Any] | None = None,
        application_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a subscription on a billing plan.

        ``plan_id`` is a PayPal billing-plan ID. Returns the new
        subscription with approval ``links``.
        """
        if not plan_id:
            raise ValueError("plan_id must be a non-empty string")
        body: dict[str, Any] = {"plan_id": plan_id}
        if subscriber is not None:
            body["subscriber"] = subscriber
        if application_context is not None:
            body["application_context"] = application_context
        return self._client.post("/v1/billing/subscriptions", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_subscription(self, subscription_id: str) -> dict[str, Any]:
        """Return one subscription by ID."""
        if not subscription_id:
            raise ValueError("subscription_id must be a non-empty string")
        return self._client.get(f"/v1/billing/subscriptions/{subscription_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def cancel_subscription(
        self,
        subscription_id: Any,
        *,
        reason: str = "User canceled",
    ) -> dict[str, Any]:
        """Cancel a subscription. Destructive — billing stops.

        ``subscription_id`` accepts a raw ID or a dict from
        :meth:`get_subscription`. Always confirm with the user before
        calling.
        """
        resolved = _coerce_id(subscription_id, keys=("subscription_id", "id"))
        response = self._client.post(
            f"/v1/billing/subscriptions/{resolved}/cancel",
            json={"reason": reason},
        )
        return {"id": resolved, "cancelled": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def suspend_subscription(
        self,
        subscription_id: Any,
        *,
        reason: str = "Paused",
    ) -> dict[str, Any]:
        """Suspend a subscription (pausable, not destructive).

        Use :meth:`get_subscription` first to confirm state. Returns
        ``{"id": ..., "suspended": True, "status": <http_status>}``.
        """
        resolved = _coerce_id(subscription_id, keys=("subscription_id", "id"))
        response = self._client.post(
            f"/v1/billing/subscriptions/{resolved}/suspend",
            json={"reason": reason},
        )
        return {"id": resolved, "suspended": True, "status": response.status}

    # MARK: - Disputes

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_disputes(
        self,
        *,
        page_size: int = 10,
        status: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List customer disputes.

        Returns compact summaries with ``dispute_ref``, dispute amount,
        status, reason, and lifecycle timestamps. Raw IDs are omitted
        unless ``include_ids=True``.
        """
        if page_size < 1 or page_size > 50:
            raise ValueError("page_size must be between 1 and 50")
        params: dict[str, Any] = {"page_size": page_size}
        if status is not None:
            params["dispute_state"] = status
        raw_payload: Any = self._client.get("/v1/customer/disputes", params=params).json()
        payload: dict[str, Any] = (
            cast("dict[str, Any]", raw_payload) if isinstance(raw_payload, dict) else {}
        )
        items: list[Any] = payload.get("items", [])
        summaries: list[dict[str, Any]] = []
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            item_dict = cast("dict[str, Any]", item)
            summary: dict[str, Any] = {
                "dispute_ref": f"dispute_{index}",
                "amount": _format_amount(item_dict.get("dispute_amount")),
                "status": item_dict.get("status", ""),
                "state": item_dict.get("dispute_state", ""),
                "reason": item_dict.get("reason", ""),
                "create_time": item_dict.get("create_time"),
                "update_time": item_dict.get("update_time"),
            }
            if include_ids:
                summary["dispute_id"] = item_dict.get("dispute_id", "")
            summaries.append(summary)
        return {
            "disputes": summaries,
            "links": payload.get("links"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_dispute(self, dispute_id: str) -> dict[str, Any]:
        """Return one dispute's full record by ID."""
        if not dispute_id:
            raise ValueError("dispute_id must be a non-empty string")
        return self._client.get(f"/v1/customer/disputes/{dispute_id}").json()
