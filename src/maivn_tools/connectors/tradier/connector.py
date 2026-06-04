"""Tradier brokerage + market-data API connector.

Defaults to the sandbox endpoint so misuse without explicit opt-in does
not place real orders. Order tools are marked destructive.
"""
# pyright: strict

from __future__ import annotations

import urllib.parse
from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Helpers


def _select_id_from_value(
    value: Any,
    keys: tuple[str, ...],
) -> str | None:
    """Walk a dict/list/string structure and return the first matching ID.

    Used by write tools that accept either a raw ID string or the dict
    returned by a list/get tool. Falsy values (empty strings, zero) are
    rejected — Tradier order IDs are positive integers.
    """
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, int) and not isinstance(value, bool):
        if value == 0:
            return None
        return str(value)
    if isinstance(value, dict):
        value_dict = cast("dict[str, Any]", value)
        for key in keys:
            candidate: Any = value_dict.get(key)
            resolved = _select_id_from_value(candidate, keys)
            if resolved is not None:
                return resolved
        for nested in value_dict.values():
            if isinstance(nested, dict | list | tuple):
                resolved = _select_id_from_value(nested, keys)
                if resolved is not None:
                    return resolved
        return None
    if isinstance(value, list | tuple):
        value_seq = cast("list[Any] | tuple[Any, ...]", value)
        for item in value_seq:
            resolved = _select_id_from_value(item, keys)
            if resolved is not None:
                return resolved
    return None


# MARK: ToolSet


@toolset(prefix="tradier")
class TradierToolSet:
    """A connector for the Tradier API.

    Args:
        access_token: OAuth bearer access token.
        sandbox: Use sandbox endpoint when True (default). Sandbox uses
            paper money. Set ``sandbox=False`` to trade against the live
            brokerage host — real orders, real money.
    """

    metadata = ProviderMetadata(
        name="tradier",
        display_name="Tradier",
        version="0.1.0",
        description="Accounts, balances, positions, orders, and market data (sandbox-first).",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.tradier.com/",
        homepage_url="https://www.tradier.com/",
        tags=("trading", "brokerage"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        sandbox: bool = True,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self.connection = connection
        self._sandbox = sandbox
        base = "https://sandbox.tradier.com" if sandbox else "https://api.tradier.com"
        self._client = HttpClient(
            base_url=base,
            auth=BearerTokenAuth(access_token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @property
    def _mode(self) -> str:
        return "sandbox" if self._sandbox else "live"

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_profile(self) -> dict[str, Any]:
        """Return the authenticated user's profile (name, default accounts).

        Use this once at startup to discover the ``account_id`` values
        the rest of the toolset needs.
        """
        return self._client.get("/v1/user/profile").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_balances(self, account_id: str) -> dict[str, Any]:
        """Return account balances (cash, equity, buying power).

        Use before placing orders to confirm available funds.
        """
        if not account_id:
            raise ValueError("account_id must be a non-empty string")
        return self._client.get(f"/v1/accounts/{account_id}/balances").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_positions(
        self,
        account_id: str,
        *,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List open positions for an account.

        Best first tool for portfolio inspection. Returns compact
        summaries with ``position_ref`` plus ``symbol``, ``quantity``,
        ``cost_basis``, and ``date_acquired``. Set ``raw=True`` for the
        unmodified Tradier response; ``include_ids=True`` to expose the
        provider ``id`` (used internally — not normally needed since
        positions are addressed by symbol).
        """
        if not account_id:
            raise ValueError("account_id must be a non-empty string")
        payload: dict[str, Any] = self._client.get(f"/v1/accounts/{account_id}/positions").json()
        if raw:
            return payload
        positions_node: Any = payload.get("positions")
        items: list[Any] = []
        if isinstance(positions_node, dict):
            raw_items: Any = cast("dict[str, Any]", positions_node).get("position")
            if isinstance(raw_items, list):
                items = cast("list[Any]", raw_items)
            elif isinstance(raw_items, dict):
                items = [raw_items]
        elif isinstance(positions_node, list):
            items = cast("list[Any]", positions_node)
        summaries: list[dict[str, Any]] = []
        for index, position in enumerate(items, start=1):
            if not isinstance(position, dict):
                continue
            position_dict = cast("dict[str, Any]", position)
            summary: dict[str, Any] = {
                "position_ref": f"position_{index}",
                "symbol": position_dict.get("symbol", ""),
                "quantity": position_dict.get("quantity"),
                "cost_basis": position_dict.get("cost_basis"),
                "date_acquired": position_dict.get("date_acquired", ""),
            }
            if include_ids:
                summary["position_id"] = position_dict.get("id", "")
            summaries.append(summary)
        return {
            "positions": summaries,
            "count": len(summaries),
            "account_id": account_id,
            "mode": self._mode,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_orders(
        self,
        account_id: str,
        *,
        include_provider_tags: bool = False,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List orders for an account.

        Best first tool for order triage. Returns compact summaries with
        ``order_ref`` plus ``symbol``, ``side``, ``quantity``,
        ``type``, ``status``, ``price``, ``stop``, ``duration``, and
        ``create_date``.

        ``include_provider_tags=True`` requests Tradier to include order
        tags in the underlying API call. ``include_ids=True`` exposes
        the numeric ``order_id`` used by :meth:`cancel_order`. Set
        ``raw=True`` for the unmodified Tradier response.

        To cancel a returned order, pass the order dict (or its
        ``order_id``) to :meth:`cancel_order`.
        """
        if not account_id:
            raise ValueError("account_id must be a non-empty string")
        payload: dict[str, Any] = self._client.get(
            f"/v1/accounts/{account_id}/orders",
            params={"includeTags": str(include_provider_tags).lower()},
        ).json()
        if raw:
            return payload
        orders_node: Any = payload.get("orders")
        items: list[Any] = []
        if isinstance(orders_node, dict):
            raw_items: Any = cast("dict[str, Any]", orders_node).get("order")
            if isinstance(raw_items, list):
                items = cast("list[Any]", raw_items)
            elif isinstance(raw_items, dict):
                items = [raw_items]
        elif isinstance(orders_node, list):
            items = cast("list[Any]", orders_node)
        summaries: list[dict[str, Any]] = []
        for index, order in enumerate(items, start=1):
            if not isinstance(order, dict):
                continue
            order_dict = cast("dict[str, Any]", order)
            summary: dict[str, Any] = {
                "order_ref": f"order_{index}",
                "symbol": order_dict.get("symbol", ""),
                "side": order_dict.get("side"),
                "quantity": order_dict.get("quantity"),
                "type": order_dict.get("type"),
                "status": order_dict.get("status"),
                "price": order_dict.get("price"),
                "stop": order_dict.get("stop"),
                "duration": order_dict.get("duration"),
                "create_date": order_dict.get("create_date", ""),
            }
            if include_ids:
                summary["order_id"] = order_dict.get("id")
            summaries.append(summary)
        return {
            "orders": summaries,
            "count": len(summaries),
            "account_id": account_id,
            "mode": self._mode,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_order(self, account_id: str, order_id: str | int) -> dict[str, Any]:
        """Return one order by its Tradier numeric ID.

        Use after :meth:`list_orders` (with ``include_ids=True``) to
        inspect a specific order's full Tradier fields.
        """
        if not account_id or not order_id:
            raise ValueError("account_id and order_id must be non-empty")
        return self._client.get(
            f"/v1/accounts/{account_id}/orders/{order_id}",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def place_equity_order(
        self,
        account_id: str,
        *,
        symbol: str,
        side: str,
        quantity: int,
        type: str = "market",
        duration: str = "day",
        price: float | None = None,
        stop: float | None = None,
        preview: bool = False,
    ) -> dict[str, Any]:
        """Place an equity order. Destructive — places real orders when ``sandbox=False``.

        Confirm with the user before calling on the live host. ``side``
        is one of ``"buy"``, ``"buy_to_cover"``, ``"sell"``,
        ``"sell_short"``. ``type`` is ``"market"``, ``"limit"``,
        ``"stop"``, or ``"stop_limit"``. Pass ``preview=True`` to
        validate the order without submitting it. Returns Tradier's
        order ack payload.
        """
        if not account_id or not symbol or not side:
            raise ValueError("account_id, symbol, and side must be non-empty")
        if side not in {"buy", "buy_to_cover", "sell", "sell_short"}:
            raise ValueError("invalid side")
        params: dict[str, Any] = {
            "class": "equity",
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "type": type,
            "duration": duration,
            "preview": str(preview).lower(),
        }
        if price is not None:
            params["price"] = price
        if stop is not None:
            params["stop"] = stop
        # Tradier requires order parameters in an application/x-www-form-urlencoded
        # request body, not on the query string. Encode them to bytes and send via
        # the form body with an explicit Content-Type header.
        body = urllib.parse.urlencode(params, doseq=True).encode("utf-8")
        return self._client.post(
            f"/v1/accounts/{account_id}/orders",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def cancel_order(self, account_id: str, order: Any) -> dict[str, Any]:
        """Cancel an order. Destructive.

        Accepts either a raw Tradier numeric ``order_id`` or an order
        dict returned by :meth:`list_orders` (with ``include_ids=True``)
        or :meth:`get_order`. Confirm with the user before calling.
        """
        if not account_id:
            raise ValueError("account_id must be a non-empty string")
        order_id = _select_id_from_value(order, ("order_id", "id"))
        if not order_id:
            raise ValueError("order must be an order id or order dict with an id")
        return self._client.delete(
            f"/v1/accounts/{account_id}/orders/{order_id}",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_quotes(self, symbols: list[str], *, greeks: bool = False) -> dict[str, Any]:
        """Get latest quotes for one or more symbols.

        Returns Tradier's ``{"quotes": {"quote": [...]}}`` payload. For
        options chains, set ``greeks=True`` to include implied vol /
        delta / gamma / etc.
        """
        if not symbols:
            raise ValueError("symbols must be non-empty")
        return self._client.get(
            "/v1/markets/quotes",
            params={
                "symbols": ",".join(symbols),
                "greeks": str(greeks).lower(),
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_option_chains(
        self,
        *,
        symbol: str,
        expiration: str,
        greeks: bool = False,
    ) -> dict[str, Any]:
        """Get the option chain for ``symbol`` on a single expiration date.

        ``expiration`` is ``YYYY-MM-DD``. Set ``greeks=True`` to include
        IV/delta/gamma/theta/vega.
        """
        if not symbol or not expiration:
            raise ValueError("symbol and expiration must be non-empty")
        return self._client.get(
            "/v1/markets/options/chains",
            params={
                "symbol": symbol,
                "expiration": expiration,
                "greeks": str(greeks).lower(),
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_clock(self) -> dict[str, Any]:
        """Return the market clock (is the US market open right now?).

        Returns ``{"clock": {"date": ..., "state": "open" | "closed",
        "next_change": ...}}``.
        """
        return self._client.get("/v1/markets/clock").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_watchlists(self) -> dict[str, Any]:
        """List watchlists configured on the account.

        Returns Tradier's raw watchlists payload.
        """
        return self._client.get("/v1/watchlists").json()
