"""Binance Spot REST API connector.

Signed endpoints require HMAC SHA256 of the query string with the API
secret. This connector takes an :class:`AuthStrategy` so callers can
plug in their own signer. Public endpoints work without signing.

Order tools place real orders against the authenticated Binance
account and are marked destructive. Pass ``test=True`` to
:meth:`new_order` to hit the ``/api/v3/order/test`` endpoint, which
validates the order without submitting it. For a separate sandbox
host, point ``base_url`` at ``https://testnet.binance.vision``.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...auth.base import AuthStrategy
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: - Helpers


def _select_id_from_value(
    value: Any,
    keys: tuple[str, ...],
) -> str | None:
    """Walk a dict/list/string structure and return the first matching ID."""
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, int) and not isinstance(value, bool):
        if value == 0:
            return None
        return str(value)
    if isinstance(value, dict):
        mapping = cast("dict[Any, Any]", value)
        for key in keys:
            candidate: Any = mapping.get(key)
            resolved = _select_id_from_value(candidate, keys)
            if resolved is not None:
                return resolved
        for nested in mapping.values():
            if isinstance(nested, dict | list | tuple):
                resolved = _select_id_from_value(nested, keys)
                if resolved is not None:
                    return resolved
        return None
    if isinstance(value, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", value)
        for item in sequence:
            resolved = _select_id_from_value(item, keys)
            if resolved is not None:
                return resolved
    return None


# MARK: - Connector


@toolset(prefix="binance")
class BinanceToolSet:
    """A connector for the Binance Spot REST API.

    Args:
        api_key: Binance API key (sent as the ``X-MBX-APIKEY`` header).
        auth: Optional custom :class:`AuthStrategy` (for HMAC signing).
        base_url: Defaults to live Binance. Use
            ``"https://testnet.binance.vision"`` for the testnet sandbox.
    """

    metadata = ProviderMetadata(
        name="binance",
        display_name="Binance Spot",
        version="0.1.0",
        description="Account, balances, orders, trades, and market data.",
        auth_modes=(AuthMode.API_KEY, AuthMode.CUSTOM),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developers.binance.com/docs/binance-spot-api-docs/rest-api",
        homepage_url="https://www.binance.com/",
        tags=("trading", "crypto"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        auth: AuthStrategy | None = None,
        base_url: str = "https://api.binance.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        # Always set X-MBX-APIKEY; callers can layer their own signer over
        # the params via a custom transport / auth.
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=auth or ApiKeyAuth(api_key, header="X-MBX-APIKEY"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def server_time(self) -> dict[str, Any]:
        """Return Binance server time in milliseconds.

        Useful for clock-drift checks before issuing signed requests.
        """
        return self._client.get("/api/v3/time").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def exchange_info(self, *, symbol: str | None = None) -> dict[str, Any]:
        """Return exchange info (symbols, filters, rate limits).

        Filter to a single symbol (e.g. ``"BTCUSDT"``) to see its trade
        rules, lot size, and tick size.
        """
        params: dict[str, Any] = {}
        if symbol is not None:
            params["symbol"] = symbol
        return self._client.get(
            "/api/v3/exchangeInfo",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def ticker_price(self, *, symbol: str | None = None) -> dict[str, Any]:
        """Latest price for one symbol, or every symbol if omitted.

        Returns ``{"symbol": ..., "price": ...}`` for a single symbol or
        a list of such dicts for all symbols.
        """
        params: dict[str, Any] = {}
        if symbol is not None:
            params["symbol"] = symbol
        return self._client.get(
            "/api/v3/ticker/price",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def ticker_24h(self, *, symbol: str | None = None) -> dict[str, Any]:
        """24-hour rolling stats for one symbol (or all).

        Returns ``{"symbol": ..., "lastPrice": ..., "priceChange": ...,
        "priceChangePercent": ..., "volume": ..., ...}``.
        """
        params: dict[str, Any] = {}
        if symbol is not None:
            params["symbol"] = symbol
        return self._client.get(
            "/api/v3/ticker/24hr",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get k-line / candlestick data for a symbol.

        ``interval`` is a Binance enum (``"1m"``, ``"5m"``, ``"1h"``,
        ``"1d"``, etc.). ``start_time``/``end_time`` are millisecond
        unix timestamps. Default ``limit`` is 100; Binance max is 1000.
        Returns a list of ``[open_time, open, high, low, close, volume,
        close_time, ...]`` arrays.
        """
        if not symbol or not interval:
            raise ValueError("symbol and interval must be non-empty")
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        return self._client.get("/api/v3/klines", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def order_book(self, *, symbol: str, limit: int = 25) -> dict[str, Any]:
        """Order book snapshot for a symbol.

        Returns ``{"bids": [[price, qty], ...], "asks": [...]}``.
        Default ``limit`` is 25; Binance valid values: 5, 10, 20, 50,
        100, 500, 1000, 5000.
        """
        if not symbol:
            raise ValueError("symbol must be a non-empty string")
        return self._client.get(
            "/api/v3/depth",
            params={"symbol": symbol, "limit": limit},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def recent_trades(self, *, symbol: str, limit: int = 25) -> dict[str, Any]:
        """Recent public trades for a symbol.

        Default ``limit`` is 25; Binance max is 1000.
        """
        if not symbol:
            raise ValueError("symbol must be a non-empty string")
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        return self._client.get(
            "/api/v3/trades",
            params={"symbol": symbol, "limit": limit},
        ).json()

    # MARK: - Signed (private) endpoints

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def account(
        self,
        *,
        timestamp: int,
        signature: str,
        recv_window: int | None = None,
    ) -> dict[str, Any]:
        """Return account info (balances per asset, account type, permissions).

        Caller must provide ``timestamp`` (ms since epoch) and
        ``signature`` (HMAC-SHA256 of the query string). Returns
        Binance's ``{"makerCommission": ..., "balances": [...], ...}``
        payload.

        ``recv_window`` (max 60000) sets the millisecond tolerance for
        clock drift; when supplied it is sent as ``recvWindow`` and must
        be included in the signed payload (the HMAC) by the caller.
        """
        params: dict[str, Any] = {"timestamp": timestamp, "signature": signature}
        if recv_window is not None:
            params["recvWindow"] = recv_window
        return self._client.get(
            "/api/v3/account",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_open_orders(
        self,
        *,
        timestamp: int,
        signature: str,
        symbol: str | None = None,
        include_ids: bool = False,
        raw: bool = False,
        recv_window: int | None = None,
    ) -> dict[str, Any]:
        """List open orders, optionally filtered by symbol.

        Best first tool for Binance order triage. Returns compact
        summaries with ``order_ref`` plus ``symbol``, ``side``,
        ``type``, ``status``, ``orig_qty``, ``executed_qty``,
        ``price``, ``stop_price``, ``time_in_force``, and ``time``.

        The Binance ``order_id`` and ``client_order_id`` are hidden by
        default — set ``include_ids=True`` to expose them for
        :meth:`cancel_order`. ``raw=True`` returns the unmodified
        Binance response.

        ``recv_window`` (max 60000) sets the millisecond tolerance for
        clock drift; when supplied it is sent as ``recvWindow`` and must
        be included in the signed payload (the HMAC) by the caller.
        """
        params: dict[str, Any] = {"timestamp": timestamp, "signature": signature}
        if symbol is not None:
            params["symbol"] = symbol
        if recv_window is not None:
            params["recvWindow"] = recv_window
        payload: Any = self._client.get(
            "/api/v3/openOrders",
            params=params,
        ).json()
        if raw:
            return payload
        items: list[Any] = cast("list[Any]", payload) if isinstance(payload, list) else []
        summaries: list[dict[str, Any]] = []
        for index, order in enumerate(items, start=1):
            if not isinstance(order, dict):
                continue
            order_dict = cast("dict[Any, Any]", order)
            summary: dict[str, Any] = {
                "order_ref": f"order_{index}",
                "symbol": order_dict.get("symbol", ""),
                "side": order_dict.get("side"),
                "type": order_dict.get("type"),
                "status": order_dict.get("status"),
                "orig_qty": order_dict.get("origQty"),
                "executed_qty": order_dict.get("executedQty"),
                "price": order_dict.get("price"),
                "stop_price": order_dict.get("stopPrice"),
                "time_in_force": order_dict.get("timeInForce"),
                "time": order_dict.get("time"),
            }
            if include_ids:
                summary["order_id"] = order_dict.get("orderId")
                summary["client_order_id"] = order_dict.get("clientOrderId", "")
            summaries.append(summary)
        return {
            "orders": summaries,
            "count": len(summaries),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def new_order(
        self,
        *,
        symbol: str,
        side: str,
        type: str,
        quantity: str | None = None,
        quote_order_qty: str | None = None,
        price: str | None = None,
        time_in_force: str | None = None,
        timestamp: int,
        signature: str,
        test: bool = False,
        recv_window: int | None = None,
    ) -> dict[str, Any]:
        """Place an order, or validate it with ``test=True``. Destructive.

        Confirm with the user before calling with ``test=False`` on a
        live host. ``side`` is ``"BUY"`` or ``"SELL"``. ``type`` is
        ``"LIMIT"``, ``"MARKET"``, ``"STOP_LOSS"``,
        ``"STOP_LOSS_LIMIT"``, etc. ``test=True`` hits
        ``/api/v3/order/test`` and returns an empty success without
        submitting.

        ``recv_window`` (max 60000) sets the millisecond tolerance for
        clock drift; when supplied it is sent as ``recvWindow`` and must
        be included in the signed payload (the HMAC) by the caller.
        """
        if not symbol or not side or not type:
            raise ValueError("symbol, side, and type are required")
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": type,
            "timestamp": timestamp,
            "signature": signature,
        }
        if quantity is not None:
            params["quantity"] = quantity
        if quote_order_qty is not None:
            params["quoteOrderQty"] = quote_order_qty
        if price is not None:
            params["price"] = price
        if time_in_force is not None:
            params["timeInForce"] = time_in_force
        if recv_window is not None:
            params["recvWindow"] = recv_window
        path = "/api/v3/order/test" if test else "/api/v3/order"
        return self._client.post(path, params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def cancel_order(
        self,
        *,
        symbol: str,
        timestamp: int,
        signature: str,
        order: Any = None,
        order_id: int | None = None,
        orig_client_order_id: str | None = None,
        recv_window: int | None = None,
    ) -> dict[str, Any]:
        """Cancel an order. Destructive.

        Accepts either explicit ``order_id`` / ``orig_client_order_id``,
        or an ``order`` dict returned by :meth:`list_open_orders` (with
        ``include_ids=True``). ``symbol`` is always required by
        Binance.

        ``recv_window`` (max 60000) sets the millisecond tolerance for
        clock drift; when supplied it is sent as ``recvWindow`` and must
        be included in the signed payload (the HMAC) by the caller.
        """
        if not symbol:
            raise ValueError("symbol must be a non-empty string")
        if order is not None and order_id is None and orig_client_order_id is None:
            resolved_id = _select_id_from_value(order, ("order_id", "orderId"))
            if resolved_id and resolved_id.isdigit():
                order_id = int(resolved_id)
            elif resolved_id:
                orig_client_order_id = resolved_id
            else:
                client_id = _select_id_from_value(order, ("client_order_id", "clientOrderId"))
                if client_id:
                    orig_client_order_id = client_id
        if order_id is None and orig_client_order_id is None:
            raise ValueError("provide order, order_id, or orig_client_order_id")
        params: dict[str, Any] = {
            "symbol": symbol,
            "timestamp": timestamp,
            "signature": signature,
        }
        if order_id is not None:
            params["orderId"] = order_id
        if orig_client_order_id is not None:
            params["origClientOrderId"] = orig_client_order_id
        if recv_window is not None:
            params["recvWindow"] = recv_window
        return self._client.delete("/api/v3/order", params=params).json()
