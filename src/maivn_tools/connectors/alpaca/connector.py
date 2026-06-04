"""Alpaca Trading + Market Data API connector.

Order-placement tools are explicitly marked destructive — Alpaca live
trading uses real money. The default endpoint is the paper-trading host
(``https://paper-api.alpaca.markets``); callers must explicitly opt
into the live host with ``paper=False``.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.base import AuthStrategy
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


class _AlpacaAuth(AuthStrategy):
    """Alpaca uses two custom headers (API key + secret)."""

    mode = AuthMode.API_KEY

    def __init__(self, api_key: str, api_secret: str) -> None:
        if not api_key or not api_secret:
            raise ValueError("api_key and api_secret must be non-empty")
        self._key = api_key
        self._secret = api_secret

    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        headers = dict(request.get("headers") or {})
        headers["APCA-API-KEY-ID"] = self._key
        headers["APCA-API-SECRET-KEY"] = self._secret
        request["headers"] = headers
        return request

    def describe(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "headers": ["APCA-API-KEY-ID", "APCA-API-SECRET-KEY"]}


def _select_id_from_value(
    value: Any,
    keys: tuple[str, ...],
) -> str | None:
    """Walk a dict/list/string structure and return the first matching ID.

    Used by write tools that accept either a raw ID string or the dict
    returned by a list/get tool. Returns ``None`` if no candidate is
    found.
    """
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        mapping = cast("dict[Any, Any]", value)
        for key in keys:
            candidate = mapping.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
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


@toolset(prefix="alpaca")
class AlpacaToolSet:
    """A connector for Alpaca's broker and market-data APIs.

    Args:
        api_key: Alpaca API key ID.
        api_secret: Alpaca API secret.
        paper: Use paper-trading endpoint when True (default). When False,
            uses ``https://api.alpaca.markets`` (live trading — real money).
        data_url: Market-data endpoint.
    """

    metadata = ProviderMetadata(
        name="alpaca",
        display_name="Alpaca",
        version="0.1.0",
        description="Accounts, positions, orders, watchlists, and market data (paper-first).",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.alpaca.markets/",
        homepage_url="https://alpaca.markets/",
        tags=("trading", "brokerage"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        paper: bool = True,
        data_url: str = "https://data.alpaca.markets",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        self.connection = connection
        self._paper = paper
        base = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
        auth = _AlpacaAuth(api_key, api_secret)
        self._trading = HttpClient(
            base_url=base,
            auth=auth,
            transport=transport,
            default_headers={"Accept": "application/json"},
        )
        self._data = HttpClient(
            base_url=data_url.rstrip("/"),
            auth=auth,
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def trading_client(self) -> HttpClient:
        return self._trading

    @property
    def data_client(self) -> HttpClient:
        return self._data

    @property
    def _mode(self) -> str:
        return "paper" if self._paper else "live"

    # MARK: - Account / positions / activities

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_account(self) -> dict[str, Any]:
        """Return account details (cash, equity, buying power, status).

        Use this once at startup to confirm the API keys work and see
        how much buying power is available before placing orders.
        Returns Alpaca's account resource with fields like ``cash``,
        ``equity``, ``buying_power``, ``portfolio_value``, ``status``,
        and the ``account_number``.
        """
        return self._trading.get("/v2/account").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_positions(
        self,
        *,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List open positions held in the account.

        Best first tool for portfolio inspection. Returns compact summaries
        with a stable ``position_ref`` (``position_1``, ``position_2``, ...)
        plus human-readable fields: ``symbol``, ``qty``, ``side``,
        ``market_value``, ``avg_entry_price``, ``current_price``,
        ``unrealized_pl``, ``unrealized_plpc``, ``asset_class``.

        Raw provider IDs (``asset_id``) are internal handles and are
        hidden by default. Set ``include_ids=True`` only when a follow-up
        tool needs them. Set ``raw=True`` for the unmodified Alpaca
        response (full field set).

        To liquidate a returned position, pass the position dict (or its
        ``symbol``) to :meth:`close_position`.
        """
        positions: Any = self._trading.get("/v2/positions").json()
        if raw:
            return {"positions": positions, "mode": self._mode}
        items: list[Any] = cast("list[Any]", positions) if isinstance(positions, list) else []
        summaries: list[dict[str, Any]] = []
        for index, position in enumerate(items, start=1):
            if not isinstance(position, dict):
                continue
            position = cast("dict[Any, Any]", position)
            summary: dict[str, Any] = {
                "position_ref": f"position_{index}",
                "symbol": position.get("symbol", ""),
                "qty": position.get("qty"),
                "side": position.get("side"),
                "market_value": position.get("market_value"),
                "avg_entry_price": position.get("avg_entry_price"),
                "current_price": position.get("current_price"),
                "unrealized_pl": position.get("unrealized_pl"),
                "unrealized_plpc": position.get("unrealized_plpc"),
                "asset_class": position.get("asset_class"),
            }
            if include_ids:
                summary["asset_id"] = position.get("asset_id", "")
            summaries.append(summary)
        return {
            "positions": summaries,
            "count": len(summaries),
            "mode": self._mode,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_position(self, symbol: str) -> dict[str, Any]:
        """Return one position by symbol (e.g. ``"AAPL"``).

        Use after :meth:`list_positions` when you need every field of a
        single position. Raises ``404`` from Alpaca if the symbol is not
        currently held.
        """
        if not symbol:
            raise ValueError("symbol must be a non-empty string")
        return self._trading.get(f"/v2/positions/{symbol}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_activities(
        self,
        *,
        activity_types: list[str] | None = None,
        date: str | None = None,
        until: str | None = None,
        after: str | None = None,
        direction: str | None = None,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """List account activities (fills, dividends, transfers, fees).

        Returns the raw Alpaca activities list. Filter with
        ``activity_types=["FILL"]`` for execution history. Default
        ``page_size`` is 25 to keep responses small for triage.
        """
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")
        params: dict[str, Any] = {"page_size": page_size}
        if activity_types is not None:
            params["activity_types"] = ",".join(activity_types)
        if date is not None:
            params["date"] = date
        if until is not None:
            params["until"] = until
        if after is not None:
            params["after"] = after
        if direction is not None:
            params["direction"] = direction
        return self._trading.get("/v2/account/activities", params=params).json()

    # MARK: - Watchlists & assets

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_assets(
        self,
        *,
        status: str = "active",
        asset_class: str | None = None,
        exchange: str | None = None,
        limit: int = 25,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List tradable assets the account can place orders against.

        Returns compact summaries with ``asset_ref`` plus ``symbol``,
        ``name``, ``exchange``, ``asset_class``, ``tradable``,
        ``fractionable``, and ``shortable``. Use ``asset_class="crypto"``
        for crypto pairs, ``asset_class="us_equity"`` (default) for
        stocks/ETFs.

        Defaults to a 25-row preview because Alpaca returns thousands of
        rows. Set ``raw=True`` for the full list, or ``include_ids=True``
        for the internal ``asset_id`` UUIDs.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        params: dict[str, Any] = {"status": status}
        if asset_class is not None:
            params["asset_class"] = asset_class
        if exchange is not None:
            params["exchange"] = exchange
        assets: Any = self._trading.get("/v2/assets", params=params).json()
        if raw:
            return {"assets": assets, "mode": self._mode}
        items: list[Any] = cast("list[Any]", assets) if isinstance(assets, list) else []
        summaries: list[dict[str, Any]] = []
        for index, asset in enumerate(items[:limit], start=1):
            if not isinstance(asset, dict):
                continue
            asset = cast("dict[Any, Any]", asset)
            summary: dict[str, Any] = {
                "asset_ref": f"asset_{index}",
                "symbol": asset.get("symbol", ""),
                "name": asset.get("name", ""),
                "exchange": asset.get("exchange", ""),
                "asset_class": asset.get("class", asset.get("asset_class", "")),
                "tradable": asset.get("tradable"),
                "fractionable": asset.get("fractionable"),
                "shortable": asset.get("shortable"),
            }
            if include_ids:
                summary["asset_id"] = asset.get("id", "")
            summaries.append(summary)
        return {
            "assets": summaries,
            "count": len(summaries),
            "total_returned_by_provider": len(items),
            "limit": limit,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_watchlists(self) -> dict[str, Any]:
        """List watchlists configured on the account.

        Returns the raw Alpaca watchlist list — each entry has ``id``,
        ``name``, ``created_at``, and (in some responses) ``assets``.
        """
        return self._trading.get("/v2/watchlists").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_watchlist(self, *, name: str, symbols: list[str]) -> dict[str, Any]:
        """Create a watchlist named ``name`` with the given symbols.

        Returns the new watchlist resource. Non-destructive — watchlists
        cannot place orders.
        """
        if not name or not symbols:
            raise ValueError("name and symbols must be non-empty")
        return self._trading.post(
            "/v2/watchlists",
            json={"name": name, "symbols": symbols},
        ).json()

    # MARK: - Orders

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_orders(
        self,
        *,
        status: str = "open",
        limit: int = 25,
        after: str | None = None,
        until: str | None = None,
        direction: str = "desc",
        symbols: list[str] | None = None,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List orders, defaulting to currently-open orders.

        Best first tool for order triage. Returns compact summaries with
        a stable ``order_ref`` plus ``symbol``, ``side``, ``qty``,
        ``filled_qty``, ``type``, ``status``, ``limit_price``,
        ``stop_price``, ``submitted_at``, and ``time_in_force``.

        Internal IDs (``order_id``, ``client_order_id``) are hidden by
        default. Set ``include_ids=True`` when a follow-up tool
        (:meth:`cancel_order`) needs them. ``raw=True`` returns the
        unmodified Alpaca response.

        To cancel a returned order, pass the order dict (or its
        ``order_id``) to :meth:`cancel_order`.
        """
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        params: dict[str, Any] = {"status": status, "limit": limit, "direction": direction}
        if after is not None:
            params["after"] = after
        if until is not None:
            params["until"] = until
        if symbols is not None:
            params["symbols"] = ",".join(symbols)
        orders: Any = self._trading.get("/v2/orders", params=params).json()
        if raw:
            return {"orders": orders, "mode": self._mode}
        items: list[Any] = cast("list[Any]", orders) if isinstance(orders, list) else []
        summaries: list[dict[str, Any]] = []
        for index, order in enumerate(items, start=1):
            if not isinstance(order, dict):
                continue
            order = cast("dict[Any, Any]", order)
            summary: dict[str, Any] = {
                "order_ref": f"order_{index}",
                "symbol": order.get("symbol", ""),
                "side": order.get("side"),
                "qty": order.get("qty"),
                "filled_qty": order.get("filled_qty"),
                "type": order.get("type"),
                "status": order.get("status"),
                "limit_price": order.get("limit_price"),
                "stop_price": order.get("stop_price"),
                "submitted_at": order.get("submitted_at"),
                "time_in_force": order.get("time_in_force"),
            }
            if include_ids:
                summary["order_id"] = order.get("id", "")
                summary["client_order_id"] = order.get("client_order_id", "")
            summaries.append(summary)
        return {
            "orders": summaries,
            "count": len(summaries),
            "status_filter": status,
            "mode": self._mode,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_order(self, order_id: str) -> dict[str, Any]:
        """Return one order by its internal Alpaca ID.

        Use after :meth:`list_orders` (with ``include_ids=True``) to
        inspect a specific order's full fields.
        """
        if not order_id:
            raise ValueError("order_id must be a non-empty string")
        return self._trading.get(f"/v2/orders/{order_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def submit_order(
        self,
        *,
        symbol: str,
        qty: float | None = None,
        notional: float | None = None,
        side: str,
        type: str = "market",
        time_in_force: str = "day",
        limit_price: float | None = None,
        stop_price: float | None = None,
        client_order_id: str | None = None,
        extended_hours: bool | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Submit an order against the account. Destructive — places real orders.

        Confirm with the user before calling, especially when the
        connector was initialized with ``paper=False``. Provide exactly
        one of ``qty`` (share count) or ``notional`` (dollar amount).
        ``side`` is ``"buy"`` or ``"sell"``; ``type`` is ``"market"``,
        ``"limit"``, ``"stop"``, or ``"stop_limit"``. Returns the new
        Alpaca order resource (with ``id``, ``status``, ``symbol``,
        ``qty``, etc.).
        """
        if not symbol or not side:
            raise ValueError("symbol and side must be non-empty")
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        if qty is None and notional is None:
            raise ValueError("provide qty or notional")
        body: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": type,
            "time_in_force": time_in_force,
        }
        if qty is not None:
            body["qty"] = qty
        if notional is not None:
            body["notional"] = notional
        if limit_price is not None:
            body["limit_price"] = limit_price
        if stop_price is not None:
            body["stop_price"] = stop_price
        if client_order_id is not None:
            body["client_order_id"] = client_order_id
        if extended_hours is not None:
            body["extended_hours"] = extended_hours
        response = self._trading.post(
            "/v2/orders",
            json=body,
            idempotency_key=idempotency_key,
        )
        return response.json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def cancel_order(self, order: Any) -> dict[str, Any]:
        """Cancel an open order. Destructive.

        Accepts either a raw Alpaca order ID string or an order dict
        returned by :meth:`list_orders` (with ``include_ids=True``) or
        :meth:`get_order`. Returns ``{"id": <id>, "cancelled": True,
        "status": <http-status>}``. Confirm with the user before
        calling.
        """
        order_id = _select_id_from_value(order, ("order_id", "id", "client_order_id"))
        if not order_id:
            raise ValueError("order must be an order id or order dict with an id")
        response = self._trading.delete(f"/v2/orders/{order_id}")
        return {"id": order_id, "cancelled": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def cancel_all_orders(self) -> dict[str, Any]:
        """Cancel every open order on the account. Destructive.

        Returns ``{"cancelled": [...], "status": <http-status>}``.
        Confirm with the user before calling — this affects every
        pending order in the account at once.
        """
        response = self._trading.delete("/v2/orders")
        try:
            return {"cancelled": response.json(), "status": response.status}
        except ValueError:
            return {"status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def close_position(
        self,
        position: Any,
        *,
        qty: float | None = None,
    ) -> dict[str, Any]:
        """Liquidate a position by submitting an offsetting market order. Destructive.

        Accepts either a symbol string (e.g. ``"AAPL"``) or a position
        dict returned by :meth:`list_positions`. Pass ``qty`` to
        liquidate a partial position; omit it to close the whole
        position. Confirm with the user before calling.
        """
        symbol = _select_id_from_value(position, ("symbol",))
        if not symbol:
            raise ValueError("position must be a symbol or position dict with a symbol")
        params: dict[str, Any] = {}
        if qty is not None:
            params["qty"] = qty
        return self._trading.delete(
            f"/v2/positions/{symbol}",
            params=params or None,
        ).json()

    # MARK: - Market data

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_latest_quote(
        self,
        symbol: str,
        *,
        feed: str | None = None,
    ) -> dict[str, Any]:
        """Return the latest NBBO quote for an equity symbol.

        Returns Alpaca's ``{"quote": {"bp": bid, "ap": ask, "bs": bid
        size, "as": ask size, "t": timestamp}, "symbol": ...}``.
        ``feed`` is ``"iex"`` (free tier) or ``"sip"`` (paid). When
        omitted, Alpaca selects the best feed available for the
        account's subscription.
        """
        if not symbol:
            raise ValueError("symbol must be a non-empty string")
        params: dict[str, Any] = {}
        if feed is not None:
            params["feed"] = feed
        return self._data.get(
            f"/v2/stocks/{symbol}/quotes/latest",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_latest_trade(self, symbol: str, *, feed: str | None = None) -> dict[str, Any]:
        """Return the latest trade for an equity symbol.

        Returns ``{"trade": {"p": price, "s": size, "t": timestamp},
        "symbol": ...}``. ``feed`` is ``"iex"`` (free) or ``"sip"``
        (paid). When omitted, Alpaca selects the best feed available for
        the account's subscription.
        """
        if not symbol:
            raise ValueError("symbol must be a non-empty string")
        params: dict[str, Any] = {}
        if feed is not None:
            params["feed"] = feed
        return self._data.get(
            f"/v2/stocks/{symbol}/trades/latest",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_bars(
        self,
        symbol: str,
        *,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 100,
        feed: str | None = None,
    ) -> dict[str, Any]:
        """Return historical OHLCV bars (candles) for an equity symbol.

        ``timeframe`` is e.g. ``"1Min"``, ``"5Min"``, ``"1Hour"``,
        ``"1Day"``. ``start``/``end`` are RFC-3339 timestamps. Default
        ``limit`` is 100; pass up to 10_000 for larger backfills.
        ``feed`` is ``"iex"`` (free) or ``"sip"`` (paid); when omitted,
        Alpaca selects the best feed available for the account's
        subscription. Returns ``{"bars": [...], "symbol": ...,
        "next_page_token": ...}``.
        """
        if not symbol or not timeframe:
            raise ValueError("symbol and timeframe must be non-empty")
        if limit < 1 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        params: dict[str, Any] = {"timeframe": timeframe, "limit": limit}
        if feed is not None:
            params["feed"] = feed
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        return self._data.get(
            f"/v2/stocks/{symbol}/bars",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_clock(self) -> dict[str, Any]:
        """Return the current market clock (is the market open right now?).

        Returns ``{"timestamp": ..., "is_open": bool, "next_open": ...,
        "next_close": ...}``.
        """
        return self._trading.get("/v2/clock").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_calendar(self, *, start: str | None = None, end: str | None = None) -> dict[str, Any]:
        """Return the trading calendar between two dates (YYYY-MM-DD).

        Returns ``[{"date": ..., "open": ..., "close": ...}]`` — useful
        for planning around holidays and half-days.
        """
        params: dict[str, Any] = {}
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        return self._trading.get("/v2/calendar", params=params or None).json()
