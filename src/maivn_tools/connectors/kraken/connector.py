"""Kraken Spot REST API connector.

Private endpoints require an API key + signed nonce. This connector
takes an :class:`AuthStrategy` so callers can plug in their own signer.
Public market-data endpoints work without authentication.

Order tools place real orders against the authenticated Kraken
account and are marked destructive. Kraken has no separate sandbox
host — pass ``validate=True`` to :meth:`add_order` to dry-run an order
without submitting it.
"""
# pyright: strict

from __future__ import annotations

import urllib.parse
from typing import Any, cast

from maivn import toolify, toolset

from ...auth.base import AuthStrategy, NoAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


def _form_body(params: dict[str, Any]) -> bytes:
    """Form-encode private POST parameters into a request body.

    Kraken Spot REST requires private POST parameters (including ``nonce``)
    to be sent as an ``application/x-www-form-urlencoded`` request body, and
    the ``API-Sign`` signature is computed over ``nonce + urlencode(body)``.
    Sending them via ``params=`` would place them in the URL query string with
    an empty body, breaking both the body contract and the signing recipe.
    """
    return urllib.parse.urlencode(params, doseq=True).encode("utf-8")


def _select_id_from_value(
    value: Any,
    keys: tuple[str, ...],
) -> str | None:
    """Walk a dict/list/string structure and return the first matching ID."""
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, dict):
        mapping = cast("dict[str, object]", value)
        for key in keys:
            candidate = mapping.get(key)
            if isinstance(candidate, str):
                text = candidate.strip()
                if text:
                    return text
        for nested in mapping.values():
            if isinstance(nested, dict | list | tuple):
                resolved = _select_id_from_value(nested, keys)
                if resolved is not None:
                    return resolved
        return None
    if isinstance(value, list | tuple):
        sequence = cast("list[object] | tuple[object, ...]", value)
        for item in sequence:
            resolved = _select_id_from_value(item, keys)
            if resolved is not None:
                return resolved
    return None


@toolset(prefix="kraken")
class KrakenToolSet:
    """A connector for Kraken Spot REST."""

    metadata = ProviderMetadata(
        name="kraken",
        display_name="Kraken",
        version="0.1.0",
        description="Balances, ledgers, trades, orders, and market data.",
        auth_modes=(AuthMode.CUSTOM,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.kraken.com/api/docs",
        homepage_url="https://www.kraken.com/",
        tags=("trading", "crypto"),
    )

    def __init__(
        self,
        *,
        auth: AuthStrategy | None = None,
        base_url: str = "https://api.kraken.com",
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

    # MARK: - Public

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def server_time(self) -> dict[str, Any]:
        """Return Kraken server time (unix and RFC1123).

        Useful for clock-drift checks before signing nonced requests.
        """
        return self._client.get("/0/public/Time").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def system_status(self) -> dict[str, Any]:
        """Return Kraken system status (``online``/``maintenance``/etc).

        Check this if write tools start failing — Kraken sometimes goes
        into ``cancel_only`` or ``post_only`` modes during maintenance.
        """
        return self._client.get("/0/public/SystemStatus").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_assets(self) -> dict[str, Any]:
        """List every supported asset on Kraken.

        Returns ``{"result": {"<asset>": {...}}}`` — Kraken uses
        prefixed asset codes (e.g. ``"XXBT"`` for BTC, ``"ZUSD"`` for
        USD).
        """
        return self._client.get("/0/public/Assets").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_asset_pairs(self, *, pair: str | None = None) -> dict[str, Any]:
        """List asset pairs, optionally filtered to a single pair.

        Returns ``{"result": {"<pair>": {...}}}``. Pair codes are
        Kraken-prefixed (e.g. ``"XXBTZUSD"`` for BTC/USD) — use this
        tool to discover the right pair string.
        """
        params: dict[str, Any] = {}
        if pair is not None:
            params["pair"] = pair
        return self._client.get(
            "/0/public/AssetPairs",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_ticker(self, pair: str) -> dict[str, Any]:
        """Get latest ticker info for a Kraken pair (best bid/ask, last, vwap).

        ``pair`` is the Kraken pair code (e.g. ``"XXBTZUSD"`` or its
        ``"BTCUSD"`` alias).
        """
        if not pair:
            raise ValueError("pair must be a non-empty string")
        return self._client.get(
            "/0/public/Ticker",
            params={"pair": pair},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_ohlc(
        self,
        *,
        pair: str,
        interval: int = 1,
        since: int | None = None,
    ) -> dict[str, Any]:
        """Get OHLC candles for a Kraken pair.

        ``interval`` is in minutes — Kraken supports 1, 5, 15, 30, 60,
        240, 1440, 10080, 21600. ``since`` is a unix timestamp for
        incremental fetches.
        """
        if not pair:
            raise ValueError("pair must be a non-empty string")
        params: dict[str, Any] = {"pair": pair, "interval": interval}
        if since is not None:
            params["since"] = since
        return self._client.get(
            "/0/public/OHLC",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_order_book(self, *, pair: str, count: int = 25) -> dict[str, Any]:
        """Get the order book for a Kraken pair.

        Returns ``{"result": {"<pair>": {"asks": [...], "bids": [...]}}}``.
        Default ``count`` is 25 levels per side (Kraken max 500).
        """
        if not pair:
            raise ValueError("pair must be a non-empty string")
        if count < 1 or count > 500:
            raise ValueError("count must be between 1 and 500")
        return self._client.get(
            "/0/public/Depth",
            params={"pair": pair, "count": count},
        ).json()

    # MARK: - Private

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_balance(self) -> dict[str, Any]:
        """Return account balances (one per asset).

        Returns ``{"result": {"<asset>": "<amount string>"}}``. Requires
        a signed nonce — use a callable :class:`AuthStrategy`.
        """
        return self._client.post(
            "/0/private/Balance",
            data=_form_body({"nonce": "0"}),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def open_orders(
        self,
        *,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List open orders on the account.

        Best first tool for Kraken order triage. Returns compact
        summaries with ``order_ref`` plus ``pair``, ``side`` (``type``
        from Kraken), ``ordertype``, ``status``, ``volume``,
        ``volume_executed``, ``price``, and ``opentm`` (unix open
        time).

        The Kraken ``txid`` (the handle :meth:`cancel_order` needs) is
        hidden by default — set ``include_ids=True`` to expose it.
        ``raw=True`` returns the unmodified Kraken response.
        """
        payload: dict[str, Any] = self._client.post(
            "/0/private/OpenOrders",
            data=_form_body({"nonce": "0"}),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ).json()
        if raw:
            return payload
        result = payload.get("result")
        result_map = cast("dict[str, object]", result) if isinstance(result, dict) else None
        open_orders = result_map.get("open") if result_map is not None else None
        if not isinstance(open_orders, dict):
            return {"orders": [], "count": 0}
        open_orders_map = cast("dict[str, object]", open_orders)
        summaries: list[dict[str, Any]] = []
        for index, (txid, order) in enumerate(open_orders_map.items(), start=1):
            if not isinstance(order, dict):
                continue
            order_map = cast("dict[str, object]", order)
            raw_descr = order_map.get("descr")
            descr = cast("dict[str, object]", raw_descr) if isinstance(raw_descr, dict) else {}
            summary: dict[str, Any] = {
                "order_ref": f"order_{index}",
                "pair": descr.get("pair", ""),
                "side": descr.get("type"),
                "ordertype": descr.get("ordertype"),
                "status": order_map.get("status"),
                "volume": order_map.get("vol"),
                "volume_executed": order_map.get("vol_exec"),
                "price": descr.get("price"),
                "opentm": order_map.get("opentm"),
            }
            if include_ids:
                summary["txid"] = txid
            summaries.append(summary)
        return {
            "orders": summaries,
            "count": len(summaries),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def closed_orders(
        self,
        *,
        start: int | None = None,
        end: int | None = None,
        ofs: int | None = None,
    ) -> dict[str, Any]:
        """List closed orders within an optional time range.

        Returns Kraken's raw ``{"result": {"closed": {"<txid>": {...}},
        "count": N}}``. ``start``/``end`` are unix timestamps; ``ofs``
        is a pagination offset.
        """
        params: dict[str, Any] = {"nonce": "0"}
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        if ofs is not None:
            params["ofs"] = ofs
        return self._client.post(
            "/0/private/ClosedOrders",
            data=_form_body(params),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def add_order(
        self,
        *,
        pair: str,
        type: str,
        ordertype: str,
        volume: str,
        price: str | None = None,
        leverage: str | None = None,
        validate: bool = False,
    ) -> dict[str, Any]:
        """Place an order. Destructive — places real orders.

        Confirm with the user before calling. ``type`` is ``"buy"`` or
        ``"sell"``. ``ordertype`` is one of Kraken's order types
        (``"market"``, ``"limit"``, ``"stop-loss"``, etc.).
        ``validate=True`` runs a dry-run that does not submit the order
        (recommended for testing). Returns Kraken's ack with ``descr``
        and ``txid`` (when placed).
        """
        if not pair or not type or not ordertype or not volume:
            raise ValueError("pair, type, ordertype, and volume are required")
        params: dict[str, Any] = {
            "nonce": "0",
            "pair": pair,
            "type": type,
            "ordertype": ordertype,
            "volume": volume,
        }
        if price is not None:
            params["price"] = price
        if leverage is not None:
            params["leverage"] = leverage
        if validate:
            params["validate"] = "true"
        return self._client.post(
            "/0/private/AddOrder",
            data=_form_body(params),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def cancel_order(self, *, txid: Any) -> dict[str, Any]:
        """Cancel an order. Destructive.

        Accepts either a raw Kraken ``txid`` string or an order dict
        returned by :meth:`open_orders` (with ``include_ids=True``).
        Returns Kraken's ``{"result": {"count": N}}`` ack.
        """
        resolved = _select_id_from_value(txid, ("txid", "order_id", "id"))
        if not resolved:
            raise ValueError("txid must be a non-empty string or order dict with txid")
        return self._client.post(
            "/0/private/CancelOrder",
            data=_form_body({"nonce": "0", "txid": resolved}),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_ledgers(self) -> dict[str, Any]:
        """List ledger entries (deposits, withdrawals, fees, trades).

        Returns Kraken's raw ledgers payload.
        """
        return self._client.post(
            "/0/private/Ledgers",
            data=_form_body({"nonce": "0"}),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def trade_history(self) -> dict[str, Any]:
        """List trade history (filled orders) for the account.

        Returns Kraken's raw trades-history payload.
        """
        return self._client.post(
            "/0/private/TradesHistory",
            data=_form_body({"nonce": "0"}),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ).json()
