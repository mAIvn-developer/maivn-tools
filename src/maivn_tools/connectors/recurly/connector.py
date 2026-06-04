"""Recurly v3 API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from maivn import toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: - Helpers


def _format_amount(amount: Any, currency: Any) -> str:
    """Format a Recurly numeric amount as ``"12.34 USD"``."""
    if amount is None:
        return ""
    try:
        amount_float = float(amount)
    except (TypeError, ValueError):
        return ""
    code = str(currency or "").upper()
    return f"{amount_float:.2f} {code}".strip()


def _extract_cursor(next_value: Any) -> str | None:
    """Extract the bare ``cursor`` token from a Recurly v3 list ``next`` value.

    Recurly v3 list envelopes return ``next`` as a full URL (e.g.
    ``https://v3.recurly.com/accounts?cursor=1234%3A...&limit=20``) rather than
    a bare cursor token. Feeding that whole URL back into the ``cursor=``
    argument would be invalid, so pull out the embedded ``cursor`` query-string
    value and return it on its own. A token without a URL is returned as-is.
    """
    if not isinstance(next_value, str) or not next_value:
        return None
    parsed = urlsplit(next_value)
    cursor_values = parse_qs(parsed.query).get("cursor")
    if cursor_values:
        return cursor_values[0]
    # No query string / no cursor param: treat the value itself as the token
    # only when it is clearly not a URL.
    if parsed.scheme or parsed.netloc:
        return None
    return next_value


def _coerce_id(
    candidate: Any,
    *,
    keys: tuple[str, ...] = ("id",),
) -> str:
    """Resolve a raw Recurly ID from a dict/string/list."""
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
    raise ValueError("could not resolve a Recurly ID from the given input")


# MARK: - Tool set


@toolset(prefix="recurly")
class RecurlyToolSet:
    """A connector for the Recurly v3 API.

    Plug into an Agent with ``agent.add_toolset(RecurlyToolSet(api_key=...))``
    and the agent can answer questions about accounts, subscriptions,
    invoices, and transactions.
    """

    metadata = ProviderMetadata(
        name="recurly",
        display_name="Recurly",
        version="0.1.0",
        description="Accounts, subscriptions, invoices, and transactions.",
        auth_modes=(AuthMode.BASIC,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developers.recurly.com/api/",
        homepage_url="https://recurly.com/",
        tags=("billing", "subscriptions"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://v3.recurly.com",
        api_version: str = "v2021-02-25",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BasicAuth(api_key, ""),
            transport=transport,
            default_headers={
                "Accept": f"application/vnd.recurly.{api_version}",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_accounts(
        self,
        *,
        limit: int = 20,
        sort: str = "created_at",
        order: str = "desc",
        cursor: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Recurly accounts.

        Returns compact summaries with ``account_ref``, code, name, email,
        state, and currency. Raw account IDs are omitted unless
        ``include_ids=True``.
        """
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        params: dict[str, Any] = {"limit": limit, "sort": sort, "order": order}
        if cursor is not None:
            params["cursor"] = cursor
        payload: dict[str, Any] = cast(
            "dict[str, Any]", self._client.get("/accounts", params=params).json()
        )
        items: list[Any] = payload.get("data", [])
        summaries: list[dict[str, Any]] = []
        for index, account in enumerate(items, start=1):
            if not isinstance(account, dict):
                continue
            account = cast("dict[str, Any]", account)
            first = account.get("first_name") or ""
            last = account.get("last_name") or ""
            name = f"{first} {last}".strip() or account.get("company") or ""
            summary: dict[str, Any] = {
                "account_ref": f"account_{index}",
                "code": account.get("code", ""),
                "name": name,
                "company": account.get("company") or "",
                "email": account.get("email", ""),
                "state": account.get("state", ""),
                "currency": (
                    account.get("preferred_locale") or account.get("currency") or ""
                ).upper(),
                "created_at": account.get("created_at"),
            }
            if include_ids:
                summary["account_id"] = account.get("id", "")
            summaries.append(summary)
        return {
            "accounts": summaries,
            "has_more": bool(payload.get("has_more")),
            "next_cursor": _extract_cursor(payload.get("next")),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_account(self, account_id: str) -> dict[str, Any]:
        """Return one Recurly account (use ``code-<code>`` for the account code)."""
        if not account_id:
            raise ValueError("account_id must be a non-empty string")
        return cast("dict[str, Any]", self._client.get(f"/accounts/{account_id}").json())

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a Recurly account. Returns the new account resource."""
        if not payload:
            raise ValueError("payload must be non-empty")
        return cast("dict[str, Any]", self._client.post("/accounts", json=payload).json())

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_account(self, account_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
        """Update a Recurly account.

        ``account_id`` accepts a raw ID, a Recurly ``code-...`` literal,
        or a dict from :meth:`get_account` / :meth:`list_accounts` (with
        ``include_ids=True``).
        """
        resolved = _coerce_id(account_id, keys=("account_id", "id", "code"))
        if not payload:
            raise ValueError("payload must be non-empty")
        return cast(
            "dict[str, Any]", self._client.put(f"/accounts/{resolved}", json=payload).json()
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_subscriptions(
        self,
        *,
        limit: int = 20,
        state: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Recurly subscriptions.

        Returns compact summaries with ``subscription_ref``, plan code,
        state, unit amount (formatted with currency), and current term
        boundaries. Raw IDs are omitted unless ``include_ids=True``.
        """
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        params: dict[str, Any] = {"limit": limit}
        if state is not None:
            params["state"] = state
        payload: dict[str, Any] = cast(
            "dict[str, Any]", self._client.get("/subscriptions", params=params).json()
        )
        items: list[Any] = payload.get("data", [])
        summaries: list[dict[str, Any]] = []
        for index, sub in enumerate(items, start=1):
            if not isinstance(sub, dict):
                continue
            sub = cast("dict[str, Any]", sub)
            plan: dict[str, Any] = (
                cast("dict[str, Any]", sub.get("plan")) if isinstance(sub.get("plan"), dict) else {}
            )
            account: dict[str, Any] = (
                cast("dict[str, Any]", sub.get("account"))
                if isinstance(sub.get("account"), dict)
                else {}
            )
            currency = sub.get("currency") or ""
            summary: dict[str, Any] = {
                "subscription_ref": f"subscription_{index}",
                "plan_code": plan.get("code", ""),
                "plan_name": plan.get("name", ""),
                "state": sub.get("state", ""),
                "quantity": sub.get("quantity"),
                "unit_amount": _format_amount(sub.get("unit_amount"), currency),
                "currency": str(currency).upper(),
                "current_period_started_at": sub.get("current_period_started_at"),
                "current_period_ends_at": sub.get("current_period_ends_at"),
                "account_code": account.get("code", ""),
            }
            if include_ids:
                summary["subscription_id"] = sub.get("id", "")
                summary["account_id"] = account.get("id", "")
            summaries.append(summary)
        return {
            "subscriptions": summaries,
            "has_more": bool(payload.get("has_more")),
            "next_cursor": _extract_cursor(payload.get("next")),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_subscription(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a Recurly subscription. Returns the new subscription resource."""
        if not payload:
            raise ValueError("payload must be non-empty")
        return cast("dict[str, Any]", self._client.post("/subscriptions", json=payload).json())

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def cancel_subscription(self, subscription_id: Any) -> dict[str, Any]:
        """Cancel a Recurly subscription. Destructive — billing stops at the term end.

        ``subscription_id`` accepts a raw ID or a dict from
        :meth:`list_subscriptions` (with ``include_ids=True``). Confirm
        with the user before calling.
        """
        resolved = _coerce_id(subscription_id, keys=("subscription_id", "id"))
        return cast(
            "dict[str, Any]",
            self._client.put(
                f"/subscriptions/{resolved}/cancel",
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def reactivate_subscription(self, subscription_id: Any) -> dict[str, Any]:
        """Reactivate a cancelled Recurly subscription.

        ``subscription_id`` accepts a raw ID or a dict.
        """
        resolved = _coerce_id(subscription_id, keys=("subscription_id", "id"))
        return cast(
            "dict[str, Any]",
            self._client.put(
                f"/subscriptions/{resolved}/reactivate",
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_invoices(
        self,
        *,
        limit: int = 20,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Recurly invoices.

        Returns compact summaries with ``invoice_ref``, number, total/
        balance (formatted with currency), state, and dates. Raw IDs are
        omitted unless ``include_ids=True``.
        """
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        payload: dict[str, Any] = cast(
            "dict[str, Any]", self._client.get("/invoices", params={"limit": limit}).json()
        )
        items: list[Any] = payload.get("data", [])
        summaries: list[dict[str, Any]] = []
        for index, invoice in enumerate(items, start=1):
            if not isinstance(invoice, dict):
                continue
            invoice = cast("dict[str, Any]", invoice)
            currency = invoice.get("currency") or ""
            account: dict[str, Any] = (
                cast("dict[str, Any]", invoice.get("account"))
                if isinstance(invoice.get("account"), dict)
                else {}
            )
            summary: dict[str, Any] = {
                "invoice_ref": f"invoice_{index}",
                "number": invoice.get("number", ""),
                "state": invoice.get("state", ""),
                "total": _format_amount(invoice.get("total"), currency),
                "balance": _format_amount(invoice.get("balance"), currency),
                "currency": str(currency).upper(),
                "created_at": invoice.get("created_at"),
                "due_at": invoice.get("due_at"),
                "account_code": account.get("code", ""),
            }
            if include_ids:
                summary["invoice_id"] = invoice.get("id", "")
                summary["account_id"] = account.get("id", "")
            summaries.append(summary)
        return {
            "invoices": summaries,
            "has_more": bool(payload.get("has_more")),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_transactions(
        self,
        *,
        limit: int = 20,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Recurly transactions (payments, refunds, declines).

        Returns compact summaries with ``transaction_ref``, type, amount
        (formatted with currency), status, and date. Raw IDs are omitted
        unless ``include_ids=True``.
        """
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        payload: dict[str, Any] = cast(
            "dict[str, Any]",
            self._client.get(
                "/transactions",
                params={"limit": limit},
            ).json(),
        )
        items: list[Any] = payload.get("data", [])
        summaries: list[dict[str, Any]] = []
        for index, txn in enumerate(items, start=1):
            if not isinstance(txn, dict):
                continue
            txn = cast("dict[str, Any]", txn)
            currency = txn.get("currency") or ""
            account: dict[str, Any] = (
                cast("dict[str, Any]", txn.get("account"))
                if isinstance(txn.get("account"), dict)
                else {}
            )
            summary: dict[str, Any] = {
                "transaction_ref": f"transaction_{index}",
                "type": txn.get("type", ""),
                "status": txn.get("status", ""),
                "amount": _format_amount(txn.get("amount"), currency),
                "currency": str(currency).upper(),
                "collected_at": txn.get("collected_at"),
                "account_code": account.get("code", ""),
            }
            if include_ids:
                summary["transaction_id"] = txn.get("id", "")
                invoice_obj = txn.get("invoice")
                summary["invoice_id"] = (
                    cast("dict[str, Any]", invoice_obj).get("id", "")
                    if isinstance(invoice_obj, dict)
                    else ""
                )
                summary["account_id"] = account.get("id", "")
            summaries.append(summary)
        return {
            "transactions": summaries,
            "has_more": bool(payload.get("has_more")),
        }
