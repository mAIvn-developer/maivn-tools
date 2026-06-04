"""Charles Schwab Developer API connector.

Schwab does not provide a separate sandbox endpoint — order tools place
real orders against the linked Schwab account and are marked
destructive. Confirm with the user before calling :meth:`place_order`
or :meth:`cancel_order`.
"""

# pyright: strict

from __future__ import annotations

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


# MARK: ToolSet


@toolset(prefix="schwab")
class SchwabToolSet:
    """A connector for the Schwab Trader and Market Data APIs."""

    metadata = ProviderMetadata(
        name="schwab",
        display_name="Charles Schwab",
        version="0.1.0",
        description="Accounts, positions, orders, market data, option chains.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.schwab.com/products",
        homepage_url="https://www.schwab.com/",
        tags=("trading", "brokerage"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        base_url: str = "https://api.schwabapi.com",
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
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_accounts(
        self,
        *,
        fields: list[str] | None = None,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List Schwab accounts linked to the authenticated user.

        Best first tool for Schwab account discovery. Returns compact
        summaries with ``account_ref`` plus ``account_number``,
        ``type``, ``round_trips``, ``is_day_trader``, and
        ``balances`` (current balance summary).

        Schwab uses an opaque ``account_hash`` to address an account in
        other API calls. It is hidden by default — set
        ``include_ids=True`` to expose it. ``raw=True`` returns the
        unmodified response. ``fields`` (e.g. ``["positions"]``)
        expands account details.
        """
        params: dict[str, Any] = {}
        if fields is not None:
            params["fields"] = ",".join(fields)
        payload: Any = self._client.get(
            "/trader/v1/accounts",
            params=params or None,
        ).json()
        if raw:
            return payload
        items: list[Any] = cast("list[Any]", payload) if isinstance(payload, list) else []
        summaries: list[dict[str, Any]] = []
        for index, account in enumerate(items, start=1):
            if not isinstance(account, dict):
                continue
            account_dict = cast(dict[str, Any], account)
            securities_account: Any = account_dict.get("securitiesAccount")
            acct: dict[str, Any]
            if isinstance(securities_account, dict):
                acct = cast(dict[str, Any], securities_account)
            else:
                acct = account_dict
            summary: dict[str, Any] = {
                "account_ref": f"account_{index}",
                "account_number": acct.get("accountNumber", ""),
                "type": acct.get("type", ""),
                "round_trips": acct.get("roundTrips"),
                "is_day_trader": acct.get("isDayTrader"),
                "balances": acct.get("currentBalances"),
            }
            if include_ids:
                summary["account_hash"] = acct.get("hashValue") or acct.get("accountHash", "")
            summaries.append(summary)
        return {
            "accounts": summaries,
            "count": len(summaries),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_account(
        self,
        account_hash: str,
        *,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return one account by its Schwab ``account_hash``.

        Use after :meth:`list_accounts` (with ``include_ids=True``) when
        you need every field for a specific account.
        """
        if not account_hash:
            raise ValueError("account_hash must be a non-empty string")
        params: dict[str, Any] = {}
        if fields is not None:
            params["fields"] = ",".join(fields)
        return self._client.get(
            f"/trader/v1/accounts/{account_hash}",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_orders(
        self,
        account_hash: str,
        *,
        from_entered_time: str,
        to_entered_time: str,
        status: str | None = None,
        max_results: int = 25,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List orders for one Schwab account within a time window.

        Best first tool for Schwab order triage. Returns compact
        summaries with ``order_ref`` plus ``symbol`` (best-effort from
        the first leg), ``side`` (``instruction``), ``quantity``,
        ``filled_quantity``, ``order_type``, ``status``, ``price``,
        ``duration``, and ``entered_time``.

        ``from_entered_time`` and ``to_entered_time`` are ISO-8601
        timestamps (e.g. ``"2026-01-01T00:00:00.000Z"``). The Schwab
        ``order_id`` is hidden by default — set ``include_ids=True`` to
        expose it for :meth:`cancel_order`. Default ``max_results`` is
        25 (Schwab max 3000). ``raw=True`` returns the unmodified
        response.
        """
        if not account_hash or not from_entered_time or not to_entered_time:
            raise ValueError("account_hash + from/to times must be non-empty")
        if max_results < 1 or max_results > 3000:
            raise ValueError("max_results must be between 1 and 3000")
        params: dict[str, Any] = {
            "fromEnteredTime": from_entered_time,
            "toEnteredTime": to_entered_time,
            "maxResults": max_results,
        }
        if status is not None:
            params["status"] = status
        payload: Any = self._client.get(
            f"/trader/v1/accounts/{account_hash}/orders",
            params=params,
        ).json()
        if raw:
            return payload
        items: list[Any] = cast("list[Any]", payload) if isinstance(payload, list) else []
        summaries: list[dict[str, Any]] = []
        for index, order in enumerate(items, start=1):
            if not isinstance(order, dict):
                continue
            order_dict = cast(dict[str, Any], order)
            legs: Any = order_dict.get("orderLegCollection") or []
            symbol: Any = ""
            side: Any = None
            if isinstance(legs, list) and legs:
                first_leg: Any = cast("list[Any]", legs)[0]
                if isinstance(first_leg, dict):
                    first_leg_dict = cast(dict[str, Any], first_leg)
                    instrument: Any = first_leg_dict.get("instrument") or {}
                    if isinstance(instrument, dict):
                        symbol = cast(dict[str, Any], instrument).get("symbol", "")
                    side = first_leg_dict.get("instruction")
            summary: dict[str, Any] = {
                "order_ref": f"order_{index}",
                "symbol": symbol,
                "side": side,
                "quantity": order_dict.get("quantity"),
                "filled_quantity": order_dict.get("filledQuantity"),
                "order_type": order_dict.get("orderType"),
                "status": order_dict.get("status"),
                "price": order_dict.get("price"),
                "duration": order_dict.get("duration"),
                "entered_time": order_dict.get("enteredTime", ""),
            }
            if include_ids:
                summary["order_id"] = order_dict.get("orderId")
            summaries.append(summary)
        return {
            "orders": summaries,
            "count": len(summaries),
            "account_hash_used": True,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def place_order(self, account_hash: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Place an order on a Schwab account. Destructive — places real orders.

        Schwab has no sandbox host. Confirm with the user before
        calling. ``payload`` is Schwab's order body (``orderType``,
        ``session``, ``duration``, ``orderStrategyType``,
        ``orderLegCollection``). Returns ``{"status": <http-status>,
        "headers": {...}}`` — Schwab returns the new ``orderId`` in the
        ``Location`` response header.
        """
        if not account_hash or not payload:
            raise ValueError("account_hash and payload must be non-empty")
        response = self._client.post(
            f"/trader/v1/accounts/{account_hash}/orders",
            json=payload,
        )
        return {"status": response.status, "headers": dict(response.headers)}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def cancel_order(self, account_hash: str, order: Any) -> dict[str, Any]:
        """Cancel an order on a Schwab account. Destructive.

        Accepts either a raw Schwab ``order_id`` (numeric or string) or
        an order dict returned by :meth:`list_orders` (with
        ``include_ids=True``). Returns ``{"id": <id>, "cancelled": True,
        "status": <http-status>}``.
        """
        if not account_hash:
            raise ValueError("account_hash must be a non-empty string")
        order_id = _select_id_from_value(order, ("order_id", "orderId", "id"))
        if not order_id:
            raise ValueError("order must be an order id or order dict with an id")
        response = self._client.delete(
            f"/trader/v1/accounts/{account_hash}/orders/{order_id}",
        )
        return {"id": order_id, "cancelled": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_quotes(
        self,
        symbols: list[str],
        *,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get quotes for one or more symbols.

        Returns Schwab's ``{"<symbol>": {"quote": {...}, "reference":
        {...}, ...}}`` payload. ``fields`` lets you expand reference
        and fundamental fields.
        """
        if not symbols:
            raise ValueError("symbols must be non-empty")
        params: dict[str, Any] = {"symbols": ",".join(symbols)}
        if fields is not None:
            params["fields"] = ",".join(fields)
        return self._client.get("/marketdata/v1/quotes", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_option_chains(
        self,
        *,
        symbol: str,
        contract_type: str = "ALL",
        strike_count: int | None = None,
        include_quotes: bool = True,
    ) -> dict[str, Any]:
        """Return the option chain for an underlying symbol.

        ``contract_type`` is ``"CALL"``, ``"PUT"``, or ``"ALL"``.
        ``strike_count`` limits how many strikes around the money to
        return. Returns Schwab's full chain payload.
        """
        if not symbol:
            raise ValueError("symbol must be a non-empty string")
        if contract_type not in {"CALL", "PUT", "ALL"}:
            raise ValueError("contract_type must be CALL/PUT/ALL")
        params: dict[str, Any] = {
            "symbol": symbol,
            "contractType": contract_type,
            "includeQuotes": str(include_quotes).lower(),
        }
        if strike_count is not None:
            params["strikeCount"] = strike_count
        return self._client.get(
            "/marketdata/v1/chains",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_price_history(
        self,
        *,
        symbol: str,
        period_type: str | None = None,
        period: int | None = None,
        frequency_type: str | None = None,
        frequency: int | None = None,
        start_date: int | None = None,
        end_date: int | None = None,
    ) -> dict[str, Any]:
        """Return historical OHLCV candles for an equity symbol.

        ``period_type`` is one of ``"day"``, ``"month"``, ``"year"``,
        ``"ytd"``. ``frequency_type`` is ``"minute"``, ``"daily"``,
        ``"weekly"``, ``"monthly"``. ``start_date``/``end_date`` are
        millisecond unix timestamps. Returns Schwab's ``{"candles":
        [...], "symbol": ..., "empty": ...}``.
        """
        if not symbol:
            raise ValueError("symbol must be a non-empty string")
        params: dict[str, Any] = {"symbol": symbol}
        if period_type is not None:
            params["periodType"] = period_type
        if period is not None:
            params["period"] = period
        if frequency_type is not None:
            params["frequencyType"] = frequency_type
        if frequency is not None:
            params["frequency"] = frequency
        if start_date is not None:
            params["startDate"] = start_date
        if end_date is not None:
            params["endDate"] = end_date
        return self._client.get(
            "/marketdata/v1/pricehistory",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def market_hours(
        self,
        markets: list[str],
        *,
        date: str | None = None,
    ) -> dict[str, Any]:
        """Return market hours for one or more markets on a date (``YYYY-MM-DD``).

        ``markets`` entries: ``"equity"``, ``"option"``, ``"bond"``,
        ``"future"``, ``"forex"``. Returns a per-market hours payload.
        """
        if not markets:
            raise ValueError("markets must be non-empty")
        params: dict[str, Any] = {"markets": ",".join(markets)}
        if date is not None:
            params["date"] = date
        return self._client.get(
            "/marketdata/v1/markets",
            params=params,
        ).json()
