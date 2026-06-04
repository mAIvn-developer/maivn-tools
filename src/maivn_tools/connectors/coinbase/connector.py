"""Coinbase Advanced Trade API connector.

Authentication requires a CDP API key + JWT signing. This connector
takes an :class:`AuthStrategy` so callers can provide their own JWT
signer (e.g. via ``coinbase-advanced-py``). The default :class:`NoAuth`
strategy is suitable for mocked tests.

Order tools place real orders against the authenticated Coinbase
account and are marked destructive. Coinbase does not provide a
separate sandbox host for Advanced Trade — confirm with the user before
calling :meth:`create_order` or :meth:`cancel_orders`.
"""

# pyright: strict
from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.base import AuthStrategy, NoAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Helpers


def _collect_ids_from_value(
    value: Any,
    keys: tuple[str, ...],
) -> list[str]:
    """Walk a dict/list/string structure and collect all matching IDs."""
    out: list[str] = []

    def visit(v: Any) -> None:
        if isinstance(v, str):
            text = v.strip()
            if text:
                out.append(text)
            return
        if isinstance(v, dict):
            mapping = cast(dict[Any, Any], v)
            for key in keys:
                candidate = mapping.get(key)
                if isinstance(candidate, str):
                    text = candidate.strip()
                    if text and text not in out:
                        out.append(text)
            for nested in mapping.values():
                if isinstance(nested, dict | list | tuple):
                    visit(nested)
            return
        if isinstance(v, list | tuple):
            for item in cast("list[Any] | tuple[Any, ...]", v):
                visit(item)

    visit(value)
    return out


# MARK: ToolSet


@toolset(prefix="coinbase")
class CoinbaseToolSet:
    """A connector for Coinbase Advanced Trade REST API."""

    metadata = ProviderMetadata(
        name="coinbase",
        display_name="Coinbase Advanced Trade",
        version="0.1.0",
        description="Accounts, products, orders, fills, and portfolios.",
        auth_modes=(AuthMode.CUSTOM,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.cdp.coinbase.com/advanced-trade/docs/welcome",
        homepage_url="https://www.coinbase.com/",
        tags=("trading", "crypto"),
    )

    def __init__(
        self,
        *,
        auth: AuthStrategy | None = None,
        base_url: str = "https://api.coinbase.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=auth or NoAuth(),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_accounts(
        self,
        *,
        limit: int = 25,
        cursor: str | None = None,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List Coinbase accounts (one per asset).

        Best first tool for portfolio inspection. Returns compact
        summaries with ``account_ref`` plus ``name``, ``currency``,
        ``available_balance``, ``hold``, ``type``, ``active``,
        ``default``. ``available_balance`` is a ``{"value": str,
        "currency": str}`` shape from Coinbase.

        The provider ``account_uuid`` is hidden by default — set
        ``include_ids=True`` to expose it for :meth:`get_account`.
        ``raw=True`` returns the unmodified Coinbase response. Default
        ``limit`` is 25 (Coinbase max 250).
        """
        if limit < 1 or limit > 250:
            raise ValueError("limit must be between 1 and 250")
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        payload: Any = self._client.get("/api/v3/brokerage/accounts", params=params).json()
        if raw:
            return cast(dict[str, Any], payload)
        raw_items: Any = (
            cast(dict[str, Any], payload).get("accounts") if isinstance(payload, dict) else None
        )
        items: list[Any] = cast(list[Any], raw_items) if isinstance(raw_items, list) else []
        summaries: list[dict[str, Any]] = []
        for index, account_value in enumerate(items, start=1):
            if not isinstance(account_value, dict):
                continue
            account = cast(dict[str, Any], account_value)
            summary: dict[str, Any] = {
                "account_ref": f"account_{index}",
                "name": account.get("name", ""),
                "currency": account.get("currency", ""),
                "available_balance": account.get("available_balance"),
                "hold": account.get("hold"),
                "type": account.get("type", ""),
                "active": account.get("active"),
                "default": account.get("default"),
            }
            if include_ids:
                summary["account_uuid"] = account.get("uuid", "")
            summaries.append(summary)
        return {
            "accounts": summaries,
            "count": len(summaries),
            "cursor": cast(dict[str, Any], payload).get("cursor")
            if isinstance(payload, dict)
            else None,
            "has_next": cast(dict[str, Any], payload).get("has_next")
            if isinstance(payload, dict)
            else None,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_account(self, account_uuid: str) -> dict[str, Any]:
        """Return a single Coinbase account by its UUID.

        Use after :meth:`list_accounts` (with ``include_ids=True``) when
        you need every field of a specific account.
        """
        if not account_uuid:
            raise ValueError("account_uuid must be a non-empty string")
        return self._client.get(f"/api/v3/brokerage/accounts/{account_uuid}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_products(
        self,
        *,
        product_type: str | None = None,
        limit: int = 25,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List trading pairs (products) available on Coinbase.

        Returns compact summaries with ``product_ref`` plus
        ``product_id`` (e.g. ``"BTC-USD"`` — already user-facing, kept
        in the summary), ``base_currency``, ``quote_currency``,
        ``status``, ``price``, ``price_percentage_change_24h``,
        ``volume_24h``, and ``trading_disabled``.

        ``product_type`` is e.g. ``"SPOT"``. Default ``limit`` is 25;
        Coinbase returns 1000 by default. Set ``raw=True`` for the
        unmodified response.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        params: dict[str, Any] = {"limit": limit}
        if product_type is not None:
            params["product_type"] = product_type
        payload: Any = self._client.get(
            "/api/v3/brokerage/products",
            params=params,
        ).json()
        if raw:
            return cast(dict[str, Any], payload)
        raw_items: Any = (
            cast(dict[str, Any], payload).get("products") if isinstance(payload, dict) else None
        )
        items: list[Any] = cast(list[Any], raw_items) if isinstance(raw_items, list) else []
        summaries: list[dict[str, Any]] = []
        for index, product_value in enumerate(items, start=1):
            if not isinstance(product_value, dict):
                continue
            product = cast(dict[str, Any], product_value)
            summaries.append(
                {
                    "product_ref": f"product_{index}",
                    "product_id": product.get("product_id", ""),
                    "base_currency": product.get("base_currency_id", ""),
                    "quote_currency": product.get("quote_currency_id", ""),
                    "status": product.get("status", ""),
                    "price": product.get("price"),
                    "price_percentage_change_24h": product.get("price_percentage_change_24h"),
                    "volume_24h": product.get("volume_24h"),
                    "trading_disabled": product.get("trading_disabled"),
                }
            )
        return {
            "products": summaries,
            "count": len(summaries),
            "num_products": cast(dict[str, Any], payload).get("num_products")
            if isinstance(payload, dict)
            else None,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_product(self, product_id: str) -> dict[str, Any]:
        """Return full details for one trading pair (e.g. ``"BTC-USD"``)."""
        if not product_id:
            raise ValueError("product_id must be a non-empty string")
        return self._client.get(f"/api/v3/brokerage/products/{product_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_product_candles(
        self,
        *,
        product_id: str,
        start: str,
        end: str,
        granularity: str,
    ) -> dict[str, Any]:
        """Get historical OHLC candles for a product.

        ``start``/``end`` are unix timestamps (string form).
        ``granularity`` is one of Coinbase's granularity enums (e.g.
        ``"ONE_MINUTE"``, ``"FIVE_MINUTE"``, ``"ONE_HOUR"``,
        ``"ONE_DAY"``). Returns ``{"candles": [...]}``.
        """
        if not product_id:
            raise ValueError("product_id must be a non-empty string")
        return self._client.get(
            f"/api/v3/brokerage/products/{product_id}/candles",
            params={"start": start, "end": end, "granularity": granularity},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_market_trades(
        self,
        *,
        product_id: str,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Get recent market trades / ticker for a product.

        Returns ``{"trades": [...], "best_bid": ..., "best_ask": ...}``.
        Default ``limit`` is 25; Coinbase max is 1000.
        """
        if not product_id:
            raise ValueError("product_id must be a non-empty string")
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        return self._client.get(
            f"/api/v3/brokerage/products/{product_id}/ticker",
            params={"limit": limit},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_orders(
        self,
        *,
        product_id: str | None = None,
        order_status: list[str] | None = None,
        cursor: str | None = None,
        limit: int = 25,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List historical / open orders.

        Best first tool for order triage. Returns compact summaries
        with ``order_ref`` plus ``product_id``, ``side``,
        ``order_type``, ``status``, ``filled_size``, ``average_filled_price``,
        ``time_in_force``, and ``created_time``.

        The Coinbase ``order_id`` is hidden by default — set
        ``include_ids=True`` to expose it for :meth:`cancel_orders`.
        ``raw=True`` returns the unmodified response.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        params: dict[str, Any] = {"limit": limit}
        if product_id is not None:
            params["product_id"] = product_id
        if order_status is not None:
            params["order_status"] = ",".join(order_status)
        if cursor is not None:
            params["cursor"] = cursor
        payload: Any = self._client.get(
            "/api/v3/brokerage/orders/historical/batch",
            params=params,
        ).json()
        if raw:
            return cast(dict[str, Any], payload)
        raw_items: Any = (
            cast(dict[str, Any], payload).get("orders") if isinstance(payload, dict) else None
        )
        items: list[Any] = cast(list[Any], raw_items) if isinstance(raw_items, list) else []
        summaries: list[dict[str, Any]] = []
        for index, order_value in enumerate(items, start=1):
            if not isinstance(order_value, dict):
                continue
            order = cast(dict[str, Any], order_value)
            summary: dict[str, Any] = {
                "order_ref": f"order_{index}",
                "product_id": order.get("product_id", ""),
                "side": order.get("side"),
                "order_type": order.get("order_type"),
                "status": order.get("status"),
                "filled_size": order.get("filled_size"),
                "average_filled_price": order.get("average_filled_price"),
                "time_in_force": order.get("time_in_force"),
                "created_time": order.get("created_time", ""),
            }
            if include_ids:
                summary["order_id"] = order.get("order_id", "")
                client_order_id = order.get("client_order_id")
                if client_order_id:
                    summary["client_order_id"] = client_order_id
            summaries.append(summary)
        return {
            "orders": summaries,
            "count": len(summaries),
            "cursor": cast(dict[str, Any], payload).get("cursor")
            if isinstance(payload, dict)
            else None,
            "has_next": cast(dict[str, Any], payload).get("has_next")
            if isinstance(payload, dict)
            else None,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_fills(
        self,
        *,
        order_id: str | None = None,
        product_id: str | None = None,
        cursor: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        """List fills (executed trades).

        Returns Coinbase's raw fills payload (``{"fills": [...]}``).
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        params: dict[str, Any] = {"limit": limit}
        if order_id is not None:
            params["order_id"] = order_id
        if product_id is not None:
            params["product_id"] = product_id
        if cursor is not None:
            params["cursor"] = cursor
        return self._client.get(
            "/api/v3/brokerage/orders/historical/fills",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Place an order. Destructive — places real orders.

        Coinbase Advanced Trade has no separate sandbox host. Confirm
        with the user before calling. ``payload`` is the Coinbase order
        body (``client_order_id``, ``product_id``, ``side``,
        ``order_configuration``).
        """
        if not payload:
            raise ValueError("payload must be non-empty")
        return self._client.post(
            "/api/v3/brokerage/orders",
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def cancel_orders(self, orders: Any) -> dict[str, Any]:
        """Cancel one or more orders. Destructive.

        Accepts a raw ``order_id`` string, a list of strings, or the
        order dicts/list returned by :meth:`list_orders` (with
        ``include_ids=True``). Confirm with the user before calling.
        Returns Coinbase's cancel result payload.
        """
        order_ids = _collect_ids_from_value(orders, ("order_id", "id"))
        if not order_ids:
            raise ValueError("orders must contain at least one order id")
        return self._client.post(
            "/api/v3/brokerage/orders/batch_cancel",
            json={"order_ids": order_ids},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_portfolios(self, *, portfolio_type: str | None = None) -> dict[str, Any]:
        """List portfolios on the account.

        Returns Coinbase's ``{"portfolios": [...]}`` payload.
        """
        params: dict[str, Any] = {}
        if portfolio_type is not None:
            params["portfolio_type"] = portfolio_type
        return self._client.get(
            "/api/v3/brokerage/portfolios",
            params=params or None,
        ).json()
