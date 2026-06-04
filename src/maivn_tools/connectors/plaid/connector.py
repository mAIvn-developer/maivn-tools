"""Plaid REST API connector.

Plaid passes ``client_id`` and ``secret`` in the JSON body of every call
plus an ``access_token`` for user-level requests. This toolset wraps that
convention.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.base import NoAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# Pinning ``Plaid-Version`` makes response shapes deterministic instead of
# depending on the account's Dashboard default. ``2020-09-14`` is the current
# documented version (https://plaid.com/docs/api/versioning/).
DEFAULT_PLAID_VERSION = "2020-09-14"

# MARK: Helpers


def _format_amount(amount: Any, iso_currency: Any) -> str:
    """Format a Plaid amount as ``"12.34 USD"``."""
    if amount is None:
        return ""
    try:
        amount_float = float(amount)
    except (TypeError, ValueError):
        return ""
    code = str(iso_currency or "").upper()
    return f"{amount_float:.2f} {code}".strip()


# MARK: ToolSet


@toolset(prefix="plaid")
class PlaidToolSet:
    """A connector for the Plaid REST API.

    Plug into an Agent with ``agent.add_toolset(PlaidToolSet(client_id=...,
    secret=...))`` and the agent can answer questions about linked bank
    accounts, balances, transactions, identity, and liabilities.
    """

    metadata = ProviderMetadata(
        name="plaid",
        display_name="Plaid",
        version="0.1.0",
        description="Accounts, transactions, identity, liabilities, and Link tokens.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://plaid.com/docs/api/",
        homepage_url="https://plaid.com/",
        tags=("payments", "banking"),
    )

    def __init__(
        self,
        *,
        client_id: str,
        secret: str,
        environment: str = "production",
        plaid_version: str = DEFAULT_PLAID_VERSION,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not client_id or not secret:
            raise ValueError("client_id and secret are required")
        if environment not in {"sandbox", "production"}:
            raise ValueError(
                "environment must be sandbox or production "
                "(Plaid decommissioned the development environment on 2024-06-20)"
            )
        self.connection = connection
        self._client_id = client_id
        self._secret = secret
        self._client = HttpClient(
            base_url=f"https://{environment}.plaid.com",
            auth=NoAuth(),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Plaid-Version": plaid_version,
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _call(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"client_id": self._client_id, "secret": self._secret}
        if body:
            payload.update(body)
        return self._client.post(path, json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_link_token(
        self,
        *,
        client_user_id: str,
        client_name: str,
        products: list[str],
        country_codes: list[str],
        language: str = "en",
        webhook: str | None = None,
    ) -> dict[str, Any]:
        """Create a Link token (used by Plaid Link to onboard users).

        Returns ``{"link_token": ..., "expiration": ...}``. Pass the
        ``link_token`` to the front-end Plaid Link flow.
        """
        if not client_user_id or not products or not country_codes:
            raise ValueError("client_user_id, products, and country_codes must be non-empty")
        body: dict[str, Any] = {
            "user": {"client_user_id": client_user_id},
            "client_name": client_name,
            "products": products,
            "country_codes": country_codes,
            "language": language,
        }
        if webhook is not None:
            body["webhook"] = webhook
        return self._call("/link/token/create", body)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def exchange_public_token(self, *, public_token: str) -> dict[str, Any]:
        """Exchange a Link ``public_token`` for an ``access_token``.

        Returns ``{"access_token": ..., "item_id": ...}``. Persist the
        ``access_token`` server-side; it is the credential for every
        per-user Plaid call.
        """
        if not public_token:
            raise ValueError("public_token must be a non-empty string")
        return self._call("/item/public_token/exchange", {"public_token": public_token})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_accounts(self, access_token: str) -> dict[str, Any]:
        """Get linked accounts for an Item.

        Returns the raw Plaid response with ``accounts`` (each having
        ``account_id``, ``name``, ``type``, ``subtype``, ``mask``, and
        ``balances``). ``access_token`` is the per-user token from
        :meth:`exchange_public_token`.
        """
        if not access_token:
            raise ValueError("access_token must be a non-empty string")
        return self._call("/accounts/get", {"access_token": access_token})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_balance(self, access_token: str) -> dict[str, Any]:
        """Get up-to-date account balances.

        Forces a live fetch (subject to provider rate limits). Returns the
        raw Plaid response with ``accounts`` including current/available
        balances and ISO currency code.
        """
        if not access_token:
            raise ValueError("access_token must be a non-empty string")
        return self._call("/accounts/balance/get", {"access_token": access_token})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_transactions(
        self,
        *,
        access_token: str,
        start_date: str,
        end_date: str,
        count: int = 25,
        offset: int = 0,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Get transactions in a date range (legacy ``/transactions/get``).

        Returns compact summaries with ``transaction_ref``, name, amount
        (formatted with currency), date, merchant, category, and pending
        flag. Raw Plaid IDs are omitted unless ``include_ids=True``.
        Default ``count`` is 25; max 500 per Plaid's docs.

        Prefer :meth:`sync_transactions` for new integrations; Plaid steers
        all new work to the incremental ``/transactions/sync`` endpoint.
        """
        if not access_token or not start_date or not end_date:
            raise ValueError("access_token, start_date, and end_date must be non-empty")
        if count < 1 or count > 500:
            raise ValueError("count must be between 1 and 500")
        payload = self._call(
            "/transactions/get",
            {
                "access_token": access_token,
                "start_date": start_date,
                "end_date": end_date,
                "options": {"count": count, "offset": offset},
            },
        )
        transactions: list[Any] = payload.get("transactions", []) or []
        summaries: list[dict[str, Any]] = []
        for index, txn in enumerate(transactions, start=1):
            if not isinstance(txn, dict):
                continue
            txn_dict = cast("dict[str, Any]", txn)
            category: list[str] = txn_dict.get("category", []) or []
            summary: dict[str, Any] = {
                "transaction_ref": f"transaction_{index}",
                "name": txn_dict.get("name", ""),
                "merchant": txn_dict.get("merchant_name") or "",
                "amount": _format_amount(txn_dict.get("amount"), txn_dict.get("iso_currency_code")),
                "date": txn_dict.get("date"),
                "category": " > ".join(category),
                "pending": bool(txn_dict.get("pending")),
            }
            if include_ids:
                summary["transaction_id"] = txn_dict.get("transaction_id", "")
                summary["account_id"] = txn_dict.get("account_id", "")
            summaries.append(summary)
        total: Any = payload.get("total_transactions")
        return {
            "transactions": summaries,
            "total_transactions": total,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def sync_transactions(
        self,
        *,
        access_token: str,
        cursor: str | None = None,
        count: int = 100,
    ) -> dict[str, Any]:
        """Use Plaid's incremental ``/transactions/sync`` endpoint.

        Returns ``{"added": [...], "modified": [...], "removed": [...],
        "next_cursor": ..., "has_more": ...}``. Pass the returned cursor
        on subsequent calls to get only what's new.
        """
        if not access_token:
            raise ValueError("access_token must be a non-empty string")
        if count < 1 or count > 500:
            raise ValueError("count must be between 1 and 500")
        body: dict[str, Any] = {"access_token": access_token, "count": count}
        if cursor is not None:
            body["cursor"] = cursor
        return self._call("/transactions/sync", body)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_identity(self, access_token: str) -> dict[str, Any]:
        """Return identity attributes attached to an Item's accounts."""
        if not access_token:
            raise ValueError("access_token must be a non-empty string")
        return self._call("/identity/get", {"access_token": access_token})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_liabilities(self, access_token: str) -> dict[str, Any]:
        """Return liability accounts (loans, credit cards, student loans)."""
        if not access_token:
            raise ValueError("access_token must be a non-empty string")
        return self._call("/liabilities/get", {"access_token": access_token})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_institution(
        self,
        institution_id: str,
        *,
        country_codes: list[str],
    ) -> dict[str, Any]:
        """Return institution metadata by Plaid institution ID."""
        if not institution_id or not country_codes:
            raise ValueError("institution_id and country_codes must be non-empty")
        return self._call(
            "/institutions/get_by_id",
            {"institution_id": institution_id, "country_codes": country_codes},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_institutions(
        self,
        *,
        query: str,
        products: list[str] | None = None,
        country_codes: list[str],
    ) -> dict[str, Any]:
        """Search institutions by name (e.g. ``"chase"``)."""
        if not query or not country_codes:
            raise ValueError("query and country_codes must be non-empty")
        body: dict[str, Any] = {"query": query, "country_codes": country_codes}
        if products is not None:
            body["products"] = products
        return self._call("/institutions/search", body)

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def remove_item(self, access_token: str) -> dict[str, Any]:
        """Remove an Item from Plaid (revoke access).

        Destructive: future calls with the same access_token will fail.
        Confirm with the user before calling.
        """
        if not access_token:
            raise ValueError("access_token must be a non-empty string")
        return self._call("/item/remove", {"access_token": access_token})
