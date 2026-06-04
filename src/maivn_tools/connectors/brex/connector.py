"""Brex API v2 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# Brex's current canonical production base URL. The legacy
# ``platform.brexapis.com`` alias still resolves but is on a deprecation path;
# ``api.brex.com`` is what the Brex quickstart and auth guides now use.
DEFAULT_BASE_URL = "https://api.brex.com"

# MARK: Helpers


def _format_money(money: Any) -> str:
    """Format a Brex ``Money`` object as ``"12.34 USD"``."""
    if not isinstance(money, dict):
        return ""
    money_dict = cast("dict[str, Any]", money)
    amount: Any = money_dict.get("amount")
    if amount is None:
        return ""
    currency: Any = money_dict.get("currency") or ""
    try:
        amount_int = int(str(amount))
    except (TypeError, ValueError):
        return ""
    return f"{amount_int / 100:.2f} {currency}".strip()


def _coerce_id(candidate: Any) -> str:
    """Resolve a raw Brex ID from a dict/string/list."""
    if isinstance(candidate, str) and candidate:
        return candidate
    if isinstance(candidate, dict):
        candidate_dict = cast("dict[str, Any]", candidate)
        for key in ("card_id", "expense_id", "id"):
            value: Any = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
        for nested in candidate_dict.values():
            nested_value: Any = nested
            if isinstance(nested_value, dict | list | tuple):
                try:
                    return _coerce_id(nested_value)
                except ValueError:
                    continue
    if isinstance(candidate, list | tuple):
        candidate_seq = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in candidate_seq:
            item_value: Any = item
            try:
                return _coerce_id(item_value)
            except ValueError:
                continue
    raise ValueError("could not resolve a Brex ID from the given input")


def _payload_items(payload: Any) -> list[Any]:
    """Extract the ``items`` list from a Brex paginated payload."""
    if not isinstance(payload, dict):
        return []
    payload_dict = cast("dict[str, Any]", payload)
    raw_items: Any = payload_dict.get("items", [])
    return cast("list[Any]", raw_items) if isinstance(raw_items, list) else []


def _payload_next_cursor(payload: Any) -> Any:
    """Extract the ``next_cursor`` value from a Brex paginated payload."""
    if not isinstance(payload, dict):
        return None
    payload_dict = cast("dict[str, Any]", payload)
    return payload_dict.get("next_cursor")


# MARK: ToolSet


@toolset(prefix="brex")
class BrexToolSet:
    """A connector for the Brex API v2.

    Plug into an Agent with ``agent.add_toolset(BrexToolSet(access_token=...))``
    and the agent can answer questions about cash accounts, card
    transactions, expenses, cards, users, and vendors.
    """

    metadata = ProviderMetadata(
        name="brex",
        display_name="Brex",
        version="0.1.0",
        description="Accounts, transactions, expenses, cards, transfers, and users.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.brex.com/openapi/",
        homepage_url="https://www.brex.com/",
        tags=("finance", "cards"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        base_url: str = DEFAULT_BASE_URL,
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

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_cash_accounts(self) -> dict[str, Any]:
        """List Brex cash management accounts. Returns the raw response."""
        return self._client.get("/v2/accounts/cash").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_card_accounts(self) -> dict[str, Any]:
        """List Brex card accounts. Returns the raw response."""
        return self._client.get("/v2/accounts/card").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_transactions(
        self,
        *,
        cursor: str | None = None,
        limit: int = 25,
        account_id: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Brex card transactions.

        Returns compact summaries with ``transaction_ref``, description,
        amount (formatted with currency), date, type, and posted-at
        timestamp. Raw transaction IDs are omitted unless
        ``include_ids=True``.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        if account_id is not None:
            params["account_id"] = account_id
        payload: Any = self._client.get(
            "/v2/transactions/card/primary",
            params=params,
        ).json()
        items = _payload_items(payload)
        summaries: list[dict[str, Any]] = []
        for index, txn in enumerate(items, start=1):
            if not isinstance(txn, dict):
                continue
            txn_dict = cast("dict[str, Any]", txn)
            summary: dict[str, Any] = {
                "transaction_ref": f"transaction_{index}",
                "description": txn_dict.get("description", ""),
                "amount": _format_money(txn_dict.get("amount")),
                "type": txn_dict.get("type", ""),
                "initiated_at": txn_dict.get("initiated_at_date"),
                "posted_at": txn_dict.get("posted_at_date"),
            }
            if include_ids:
                summary["transaction_id"] = txn_dict.get("id", "")
                summary["card_id"] = txn_dict.get("card_id", "")
            summaries.append(summary)
        return {
            "transactions": summaries,
            "next_cursor": _payload_next_cursor(payload),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_expenses(
        self,
        *,
        cursor: str | None = None,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Brex card expenses.

        Returns compact summaries with ``expense_ref``, merchant, amount
        (formatted with currency), status, memo, and category. Raw IDs
        are omitted unless ``include_ids=True``.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit, "expense_type": "CARD"}
        if cursor is not None:
            params["cursor"] = cursor
        payload: Any = self._client.get(
            "/v1/expenses",
            params=params,
        ).json()
        items = _payload_items(payload)
        summaries: list[dict[str, Any]] = []
        for index, expense in enumerate(items, start=1):
            if not isinstance(expense, dict):
                continue
            expense_dict = cast("dict[str, Any]", expense)
            raw_merchant: Any = expense_dict.get("merchant")
            merchant: dict[str, Any] = (
                cast("dict[str, Any]", raw_merchant) if isinstance(raw_merchant, dict) else {}
            )
            summary: dict[str, Any] = {
                "expense_ref": f"expense_{index}",
                "merchant": merchant.get("raw_descriptor", ""),
                "amount": _format_money(expense_dict.get("original_amount")),
                "status": expense_dict.get("status", ""),
                "category": expense_dict.get("category", ""),
                "memo": expense_dict.get("memo", ""),
                "purchased_at": expense_dict.get("purchased_at"),
            }
            if include_ids:
                summary["expense_id"] = expense_dict.get("id", "")
                summary["card_id"] = expense_dict.get("card_id", "")
            summaries.append(summary)
        return {
            "expenses": summaries,
            "next_cursor": _payload_next_cursor(payload),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_expense(self, expense_id: str) -> dict[str, Any]:
        """Return one Brex expense by ID."""
        if not expense_id:
            raise ValueError("expense_id must be a non-empty string")
        return self._client.get(f"/v1/expenses/{expense_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_expense(self, expense_id: Any, fields: dict[str, Any]) -> dict[str, Any]:
        """Patch a Brex expense (memo, receipt URL, etc.).

        ``expense_id`` accepts a raw ID or a dict from :meth:`list_expenses`
        (with ``include_ids=True``).
        """
        resolved = _coerce_id(expense_id)
        if not fields:
            raise ValueError("fields must be non-empty")
        return self._client.put(
            f"/v1/expenses/card/{resolved}",
            json=fields,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_cards(
        self,
        *,
        cursor: str | None = None,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Brex cards.

        Returns compact summaries with ``card_ref``, last four digits, card
        type, status, owner name, and limit. Raw card IDs are omitted
        unless ``include_ids=True``.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        payload: Any = self._client.get("/v2/cards", params=params).json()
        items = _payload_items(payload)
        summaries: list[dict[str, Any]] = []
        for index, card in enumerate(items, start=1):
            if not isinstance(card, dict):
                continue
            card_dict = cast("dict[str, Any]", card)
            raw_owner: Any = card_dict.get("owner")
            owner = cast("dict[str, Any]", raw_owner) if isinstance(raw_owner, dict) else {}
            summary: dict[str, Any] = {
                "card_ref": f"card_{index}",
                "last_four": card_dict.get("last_four", ""),
                "card_type": card_dict.get("card_type", ""),
                "status": card_dict.get("status", ""),
                "owner_name": owner.get("name", ""),
                "limit": _format_money(card_dict.get("limit")),
            }
            if include_ids:
                summary["card_id"] = card_dict.get("id", "")
            summaries.append(summary)
        return {
            "cards": summaries,
            "next_cursor": _payload_next_cursor(payload),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def issue_card(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Issue a new Brex card. Returns the new card resource."""
        if not payload:
            raise ValueError("payload must be non-empty")
        return self._client.post("/v2/cards", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def terminate_card(self, card_id: Any) -> dict[str, Any]:
        """Terminate a Brex card. Destructive — confirm with the user.

        ``card_id`` accepts a raw ID or a dict from :meth:`list_cards`
        (with ``include_ids=True``).
        """
        resolved = _coerce_id(card_id)
        response = self._client.post(f"/v2/cards/{resolved}/terminate")
        return {"id": resolved, "terminated": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_users(self, *, cursor: str | None = None, limit: int = 25) -> dict[str, Any]:
        """List Brex users. Returns the raw paginated response."""
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        return self._client.get("/v2/users", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_vendors(self, *, cursor: str | None = None, limit: int = 25) -> dict[str, Any]:
        """List Brex vendors. Returns the raw paginated response."""
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        return self._client.get("/v1/vendors", params=params).json()
