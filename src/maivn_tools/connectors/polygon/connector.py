"""Polygon.io market-data API connector.

Read-only market data: stocks, options, forex, crypto. Authentication is
an API key (query param ``apiKey``). No destructive operations — this
connector cannot place trades.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Helpers


def _as_dict(value: object) -> dict[str, Any]:
    """Return ``value`` as a ``dict`` mapping, or an empty dict otherwise."""
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)
    return {}


def _results(payload: object) -> list[dict[str, Any]]:
    """Extract the Polygon ``results`` list of dict items from a payload."""
    container = _as_dict(payload)
    raw_items: object = container.get("results")
    if not isinstance(raw_items, list):
        return []
    items: list[object] = cast("list[object]", raw_items)
    return [cast("dict[str, Any]", item) for item in items if isinstance(item, dict)]


def _next_url(payload: object) -> Any:
    """Return the Polygon ``next_url`` pagination token, if present."""
    return _as_dict(payload).get("next_url")


# MARK: ToolSet


@toolset(prefix="polygon")
class PolygonToolSet:
    """A connector for Polygon.io market data.

    Read-only — Polygon serves quotes, trades, bars, and news. There
    are no order-placement tools on this toolset.
    """

    metadata = ProviderMetadata(
        name="polygon",
        display_name="Polygon.io",
        version="0.1.0",
        description="Stocks/options/forex/crypto market data: aggregates, tickers, news.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.SEARCH}),
        documentation_url="https://polygon.io/docs",
        homepage_url="https://polygon.io/",
        tags=("market-data", "finance"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.polygon.io",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, query_param="apiKey"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_tickers(
        self,
        *,
        ticker: str | None = None,
        market: str | None = None,
        active: bool = True,
        limit: int = 25,
        cursor: str | None = None,
        raw: bool = False,
    ) -> dict[str, Any]:
        """Search/list reference tickers across all asset classes.

        Best first tool for symbol discovery. Returns compact summaries
        with ``ticker_ref`` plus ``ticker``, ``name``, ``market``
        (stocks/options/fx/crypto), ``primary_exchange``, ``locale``,
        ``currency``, and ``active``.

        Default ``limit`` is 25 — Polygon's max is 1000. ``cursor`` is
        the ``next_url`` token from a previous page. Set ``raw=True``
        for the unmodified Polygon response.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        params: dict[str, Any] = {"active": str(active).lower(), "limit": limit}
        if ticker is not None:
            params["ticker"] = ticker
        if market is not None:
            params["market"] = market
        if cursor is not None:
            params["cursor"] = cursor
        payload: Any = self._client.get("/v3/reference/tickers", params=params).json()
        if raw:
            return payload
        summaries: list[dict[str, Any]] = []
        for index, item in enumerate(_results(payload), start=1):
            summaries.append(
                {
                    "ticker_ref": f"ticker_{index}",
                    "ticker": item.get("ticker", ""),
                    "name": item.get("name", ""),
                    "market": item.get("market", ""),
                    "primary_exchange": item.get("primary_exchange", ""),
                    "locale": item.get("locale", ""),
                    "currency": item.get("currency_name", ""),
                    "active": item.get("active"),
                }
            )
        return {
            "tickers": summaries,
            "count": len(summaries),
            "next_url": _next_url(payload),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_ticker_details(self, ticker: str) -> dict[str, Any]:
        """Return detailed reference info for a single ticker.

        Use after :meth:`list_tickers` when you need full company /
        instrument details: description, market cap, SIC code, list
        date, branding.
        """
        if not ticker:
            raise ValueError("ticker must be a non-empty string")
        return self._client.get(f"/v3/reference/tickers/{ticker}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_aggregates(
        self,
        *,
        ticker: str,
        multiplier: int,
        timespan: str,
        from_date: str,
        to_date: str,
        adjusted: bool = True,
        sort: str = "asc",
        limit: int = 5000,
    ) -> dict[str, Any]:
        """Return historical OHLCV aggregate bars for a ticker.

        ``multiplier`` + ``timespan`` form the bar size (e.g.
        ``multiplier=5, timespan="minute"`` for 5-minute bars; valid
        ``timespan``: minute/hour/day/week/month/quarter/year).
        ``from_date``/``to_date`` are ``YYYY-MM-DD``. Returns Polygon's
        ``{"results": [...], "resultsCount": N}`` payload.
        """
        if not ticker or not timespan or not from_date or not to_date:
            raise ValueError("ticker, timespan, from_date, and to_date are required")
        if limit < 1 or limit > 50_000:
            raise ValueError("limit must be between 1 and 50000")
        return self._client.get(
            f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_date}/{to_date}",
            params={
                "adjusted": str(adjusted).lower(),
                "sort": sort,
                "limit": limit,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_last_trade(self, ticker: str) -> dict[str, Any]:
        """Return the most recent trade for a ticker.

        Returns ``{"results": {"p": price, "s": size, "t": timestamp,
        "x": exchange}}``.
        """
        if not ticker:
            raise ValueError("ticker must be a non-empty string")
        return self._client.get(f"/v2/last/trade/{ticker}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_last_quote(self, ticker: str) -> dict[str, Any]:
        """Return the most recent NBBO quote for a ticker.

        Returns ``{"results": {"P": ask, "S": ask size, "p": bid, "s":
        bid size, "t": timestamp}}``.
        """
        if not ticker:
            raise ValueError("ticker must be a non-empty string")
        return self._client.get(f"/v2/last/nbbo/{ticker}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_daily_open_close(
        self,
        *,
        ticker: str,
        date: str,
        adjusted: bool = True,
    ) -> dict[str, Any]:
        """Daily OHLC for a ticker on a single ``YYYY-MM-DD`` date.

        Returns ``{"open": ..., "high": ..., "low": ..., "close": ...,
        "volume": ..., "afterHours": ..., "preMarket": ...}``.
        """
        if not ticker or not date:
            raise ValueError("ticker and date must be non-empty")
        return self._client.get(
            f"/v1/open-close/{ticker}/{date}",
            params={"adjusted": str(adjusted).lower()},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_previous_close(
        self,
        ticker: str,
        *,
        adjusted: bool = True,
    ) -> dict[str, Any]:
        """Previous trading day's OHLC for a ticker.

        Returns Polygon's ``{"results": [{"c": close, "h": high, "l":
        low, "o": open, "v": volume, "vw": vwap}]}``.
        """
        if not ticker:
            raise ValueError("ticker must be a non-empty string")
        return self._client.get(
            f"/v2/aggs/ticker/{ticker}/prev",
            params={"adjusted": str(adjusted).lower()},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_news(
        self,
        *,
        ticker: str | None = None,
        published_utc_gte: str | None = None,
        order: str = "desc",
        limit: int = 10,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List recent news articles, optionally filtered by ticker.

        Best first tool for catalyst/news triage. Returns compact
        summaries with ``article_ref``, ``title``, ``publisher``,
        ``author``, ``published_utc``, ``article_url``, ``description``,
        and ``tickers``.

        Default ``limit`` is 10 (Polygon max 1000). Set ``raw=True``
        for the unmodified response.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        params: dict[str, Any] = {"limit": limit, "order": order}
        if ticker is not None:
            params["ticker"] = ticker
        if published_utc_gte is not None:
            params["published_utc.gte"] = published_utc_gte
        payload: Any = self._client.get(
            "/v2/reference/news",
            params=params,
        ).json()
        if raw:
            return payload
        summaries: list[dict[str, Any]] = []
        for index, item in enumerate(_results(payload), start=1):
            publisher = _as_dict(item.get("publisher") or {})
            summaries.append(
                {
                    "article_ref": f"article_{index}",
                    "title": item.get("title", ""),
                    "publisher": publisher.get("name", ""),
                    "author": item.get("author", ""),
                    "published_utc": item.get("published_utc", ""),
                    "article_url": item.get("article_url", ""),
                    "description": item.get("description", ""),
                    "tickers": item.get("tickers", []),
                }
            )
        return {
            "articles": summaries,
            "count": len(summaries),
            "next_url": _next_url(payload),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_market_status(self) -> dict[str, Any]:
        """Return current market status (is the US market open right now?).

        Returns ``{"market": ..., "serverTime": ..., "exchanges":
        {...}, "currencies": {...}}``.
        """
        return self._client.get("/v1/marketstatus/now").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_option_contracts(
        self,
        *,
        underlying_ticker: str,
        expiration_date: str | None = None,
        contract_type: str | None = None,
        limit: int = 25,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List option contracts for an underlying ticker.

        Returns compact summaries with ``contract_ref`` plus ``ticker``
        (the OCC option symbol), ``contract_type`` (call/put),
        ``strike_price``, ``expiration_date``, ``exercise_style``, and
        ``shares_per_contract``.

        Filter with ``expiration_date="YYYY-MM-DD"`` and/or
        ``contract_type="call" or "put"``. Set ``raw=True`` for the
        unmodified Polygon response.
        """
        if not underlying_ticker:
            raise ValueError("underlying_ticker must be a non-empty string")
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        params: dict[str, Any] = {
            "underlying_ticker": underlying_ticker,
            "limit": limit,
        }
        if expiration_date is not None:
            params["expiration_date"] = expiration_date
        if contract_type is not None:
            params["contract_type"] = contract_type
        payload: Any = self._client.get(
            "/v3/reference/options/contracts",
            params=params,
        ).json()
        if raw:
            return payload
        summaries: list[dict[str, Any]] = []
        for index, item in enumerate(_results(payload), start=1):
            summaries.append(
                {
                    "contract_ref": f"contract_{index}",
                    "ticker": item.get("ticker", ""),
                    "underlying_ticker": item.get("underlying_ticker", ""),
                    "contract_type": item.get("contract_type", ""),
                    "strike_price": item.get("strike_price"),
                    "expiration_date": item.get("expiration_date", ""),
                    "exercise_style": item.get("exercise_style", ""),
                    "shares_per_contract": item.get("shares_per_contract"),
                }
            )
        return {
            "contracts": summaries,
            "count": len(summaries),
            "next_url": _next_url(payload),
        }
