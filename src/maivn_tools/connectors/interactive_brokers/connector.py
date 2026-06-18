"""Interactive Brokers Client Portal Web API connector.

The Client Portal API expects a running local gateway and uses session
cookies. This connector takes the base URL of the gateway (typically
``https://localhost:5000``) and lets callers attach their own auth /
session handling via a custom :class:`HttpTransport` if needed.

IBKR has no public sandbox via this API — order placement targets
whichever account is logged into the gateway. Use a paper trading
account when testing.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.base import NoAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_ORDERS_OUTPUT, LIST_POSITIONS_OUTPUT

# MARK: Helpers


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
        mapping = cast(dict[Any, Any], value)
        for key in keys:
            candidate: Any = mapping.get(key)
            resolved = _select_id_from_value(candidate, keys)
            if resolved is not None:
                return resolved
        for nested in mapping.values():
            nested_value: Any = nested
            if isinstance(nested_value, dict | list | tuple):
                resolved = _select_id_from_value(nested_value, keys)
                if resolved is not None:
                    return resolved
        return None
    if isinstance(value, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", value)
        for item in sequence:
            item_value: Any = item
            resolved = _select_id_from_value(item_value, keys)
            if resolved is not None:
                return resolved
    return None


@toolset(prefix="ibkr")
class InteractiveBrokersToolSet:
    """A connector for IBKR Client Portal Web API.

    Args:
        base_url: URL of the running Client Portal Gateway. Defaults to
            ``https://localhost:5000`` (the gateway default). The
            gateway must already be authenticated when calls run — use
            :meth:`authentication_status` to verify.
    """

    metadata = ProviderMetadata(
        name="interactive_brokers",
        display_name="Interactive Brokers",
        version="0.1.0",
        description="Accounts, portfolio, orders, market data via Client Portal Web API.",
        auth_modes=(AuthMode.CUSTOM,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://www.interactivebrokers.com/api/doc.html",
        homepage_url="https://www.interactivebrokers.com/",
        tags=("trading", "brokerage"),
    )

    def __init__(
        self,
        *,
        base_url: str = "https://localhost:5000",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=NoAuth(),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def authentication_status(self) -> dict[str, Any]:
        """Return the gateway's current authentication / session status.

        Use this first — most other calls fail if ``authenticated`` is
        false or ``connected`` is false. Returns IBKR's ``{"authenticated":
        bool, "connected": bool, "competing": bool, "fail": str,
        "MAC": ...}`` payload.
        """
        return self._client.post("/v1/api/iserver/auth/status", json={}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def reauthenticate(self) -> dict[str, Any]:
        """Reauthenticate an existing IBKR Client Portal session.

        Returns the gateway's ack message. Use when
        :meth:`authentication_status` reports stale session.
        """
        return self._client.post("/v1/api/iserver/reauthenticate", json={}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_accounts(self) -> dict[str, Any]:
        """List portfolio accounts available to the logged-in IBKR session.

        Returns IBKR's account list — each entry has ``accountId``
        (the value other tools call ``account_id``), ``accountVan``,
        ``displayName``, and ``type`` (e.g. ``"DEMO"`` for paper).
        """
        return self._client.get("/v1/api/portfolio/accounts").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_account_summary(self, account_id: str) -> dict[str, Any]:
        """Return summary fields for one IBKR account.

        Use after :meth:`list_accounts` to inspect balances and
        liquidation values for a specific account.
        """
        if not account_id:
            raise ValueError("account_id must be a non-empty string")
        return self._client.get(
            f"/v1/api/portfolio/{account_id}/summary",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_POSITIONS_OUTPUT)
    def list_positions(
        self,
        account_id: str,
        *,
        page_id: int = 0,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List positions for an IBKR account (paginated, 30 per page).

        Best first tool for IBKR portfolio inspection. Returns compact
        summaries with ``position_ref`` plus ``symbol``, ``position``
        (signed share count), ``mkt_value``, ``mkt_price``,
        ``avg_cost``, ``unrealized_pnl``, ``asset_class``, ``currency``,
        and ``exchange``.

        The underlying IBKR ``conid`` (the numeric contract ID) is the
        handle used for market data and orders. It is hidden by default
        — set ``include_ids=True`` to expose it. ``raw=True`` returns
        the unmodified IBKR response.
        """
        if not account_id:
            raise ValueError("account_id must be a non-empty string")
        payload: Any = self._client.get(
            f"/v1/api/portfolio/{account_id}/positions/{page_id}",
        ).json()
        if raw:
            return payload
        items: list[Any] = cast("list[Any]", payload) if isinstance(payload, list) else []
        summaries: list[dict[str, Any]] = []
        for index, position in enumerate(items, start=1):
            if not isinstance(position, dict):
                continue
            entry = cast(dict[Any, Any], position)
            summary: dict[str, Any] = {
                "position_ref": f"position_{index}",
                "symbol": entry.get("contractDesc") or entry.get("ticker", ""),
                "position": entry.get("position"),
                "mkt_value": entry.get("mktValue"),
                "mkt_price": entry.get("mktPrice"),
                "avg_cost": entry.get("avgCost"),
                "unrealized_pnl": entry.get("unrealizedPnl"),
                "asset_class": entry.get("assetClass", ""),
                "currency": entry.get("currency", ""),
                "exchange": entry.get("listingExchange", ""),
            }
            if include_ids:
                summary["conid"] = entry.get("conid")
            summaries.append(summary)
        return {
            "positions": summaries,
            "count": len(summaries),
            "page_id": page_id,
            "account_id": account_id,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_contract(
        self,
        *,
        symbol: str,
        name: bool = False,
        sec_type: str | None = None,
    ) -> dict[str, Any]:
        """Search IBKR's security definitions by symbol (or name).

        Returns matching contracts — each entry has ``conid``,
        ``symbol``, ``description``, ``companyHeader``, and supported
        ``secType`` codes. The ``conid`` is the handle required by
        :meth:`market_data_snapshot` and order tools.
        """
        if not symbol:
            raise ValueError("symbol must be a non-empty string")
        body: dict[str, Any] = {"symbol": symbol, "name": name}
        if sec_type is not None:
            body["secType"] = sec_type
        return self._client.post(
            "/v1/api/iserver/secdef/search",
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def market_data_snapshot(
        self,
        *,
        conids: list[int],
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return market-data snapshots for a list of IBKR contract IDs (conids).

        Common ``fields``: ``"31"`` (last price), ``"84"`` (bid),
        ``"86"`` (ask). Returns IBKR's snapshot list. Note: the first
        call for a new conid may return empty; call again to get the
        warmed-up snapshot.
        """
        if not conids:
            raise ValueError("conids must be non-empty")
        params: dict[str, Any] = {"conids": ",".join(str(c) for c in conids)}
        if fields is not None:
            params["fields"] = ",".join(fields)
        return self._client.get(
            "/v1/api/iserver/marketdata/snapshot",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def preview_order(self, *, account_id: str, orders: list[dict[str, Any]]) -> dict[str, Any]:
        """Preview an order ("what-if") without placing it.

        Returns IBKR's projected margin / commission impact. Safer than
        :meth:`place_order` for validating order parameters, but still
        marked destructive because it shares the same input shape and
        agents should treat it as a confirmation step rather than a
        free-form read.
        """
        if not account_id or not orders:
            raise ValueError("account_id and orders must be non-empty")
        return self._client.post(
            f"/v1/api/iserver/account/{account_id}/orders/whatif",
            json={"orders": orders},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def place_order(self, *, account_id: str, orders: list[dict[str, Any]]) -> dict[str, Any]:
        """Place one or more orders. Destructive — submits live orders.

        Confirm with the user before calling. IBKR uses whichever
        account is logged into the gateway; if that account is live
        and funded, these are real orders. Returns the IBKR order ack
        list — note that IBKR sometimes returns a confirmation prompt
        that must be answered via :meth:`place_order` again with the
        reply ID. Run :meth:`preview_order` first when in doubt.
        """
        if not account_id or not orders:
            raise ValueError("account_id and orders must be non-empty")
        return self._client.post(
            f"/v1/api/iserver/account/{account_id}/orders",
            json={"orders": orders},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def cancel_order(self, *, account_id: str, order: Any) -> dict[str, Any]:
        """Cancel an order. Destructive.

        Accepts either a raw IBKR ``order_id`` (numeric or string) or an
        order dict returned by :meth:`list_orders`.
        """
        if not account_id:
            raise ValueError("account_id must be a non-empty string")
        order_id = _select_id_from_value(order, ("order_id", "orderId", "id"))
        if not order_id:
            raise ValueError("order must be an order id or order dict with an id")
        return self._client.delete(
            f"/v1/api/iserver/account/{account_id}/order/{order_id}",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_ORDERS_OUTPUT)
    def list_orders(
        self,
        *,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List live orders across the logged-in IBKR session.

        Best first tool for IBKR order triage. Returns compact summaries
        with ``order_ref`` plus ``symbol`` (``ticker``), ``side``,
        ``quantity``, ``status``, ``order_type``, ``limit_price``,
        ``avg_price``, ``filled_quantity``, ``time_in_force``, and
        ``account_id``.

        The underlying ``orderId`` (handle for :meth:`cancel_order`) is
        hidden by default — set ``include_ids=True`` to expose it.
        ``raw=True`` returns the unmodified IBKR response.
        """
        payload: Any = self._client.get("/v1/api/iserver/account/orders").json()
        if raw:
            return payload
        orders_node: Any = (
            cast(dict[Any, Any], payload).get("orders") if isinstance(payload, dict) else None
        )
        items: list[Any] = cast("list[Any]", orders_node) if isinstance(orders_node, list) else []
        summaries: list[dict[str, Any]] = []
        for index, order in enumerate(items, start=1):
            if not isinstance(order, dict):
                continue
            entry = cast(dict[Any, Any], order)
            summary: dict[str, Any] = {
                "order_ref": f"order_{index}",
                "symbol": entry.get("ticker") or entry.get("symbol", ""),
                "side": entry.get("side"),
                "quantity": entry.get("remainingQuantity") or entry.get("totalSize"),
                "status": entry.get("status"),
                "order_type": entry.get("orderType"),
                "limit_price": entry.get("price"),
                "avg_price": entry.get("avgPrice"),
                "filled_quantity": entry.get("filledQuantity"),
                "time_in_force": entry.get("timeInForce"),
                "account_id": entry.get("acct"),
            }
            if include_ids:
                summary["order_id"] = entry.get("orderId")
            summaries.append(summary)
        return {
            "orders": summaries,
            "count": len(summaries),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def history(
        self,
        *,
        conid: int,
        period: str,
        bar: str,
    ) -> dict[str, Any]:
        """Return historical OHLC bars for an IBKR contract.

        ``period`` is e.g. ``"1d"``, ``"1w"``, ``"1m"``, ``"1y"``.
        ``bar`` is e.g. ``"1min"``, ``"5min"``, ``"1h"``, ``"1d"``.
        Returns IBKR's bar list under ``"data"``.
        """
        return self._client.get(
            "/v1/api/iserver/marketdata/history",
            params={"conid": conid, "period": period, "bar": bar},
        ).json()
