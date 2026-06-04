# pyright: strict
from __future__ import annotations

import urllib.parse

import pytest
from maivn._internal.utils.toolset import (
    get_toolify_options,
    get_toolset_options,
)

from maivn_tools.connectors.alpaca import AlpacaToolSet
from maivn_tools.connectors.binance import BinanceToolSet
from maivn_tools.connectors.coinbase import CoinbaseToolSet
from maivn_tools.connectors.interactive_brokers import InteractiveBrokersToolSet
from maivn_tools.connectors.kraken import KrakenToolSet
from maivn_tools.connectors.polygon import PolygonToolSet
from maivn_tools.connectors.schwab import SchwabToolSet
from maivn_tools.connectors.tradier import TradierToolSet
from maivn_tools.testing import MockTransport, json_response

# MARK: - Alpaca


def _alpaca() -> tuple[AlpacaToolSet, MockTransport]:
    transport = MockTransport()
    return (
        AlpacaToolSet(api_key="k", api_secret="s", paper=True, transport=transport),
        transport,
    )


def test_alpaca() -> None:
    transport = MockTransport()
    connector = AlpacaToolSet(
        api_key="k",
        api_secret="s",
        paper=True,
        transport=transport,
    )
    for _ in range(18):
        transport.enqueue(json_response({}))
    connector.get_account()
    connector.list_positions()
    connector.get_position("AAPL")
    connector.list_activities(
        activity_types=["FILL"],
        date="2026-01-01",
        until="2026-02-01",
        after="2026-01-01",
        direction="desc",
    )
    connector.list_assets(status="active")
    connector.list_watchlists()
    connector.create_watchlist(name="W", symbols=["AAPL"])
    connector.list_orders(status="open", after="x", until="y", symbols=["AAPL"])
    connector.get_order("o1")
    connector.submit_order(symbol="AAPL", qty=1, side="buy", idempotency_key="k1")
    connector.submit_order(symbol="AAPL", notional=100, side="sell")
    connector.cancel_order("o1")
    connector.cancel_all_orders()
    connector.close_position("AAPL", qty=1)
    connector.get_latest_quote("AAPL")
    connector.get_latest_trade("AAPL")
    connector.get_bars("AAPL", timeframe="1Day", start="2026-01-01", end="2026-02-01")
    connector.get_clock()
    assert transport.requests[0].headers["APCA-API-KEY-ID"] == "k"
    assert transport.requests[0].headers["APCA-API-SECRET-KEY"] == "s"
    assert "paper-api.alpaca.markets" in transport.requests[0].url
    with pytest.raises(ValueError):
        AlpacaToolSet(api_key="", api_secret="s")
    with pytest.raises(ValueError):
        connector.get_position("")
    with pytest.raises(ValueError):
        connector.create_watchlist(name="", symbols=[])
    with pytest.raises(ValueError):
        connector.get_order("")
    with pytest.raises(ValueError):
        connector.submit_order(symbol="", side="buy", qty=1)
    with pytest.raises(ValueError):
        connector.submit_order(symbol="AAPL", side="bogus", qty=1)
    with pytest.raises(ValueError):
        connector.submit_order(symbol="AAPL", side="buy")
    with pytest.raises(ValueError):
        connector.cancel_order("")
    with pytest.raises(ValueError):
        connector.close_position("")
    with pytest.raises(ValueError):
        connector.get_latest_quote("")
    with pytest.raises(ValueError):
        connector.get_bars("", timeframe="1Day")


def test_alpaca_calendar() -> None:
    transport = MockTransport()
    connector = AlpacaToolSet(api_key="k", api_secret="s", transport=transport)
    transport.enqueue(json_response({}))
    connector.get_calendar(start="2026-01-01", end="2026-02-01")


def test_alpaca_is_a_toolset() -> None:
    opts = get_toolset_options(AlpacaToolSet)
    assert opts is not None
    assert opts.prefix == "alpaca"


def test_alpaca_list_positions_returns_human_summaries_without_ids() -> None:
    connector, transport = _alpaca()
    transport.enqueue(
        json_response(
            [
                {
                    "asset_id": "uuid-1",
                    "symbol": "AAPL",
                    "qty": "10",
                    "side": "long",
                    "market_value": "1900",
                    "avg_entry_price": "180",
                    "current_price": "190",
                    "unrealized_pl": "100",
                    "unrealized_plpc": "0.055",
                    "asset_class": "us_equity",
                }
            ]
        )
    )
    result = connector.list_positions()
    assert result["count"] == 1
    assert result["mode"] == "paper"
    position = result["positions"][0]
    assert position["position_ref"] == "position_1"
    assert position["symbol"] == "AAPL"
    assert position["qty"] == "10"
    assert position["unrealized_pl"] == "100"
    assert "asset_id" not in position


def test_alpaca_list_positions_include_ids_exposes_asset_id() -> None:
    connector, transport = _alpaca()
    transport.enqueue(json_response([{"asset_id": "uuid-1", "symbol": "AAPL"}]))
    result = connector.list_positions(include_ids=True)
    assert result["positions"][0]["asset_id"] == "uuid-1"


def test_alpaca_list_positions_raw_mode_returns_unmodified_payload() -> None:
    connector, transport = _alpaca()
    raw = [{"asset_id": "uuid-1", "symbol": "AAPL", "extra_field": 1}]
    transport.enqueue(json_response(raw))
    result = connector.list_positions(raw=True)
    assert result["positions"] == raw


def test_alpaca_list_orders_returns_summaries_without_internal_ids() -> None:
    connector, transport = _alpaca()
    transport.enqueue(
        json_response(
            [
                {
                    "id": "order-uuid-1",
                    "client_order_id": "client-1",
                    "symbol": "AAPL",
                    "side": "buy",
                    "qty": "5",
                    "filled_qty": "0",
                    "type": "limit",
                    "status": "new",
                    "limit_price": "150",
                    "stop_price": None,
                    "submitted_at": "2026-05-15T12:00:00Z",
                    "time_in_force": "day",
                }
            ]
        )
    )
    result = connector.list_orders()
    order = result["orders"][0]
    assert order["order_ref"] == "order_1"
    assert order["symbol"] == "AAPL"
    assert order["status"] == "new"
    assert "order_id" not in order
    assert "client_order_id" not in order


def test_alpaca_list_orders_include_ids_returns_internal_ids() -> None:
    connector, transport = _alpaca()
    transport.enqueue(json_response([{"id": "o1", "client_order_id": "c1", "symbol": "AAPL"}]))
    result = connector.list_orders(include_ids=True)
    assert result["orders"][0]["order_id"] == "o1"
    assert result["orders"][0]["client_order_id"] == "c1"


def test_alpaca_list_assets_caps_to_limit_and_hides_id() -> None:
    connector, transport = _alpaca()
    transport.enqueue(
        json_response(
            [{"id": f"uuid-{i}", "symbol": f"SYM{i}", "name": f"Sym {i}"} for i in range(30)]
        )
    )
    result = connector.list_assets(limit=5)
    assert result["count"] == 5
    assert "asset_id" not in result["assets"][0]
    assert result["assets"][0]["asset_ref"] == "asset_1"
    assert result["total_returned_by_provider"] == 30


def test_alpaca_cancel_order_accepts_dict_from_list_orders() -> None:
    connector, transport = _alpaca()
    transport.enqueue(json_response({}))
    connector.cancel_order({"order_id": "abc-123"})
    assert transport.requests[0].url.endswith("/v2/orders/abc-123")


def test_alpaca_cancel_order_accepts_raw_alpaca_dict() -> None:
    connector, transport = _alpaca()
    transport.enqueue(json_response({}))
    connector.cancel_order({"id": "abc-123", "symbol": "AAPL"})
    assert transport.requests[0].url.endswith("/v2/orders/abc-123")


def test_alpaca_cancel_order_rejects_empty_or_idless() -> None:
    connector, _ = _alpaca()
    with pytest.raises(ValueError):
        connector.cancel_order({})


def test_alpaca_close_position_accepts_dict() -> None:
    connector, transport = _alpaca()
    transport.enqueue(json_response({}))
    connector.close_position({"symbol": "MSFT"})
    assert "/v2/positions/MSFT" in transport.requests[0].url


def test_alpaca_submit_order_marked_destructive() -> None:
    connector, _ = _alpaca()
    opts = get_toolify_options(connector.submit_order)
    assert opts is not None and opts.destructive is True


def test_alpaca_cancel_order_marked_destructive() -> None:
    connector, _ = _alpaca()
    opts = get_toolify_options(connector.cancel_order)
    assert opts is not None and opts.destructive is True


def test_alpaca_close_position_marked_destructive() -> None:
    connector, _ = _alpaca()
    opts = get_toolify_options(connector.close_position)
    assert opts is not None and opts.destructive is True


def test_alpaca_get_account_is_not_destructive() -> None:
    connector, _ = _alpaca()
    opts = get_toolify_options(connector.get_account)
    assert opts is not None and opts.destructive is False


# MARK: - Polygon


def _polygon() -> tuple[PolygonToolSet, MockTransport]:
    transport = MockTransport()
    return PolygonToolSet(api_key="pk", transport=transport), transport


def test_polygon() -> None:
    transport = MockTransport()
    connector = PolygonToolSet(api_key="pk", transport=transport)
    for _ in range(10):
        transport.enqueue(json_response({}))
    connector.list_tickers(ticker="AAPL", market="stocks", cursor="c")
    connector.get_ticker_details("AAPL")
    connector.get_aggregates(
        ticker="AAPL",
        multiplier=1,
        timespan="day",
        from_date="2026-01-01",
        to_date="2026-02-01",
    )
    connector.get_last_trade("AAPL")
    connector.get_last_quote("AAPL")
    connector.get_daily_open_close(ticker="AAPL", date="2026-01-15")
    connector.get_previous_close("AAPL")
    connector.list_news(ticker="AAPL", published_utc_gte="2026-01-01")
    connector.get_market_status()
    connector.list_option_contracts(underlying_ticker="AAPL", expiration_date="2026-02-19")
    assert transport.requests[0].params["apiKey"] == "pk"
    with pytest.raises(ValueError):
        PolygonToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.get_ticker_details("")
    with pytest.raises(ValueError):
        connector.get_aggregates(
            ticker="",
            multiplier=1,
            timespan="day",
            from_date="2026-01-01",
            to_date="2026-02-01",
        )
    with pytest.raises(ValueError):
        connector.get_last_trade("")
    with pytest.raises(ValueError):
        connector.get_last_quote("")
    with pytest.raises(ValueError):
        connector.get_daily_open_close(ticker="AAPL", date="")
    with pytest.raises(ValueError):
        connector.get_previous_close("")
    with pytest.raises(ValueError):
        connector.list_option_contracts(underlying_ticker="")


def test_polygon_is_a_toolset() -> None:
    opts = get_toolset_options(PolygonToolSet)
    assert opts is not None
    assert opts.prefix == "polygon"


def test_polygon_list_tickers_returns_summaries() -> None:
    connector, transport = _polygon()
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "ticker": "AAPL",
                        "name": "Apple Inc.",
                        "market": "stocks",
                        "primary_exchange": "XNAS",
                        "locale": "us",
                        "currency_name": "usd",
                        "active": True,
                    }
                ],
                "next_url": "https://polygon/next",
            }
        )
    )
    result = connector.list_tickers(ticker="AAPL")
    assert result["count"] == 1
    assert result["tickers"][0]["ticker_ref"] == "ticker_1"
    assert result["tickers"][0]["name"] == "Apple Inc."
    assert result["next_url"] == "https://polygon/next"


def test_polygon_list_news_returns_summaries() -> None:
    connector, transport = _polygon()
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "title": "Apple beats earnings",
                        "publisher": {"name": "Reuters"},
                        "author": "Jane",
                        "published_utc": "2026-05-15T00:00:00Z",
                        "article_url": "https://reuters/x",
                        "description": "blah",
                        "tickers": ["AAPL"],
                    }
                ]
            }
        )
    )
    result = connector.list_news()
    article = result["articles"][0]
    assert article["article_ref"] == "article_1"
    assert article["publisher"] == "Reuters"
    assert article["tickers"] == ["AAPL"]


def test_polygon_list_option_contracts_returns_summaries() -> None:
    connector, transport = _polygon()
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "ticker": "O:AAPL260219C00200000",
                        "underlying_ticker": "AAPL",
                        "contract_type": "call",
                        "strike_price": 200,
                        "expiration_date": "2026-02-19",
                        "exercise_style": "american",
                        "shares_per_contract": 100,
                    }
                ]
            }
        )
    )
    result = connector.list_option_contracts(underlying_ticker="AAPL")
    assert result["contracts"][0]["contract_ref"] == "contract_1"
    assert result["contracts"][0]["strike_price"] == 200


def test_polygon_list_tickers_raw_returns_payload() -> None:
    connector, transport = _polygon()
    raw = {"results": [{"ticker": "AAPL"}], "next_url": "x"}
    transport.enqueue(json_response(raw))
    assert connector.list_tickers(raw=True) == raw


def test_polygon_limit_bounds_validated() -> None:
    connector, _ = _polygon()
    with pytest.raises(ValueError):
        connector.list_tickers(limit=0)
    with pytest.raises(ValueError):
        connector.list_tickers(limit=2000)
    with pytest.raises(ValueError):
        connector.list_news(limit=0)


# MARK: - Tradier


def _tradier() -> tuple[TradierToolSet, MockTransport]:
    transport = MockTransport()
    return (
        TradierToolSet(access_token="t", sandbox=True, transport=transport),
        transport,
    )


def test_tradier() -> None:
    transport = MockTransport()
    connector = TradierToolSet(access_token="t", sandbox=True, transport=transport)
    for _ in range(11):
        transport.enqueue(json_response({}))
    connector.get_profile()
    connector.get_balances("a1")
    connector.list_positions("a1")
    connector.list_orders("a1", include_provider_tags=True)
    connector.get_order("a1", 1)
    connector.place_equity_order(
        account_id="a1",
        symbol="AAPL",
        side="buy",
        quantity=1,
        type="limit",
        duration="gtc",
        price=100.0,
        stop=99.0,
        preview=True,
    )
    connector.cancel_order("a1", 1)
    connector.get_quotes(symbols=["AAPL", "MSFT"], greeks=True)
    connector.get_option_chains(symbol="AAPL", expiration="2026-02-19", greeks=True)
    connector.get_clock()
    connector.list_watchlists()
    assert "sandbox.tradier.com" in transport.requests[0].url
    with pytest.raises(ValueError):
        TradierToolSet(access_token="")
    with pytest.raises(ValueError):
        connector.get_balances("")
    with pytest.raises(ValueError):
        connector.list_positions("")
    with pytest.raises(ValueError):
        connector.list_orders("")
    with pytest.raises(ValueError):
        connector.get_order("", 1)
    with pytest.raises(ValueError):
        connector.place_equity_order(
            account_id="",
            symbol="x",
            side="buy",
            quantity=1,
        )
    with pytest.raises(ValueError):
        connector.place_equity_order(
            account_id="a1",
            symbol="x",
            side="bogus",
            quantity=1,
        )
    with pytest.raises(ValueError):
        connector.cancel_order("a1", 0)
    with pytest.raises(ValueError):
        connector.get_quotes(symbols=[])
    with pytest.raises(ValueError):
        connector.get_option_chains(symbol="AAPL", expiration="")


def test_tradier_is_a_toolset() -> None:
    opts = get_toolset_options(TradierToolSet)
    assert opts is not None
    assert opts.prefix == "tradier"


def test_tradier_list_orders_returns_summaries_without_ids() -> None:
    connector, transport = _tradier()
    transport.enqueue(
        json_response(
            {
                "orders": {
                    "order": [
                        {
                            "id": 12345,
                            "symbol": "AAPL",
                            "side": "buy",
                            "quantity": 10,
                            "type": "limit",
                            "status": "open",
                            "price": 150.0,
                            "stop": None,
                            "duration": "day",
                            "create_date": "2026-05-15",
                        }
                    ]
                }
            }
        )
    )
    result = connector.list_orders("a1")
    assert result["count"] == 1
    assert result["mode"] == "sandbox"
    order = result["orders"][0]
    assert order["order_ref"] == "order_1"
    assert order["symbol"] == "AAPL"
    assert "order_id" not in order


def test_tradier_list_orders_include_ids_returns_order_id() -> None:
    connector, transport = _tradier()
    transport.enqueue(json_response({"orders": {"order": {"id": 12345, "symbol": "AAPL"}}}))
    result = connector.list_orders("a1", include_ids=True)
    assert result["orders"][0]["order_id"] == 12345


def test_tradier_list_positions_returns_summaries() -> None:
    connector, transport = _tradier()
    transport.enqueue(
        json_response(
            {
                "positions": {
                    "position": [
                        {
                            "symbol": "AAPL",
                            "quantity": 10,
                            "cost_basis": 1500,
                            "date_acquired": "2026-01-01",
                        }
                    ]
                }
            }
        )
    )
    result = connector.list_positions("a1")
    assert result["positions"][0]["position_ref"] == "position_1"
    assert result["positions"][0]["symbol"] == "AAPL"


def test_tradier_cancel_order_accepts_dict() -> None:
    connector, transport = _tradier()
    transport.enqueue(json_response({}))
    connector.cancel_order("a1", {"order_id": 999})
    assert "/orders/999" in transport.requests[0].url


def test_tradier_cancel_order_accepts_raw_dict_with_id() -> None:
    connector, transport = _tradier()
    transport.enqueue(json_response({}))
    connector.cancel_order("a1", {"id": 777, "symbol": "AAPL"})
    assert "/orders/777" in transport.requests[0].url


def test_tradier_place_equity_order_marked_destructive() -> None:
    connector, _ = _tradier()
    opts = get_toolify_options(connector.place_equity_order)
    assert opts is not None and opts.destructive is True


def test_tradier_cancel_order_marked_destructive() -> None:
    connector, _ = _tradier()
    opts = get_toolify_options(connector.cancel_order)
    assert opts is not None and opts.destructive is True


# MARK: - IBKR


def _ibkr() -> tuple[InteractiveBrokersToolSet, MockTransport]:
    transport = MockTransport()
    return (
        InteractiveBrokersToolSet(
            base_url="https://localhost:5000",
            transport=transport,
        ),
        transport,
    )


def test_ibkr() -> None:
    transport = MockTransport()
    connector = InteractiveBrokersToolSet(
        base_url="https://localhost:5000",
        transport=transport,
    )
    for _ in range(11):
        transport.enqueue(json_response({}))
    connector.authentication_status()
    connector.reauthenticate()
    connector.list_accounts()
    connector.get_account_summary("DU123")
    connector.list_positions("DU123", page_id=0)
    connector.search_contract(symbol="AAPL", name=True, sec_type="STK")
    connector.market_data_snapshot(conids=[1, 2], fields=["31", "84"])
    connector.preview_order(account_id="DU123", orders=[{"conid": 1}])
    connector.place_order(account_id="DU123", orders=[{"conid": 1}])
    connector.cancel_order(account_id="DU123", order=1)
    connector.list_orders()
    with pytest.raises(ValueError):
        connector.get_account_summary("")
    with pytest.raises(ValueError):
        connector.list_positions("")
    with pytest.raises(ValueError):
        connector.search_contract(symbol="")
    with pytest.raises(ValueError):
        connector.market_data_snapshot(conids=[])
    with pytest.raises(ValueError):
        connector.preview_order(account_id="", orders=[{"x": 1}])
    with pytest.raises(ValueError):
        connector.place_order(account_id="DU123", orders=[])
    with pytest.raises(ValueError):
        connector.cancel_order(account_id="", order=1)


def test_ibkr_history() -> None:
    transport = MockTransport()
    connector = InteractiveBrokersToolSet(transport=transport)
    transport.enqueue(json_response({}))
    connector.history(conid=1, period="1d", bar="1min")


def test_ibkr_is_a_toolset() -> None:
    opts = get_toolset_options(InteractiveBrokersToolSet)
    assert opts is not None
    assert opts.prefix == "ibkr"


def test_ibkr_list_positions_returns_summaries() -> None:
    connector, transport = _ibkr()
    transport.enqueue(
        json_response(
            [
                {
                    "conid": 265598,
                    "contractDesc": "AAPL",
                    "position": 10,
                    "mktValue": 1900,
                    "mktPrice": 190,
                    "avgCost": 180,
                    "unrealizedPnl": 100,
                    "assetClass": "STK",
                    "currency": "USD",
                    "listingExchange": "NASDAQ",
                }
            ]
        )
    )
    result = connector.list_positions("DU123")
    pos = result["positions"][0]
    assert pos["position_ref"] == "position_1"
    assert pos["symbol"] == "AAPL"
    assert "conid" not in pos


def test_ibkr_list_positions_include_ids_exposes_conid() -> None:
    connector, transport = _ibkr()
    transport.enqueue(json_response([{"conid": 265598, "contractDesc": "AAPL"}]))
    result = connector.list_positions("DU123", include_ids=True)
    assert result["positions"][0]["conid"] == 265598


def test_ibkr_list_orders_returns_summaries() -> None:
    connector, transport = _ibkr()
    transport.enqueue(
        json_response(
            {
                "orders": [
                    {
                        "orderId": 999,
                        "ticker": "AAPL",
                        "side": "BUY",
                        "remainingQuantity": 10,
                        "status": "Submitted",
                        "orderType": "LIMIT",
                        "price": 150,
                        "avgPrice": None,
                        "filledQuantity": 0,
                        "timeInForce": "DAY",
                        "acct": "DU123",
                    }
                ]
            }
        )
    )
    result = connector.list_orders()
    assert result["orders"][0]["order_ref"] == "order_1"
    assert result["orders"][0]["symbol"] == "AAPL"
    assert "order_id" not in result["orders"][0]


def test_ibkr_cancel_order_accepts_dict() -> None:
    connector, transport = _ibkr()
    transport.enqueue(json_response({}))
    connector.cancel_order(account_id="DU123", order={"order_id": 42})
    assert "/order/42" in transport.requests[0].url


def test_ibkr_place_order_marked_destructive() -> None:
    connector, _ = _ibkr()
    opts = get_toolify_options(connector.place_order)
    assert opts is not None and opts.destructive is True


def test_ibkr_cancel_order_marked_destructive() -> None:
    connector, _ = _ibkr()
    opts = get_toolify_options(connector.cancel_order)
    assert opts is not None and opts.destructive is True


# MARK: - Coinbase


def _coinbase() -> tuple[CoinbaseToolSet, MockTransport]:
    transport = MockTransport()
    return CoinbaseToolSet(transport=transport), transport


def test_coinbase() -> None:
    transport = MockTransport()
    connector = CoinbaseToolSet(transport=transport)
    for _ in range(11):
        transport.enqueue(json_response({}))
    connector.list_accounts(cursor="c")
    connector.get_account("uuid-1")
    connector.list_products(product_type="SPOT")
    connector.get_product("BTC-USD")
    connector.get_product_candles(
        product_id="BTC-USD",
        start="0",
        end="1000",
        granularity="ONE_HOUR",
    )
    connector.get_market_trades(product_id="BTC-USD")
    connector.list_orders(product_id="BTC-USD", order_status=["FILLED"], cursor="c")
    connector.list_fills(order_id="o1", product_id="BTC-USD", cursor="c")
    connector.create_order({"client_order_id": "x"})
    connector.cancel_orders(["o1", "o2"])
    connector.list_portfolios(portfolio_type="DEFAULT")
    with pytest.raises(ValueError):
        connector.get_account("")
    with pytest.raises(ValueError):
        connector.get_product("")
    with pytest.raises(ValueError):
        connector.get_product_candles(
            product_id="",
            start="0",
            end="1",
            granularity="x",
        )
    with pytest.raises(ValueError):
        connector.get_market_trades(product_id="")
    with pytest.raises(ValueError):
        connector.create_order({})
    with pytest.raises(ValueError):
        connector.cancel_orders([])


def test_coinbase_is_a_toolset() -> None:
    opts = get_toolset_options(CoinbaseToolSet)
    assert opts is not None
    assert opts.prefix == "coinbase"


def test_coinbase_list_accounts_returns_summaries() -> None:
    connector, transport = _coinbase()
    transport.enqueue(
        json_response(
            {
                "accounts": [
                    {
                        "uuid": "uuid-1",
                        "name": "BTC Wallet",
                        "currency": "BTC",
                        "available_balance": {"value": "0.5", "currency": "BTC"},
                        "hold": {"value": "0", "currency": "BTC"},
                        "type": "ACCOUNT_TYPE_CRYPTO",
                        "active": True,
                        "default": True,
                    }
                ],
                "has_next": False,
                "cursor": "",
            }
        )
    )
    result = connector.list_accounts()
    assert result["accounts"][0]["account_ref"] == "account_1"
    assert result["accounts"][0]["name"] == "BTC Wallet"
    assert "account_uuid" not in result["accounts"][0]


def test_coinbase_list_accounts_include_ids_exposes_uuid() -> None:
    connector, transport = _coinbase()
    transport.enqueue(json_response({"accounts": [{"uuid": "uuid-1", "name": "x"}]}))
    result = connector.list_accounts(include_ids=True)
    assert result["accounts"][0]["account_uuid"] == "uuid-1"


def test_coinbase_list_orders_returns_summaries() -> None:
    connector, transport = _coinbase()
    transport.enqueue(
        json_response(
            {
                "orders": [
                    {
                        "order_id": "o-1",
                        "product_id": "BTC-USD",
                        "side": "BUY",
                        "order_type": "LIMIT",
                        "status": "OPEN",
                        "filled_size": "0",
                        "average_filled_price": "0",
                        "time_in_force": "GOOD_UNTIL_CANCELLED",
                        "created_time": "2026-05-15T12:00:00Z",
                    }
                ]
            }
        )
    )
    result = connector.list_orders()
    assert result["orders"][0]["order_ref"] == "order_1"
    assert result["orders"][0]["product_id"] == "BTC-USD"
    assert "order_id" not in result["orders"][0]


def test_coinbase_list_products_returns_summaries() -> None:
    connector, transport = _coinbase()
    transport.enqueue(
        json_response(
            {
                "products": [
                    {
                        "product_id": "BTC-USD",
                        "base_currency_id": "BTC",
                        "quote_currency_id": "USD",
                        "status": "online",
                        "price": "50000",
                        "price_percentage_change_24h": "1.5",
                        "volume_24h": "1000",
                        "trading_disabled": False,
                    }
                ]
            }
        )
    )
    result = connector.list_products()
    assert result["products"][0]["product_ref"] == "product_1"
    assert result["products"][0]["product_id"] == "BTC-USD"


def test_coinbase_cancel_orders_accepts_orders_list_dicts() -> None:
    connector, transport = _coinbase()
    transport.enqueue(json_response({"results": []}))
    connector.cancel_orders([{"order_id": "o1"}, {"order_id": "o2"}])
    payload = transport.requests[0].json_body
    assert payload["order_ids"] == ["o1", "o2"]


def test_coinbase_cancel_orders_accepts_list_orders_payload() -> None:
    connector, transport = _coinbase()
    transport.enqueue(json_response({"results": []}))
    list_orders_payload = {
        "orders": [
            {"order_ref": "order_1", "order_id": "o1", "product_id": "BTC-USD"},
            {"order_ref": "order_2", "order_id": "o2", "product_id": "ETH-USD"},
        ],
    }
    connector.cancel_orders(list_orders_payload)
    payload = transport.requests[0].json_body
    assert "o1" in payload["order_ids"]
    assert "o2" in payload["order_ids"]


def test_coinbase_create_order_marked_destructive() -> None:
    connector, _ = _coinbase()
    opts = get_toolify_options(connector.create_order)
    assert opts is not None and opts.destructive is True


def test_coinbase_cancel_orders_marked_destructive() -> None:
    connector, _ = _coinbase()
    opts = get_toolify_options(connector.cancel_orders)
    assert opts is not None and opts.destructive is True


# MARK: - Kraken


def _kraken() -> tuple[KrakenToolSet, MockTransport]:
    transport = MockTransport()
    return KrakenToolSet(transport=transport), transport


def test_kraken() -> None:
    transport = MockTransport()
    connector = KrakenToolSet(transport=transport)
    for _ in range(13):
        transport.enqueue(json_response({}))
    connector.server_time()
    connector.system_status()
    connector.get_assets()
    connector.get_asset_pairs(pair="XBTUSD")
    connector.get_ticker("XBTUSD")
    connector.get_ohlc(pair="XBTUSD", interval=60, since=0)
    connector.get_order_book(pair="XBTUSD")
    connector.get_balance()
    connector.open_orders()
    connector.closed_orders(start=1, end=2, ofs=0)
    connector.add_order(
        pair="XBTUSD",
        type="buy",
        ordertype="limit",
        volume="0.1",
        price="50000",
        leverage="2",
        validate=True,
    )
    connector.cancel_order(txid="OXM2EY-2RXZ")
    connector.list_ledgers()
    with pytest.raises(ValueError):
        connector.get_ticker("")
    with pytest.raises(ValueError):
        connector.get_ohlc(pair="", interval=60)
    with pytest.raises(ValueError):
        connector.get_order_book(pair="")
    with pytest.raises(ValueError):
        connector.add_order(pair="", type="buy", ordertype="market", volume="0.1")
    with pytest.raises(ValueError):
        connector.cancel_order(txid="")


def test_kraken_trade_history() -> None:
    transport = MockTransport()
    connector = KrakenToolSet(transport=transport)
    transport.enqueue(json_response({}))
    connector.trade_history()


def test_kraken_is_a_toolset() -> None:
    opts = get_toolset_options(KrakenToolSet)
    assert opts is not None
    assert opts.prefix == "kraken"


def test_kraken_open_orders_returns_summaries() -> None:
    connector, transport = _kraken()
    transport.enqueue(
        json_response(
            {
                "result": {
                    "open": {
                        "OXM2EY-2RXZ": {
                            "status": "open",
                            "vol": "0.1",
                            "vol_exec": "0",
                            "opentm": 1234567890,
                            "descr": {
                                "pair": "XBTUSD",
                                "type": "buy",
                                "ordertype": "limit",
                                "price": "50000",
                            },
                        }
                    }
                }
            }
        )
    )
    result = connector.open_orders()
    assert result["count"] == 1
    order = result["orders"][0]
    assert order["order_ref"] == "order_1"
    assert order["pair"] == "XBTUSD"
    assert order["side"] == "buy"
    assert "txid" not in order


def test_kraken_open_orders_include_ids_exposes_txid() -> None:
    connector, transport = _kraken()
    transport.enqueue(
        json_response(
            {
                "result": {
                    "open": {
                        "OXM2EY-2RXZ": {
                            "status": "open",
                            "descr": {"pair": "XBTUSD", "type": "buy", "ordertype": "market"},
                        }
                    }
                }
            }
        )
    )
    result = connector.open_orders(include_ids=True)
    assert result["orders"][0]["txid"] == "OXM2EY-2RXZ"


def test_kraken_cancel_order_accepts_dict() -> None:
    connector, transport = _kraken()
    transport.enqueue(json_response({}))
    connector.cancel_order(txid={"txid": "OXM2EY-2RXZ"})
    body = transport.requests[0].data
    assert body is not None
    form = urllib.parse.parse_qs(body.decode("utf-8"))
    assert form["txid"] == ["OXM2EY-2RXZ"]


def test_kraken_add_order_marked_destructive() -> None:
    connector, _ = _kraken()
    opts = get_toolify_options(connector.add_order)
    assert opts is not None and opts.destructive is True


def test_kraken_cancel_order_marked_destructive() -> None:
    connector, _ = _kraken()
    opts = get_toolify_options(connector.cancel_order)
    assert opts is not None and opts.destructive is True


# MARK: - Binance


def _binance() -> tuple[BinanceToolSet, MockTransport]:
    transport = MockTransport()
    return BinanceToolSet(api_key="apikey", transport=transport), transport


def test_binance() -> None:
    transport = MockTransport()
    connector = BinanceToolSet(api_key="apikey", transport=transport)
    for _ in range(12):
        transport.enqueue(json_response({}))
    connector.server_time()
    connector.exchange_info(symbol="BTCUSDT")
    connector.ticker_price(symbol="BTCUSDT")
    connector.ticker_24h(symbol="BTCUSDT")
    connector.get_klines(
        symbol="BTCUSDT",
        interval="1h",
        start_time=1,
        end_time=2,
        limit=10,
    )
    connector.order_book(symbol="BTCUSDT", limit=10)
    connector.recent_trades(symbol="BTCUSDT", limit=10)
    connector.account(timestamp=123, signature="sig")
    connector.list_open_orders(timestamp=123, signature="sig", symbol="BTCUSDT")
    connector.new_order(
        symbol="BTCUSDT",
        side="BUY",
        type="LIMIT",
        quantity="0.001",
        quote_order_qty=None,
        price="50000",
        time_in_force="GTC",
        timestamp=1,
        signature="sig",
        test=True,
    )
    connector.new_order(
        symbol="BTCUSDT",
        side="SELL",
        type="MARKET",
        quantity="0.001",
        timestamp=1,
        signature="sig",
    )
    connector.cancel_order(
        symbol="BTCUSDT",
        order_id=1,
        timestamp=1,
        signature="sig",
    )
    assert transport.requests[0].headers["X-MBX-APIKEY"] == "apikey"
    with pytest.raises(ValueError):
        BinanceToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.get_klines(symbol="", interval="1h")
    with pytest.raises(ValueError):
        connector.order_book(symbol="")
    with pytest.raises(ValueError):
        connector.recent_trades(symbol="")
    with pytest.raises(ValueError):
        connector.new_order(
            symbol="",
            side="BUY",
            type="MARKET",
            quantity="1",
            timestamp=1,
            signature="sig",
        )
    with pytest.raises(ValueError):
        connector.new_order(
            symbol="X",
            side="bogus",
            type="MARKET",
            quantity="1",
            timestamp=1,
            signature="sig",
        )
    with pytest.raises(ValueError):
        connector.cancel_order(symbol="", timestamp=1, signature="sig")
    with pytest.raises(ValueError):
        connector.cancel_order(
            symbol="X",
            timestamp=1,
            signature="sig",
        )


def test_binance_is_a_toolset() -> None:
    opts = get_toolset_options(BinanceToolSet)
    assert opts is not None
    assert opts.prefix == "binance"


def test_binance_list_open_orders_returns_summaries() -> None:
    connector, transport = _binance()
    transport.enqueue(
        json_response(
            [
                {
                    "symbol": "BTCUSDT",
                    "orderId": 999,
                    "clientOrderId": "cli-1",
                    "side": "BUY",
                    "type": "LIMIT",
                    "status": "NEW",
                    "origQty": "0.001",
                    "executedQty": "0",
                    "price": "50000",
                    "stopPrice": "0",
                    "timeInForce": "GTC",
                    "time": 1234567890,
                }
            ]
        )
    )
    result = connector.list_open_orders(timestamp=1, signature="sig")
    assert result["orders"][0]["order_ref"] == "order_1"
    assert result["orders"][0]["symbol"] == "BTCUSDT"
    assert "order_id" not in result["orders"][0]


def test_binance_list_open_orders_include_ids_exposes_order_id() -> None:
    connector, transport = _binance()
    transport.enqueue(
        json_response([{"symbol": "BTCUSDT", "orderId": 999, "clientOrderId": "c-1"}])
    )
    result = connector.list_open_orders(timestamp=1, signature="sig", include_ids=True)
    assert result["orders"][0]["order_id"] == 999
    assert result["orders"][0]["client_order_id"] == "c-1"


def test_binance_cancel_order_accepts_dict_with_numeric_id() -> None:
    connector, transport = _binance()
    transport.enqueue(json_response({}))
    connector.cancel_order(
        symbol="BTCUSDT",
        timestamp=1,
        signature="sig",
        order={"order_id": 42},
    )
    assert transport.requests[0].params["orderId"] == 42


def test_binance_cancel_order_accepts_dict_with_client_id_fallback() -> None:
    connector, transport = _binance()
    transport.enqueue(json_response({}))
    connector.cancel_order(
        symbol="BTCUSDT",
        timestamp=1,
        signature="sig",
        order={"client_order_id": "client-abc"},
    )
    assert transport.requests[0].params["origClientOrderId"] == "client-abc"


def test_binance_new_order_marked_destructive() -> None:
    connector, _ = _binance()
    opts = get_toolify_options(connector.new_order)
    assert opts is not None and opts.destructive is True


def test_binance_cancel_order_marked_destructive() -> None:
    connector, _ = _binance()
    opts = get_toolify_options(connector.cancel_order)
    assert opts is not None and opts.destructive is True


# MARK: - Schwab


def _schwab() -> tuple[SchwabToolSet, MockTransport]:
    transport = MockTransport()
    return SchwabToolSet(access_token="t", transport=transport), transport


def test_schwab() -> None:
    transport = MockTransport()
    connector = SchwabToolSet(access_token="t", transport=transport)
    for _ in range(9):
        transport.enqueue(json_response({}))
    connector.list_accounts(fields=["positions"])
    connector.get_account("ah", fields=["positions"])
    connector.list_orders(
        "ah",
        from_entered_time="2026-01-01T00:00:00.000Z",
        to_entered_time="2026-02-01T00:00:00.000Z",
        status="FILLED",
    )
    connector.place_order("ah", {"orderType": "MARKET"})
    connector.cancel_order("ah", 1)
    connector.get_quotes(["AAPL"], fields=["quote"])
    connector.get_option_chains(symbol="AAPL", contract_type="CALL", strike_count=5)
    connector.get_price_history(
        symbol="AAPL",
        period_type="day",
        period=10,
        frequency_type="minute",
        frequency=5,
        start_date=1,
        end_date=2,
    )
    connector.market_hours(["equity"], date="2026-01-01")
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    with pytest.raises(ValueError):
        SchwabToolSet(access_token="")
    with pytest.raises(ValueError):
        connector.get_account("")
    with pytest.raises(ValueError):
        connector.list_orders(
            "",
            from_entered_time="x",
            to_entered_time="y",
        )
    with pytest.raises(ValueError):
        connector.place_order("", {"x": 1})
    with pytest.raises(ValueError):
        connector.cancel_order("", 1)
    with pytest.raises(ValueError):
        connector.get_quotes([])
    with pytest.raises(ValueError):
        connector.get_option_chains(symbol="", contract_type="CALL")
    with pytest.raises(ValueError):
        connector.get_option_chains(symbol="AAPL", contract_type="BOGUS")
    with pytest.raises(ValueError):
        connector.get_price_history(symbol="")
    with pytest.raises(ValueError):
        connector.market_hours([])


def test_schwab_is_a_toolset() -> None:
    opts = get_toolset_options(SchwabToolSet)
    assert opts is not None
    assert opts.prefix == "schwab"


def test_schwab_list_accounts_returns_summaries() -> None:
    connector, transport = _schwab()
    transport.enqueue(
        json_response(
            [
                {
                    "securitiesAccount": {
                        "accountNumber": "123",
                        "hashValue": "abc-hash",
                        "type": "MARGIN",
                        "roundTrips": 0,
                        "isDayTrader": False,
                        "currentBalances": {"cashBalance": 1000},
                    }
                }
            ]
        )
    )
    result = connector.list_accounts()
    assert result["accounts"][0]["account_ref"] == "account_1"
    assert result["accounts"][0]["account_number"] == "123"
    assert "account_hash" not in result["accounts"][0]


def test_schwab_list_accounts_include_ids_exposes_account_hash() -> None:
    connector, transport = _schwab()
    transport.enqueue(
        json_response(
            [
                {
                    "securitiesAccount": {
                        "accountNumber": "123",
                        "hashValue": "abc-hash",
                    }
                }
            ]
        )
    )
    result = connector.list_accounts(include_ids=True)
    assert result["accounts"][0]["account_hash"] == "abc-hash"


def test_schwab_list_orders_returns_summaries() -> None:
    connector, transport = _schwab()
    transport.enqueue(
        json_response(
            [
                {
                    "orderId": 1234,
                    "quantity": 10,
                    "filledQuantity": 0,
                    "orderType": "LIMIT",
                    "status": "WORKING",
                    "price": 150,
                    "duration": "DAY",
                    "enteredTime": "2026-05-15T12:00:00Z",
                    "orderLegCollection": [
                        {
                            "instruction": "BUY",
                            "instrument": {"symbol": "AAPL"},
                        }
                    ],
                }
            ]
        )
    )
    result = connector.list_orders(
        "ah",
        from_entered_time="2026-01-01T00:00:00.000Z",
        to_entered_time="2026-02-01T00:00:00.000Z",
    )
    order = result["orders"][0]
    assert order["order_ref"] == "order_1"
    assert order["symbol"] == "AAPL"
    assert order["side"] == "BUY"
    assert "order_id" not in order


def test_schwab_list_orders_include_ids_returns_order_id() -> None:
    connector, transport = _schwab()
    transport.enqueue(json_response([{"orderId": 1234, "orderLegCollection": []}]))
    result = connector.list_orders(
        "ah",
        from_entered_time="x",
        to_entered_time="y",
        include_ids=True,
    )
    assert result["orders"][0]["order_id"] == 1234


def test_schwab_cancel_order_accepts_dict() -> None:
    connector, transport = _schwab()
    transport.enqueue(json_response({}))
    connector.cancel_order("ah", {"order_id": 1234})
    assert "/orders/1234" in transport.requests[0].url


def test_schwab_place_order_marked_destructive() -> None:
    connector, _ = _schwab()
    opts = get_toolify_options(connector.place_order)
    assert opts is not None and opts.destructive is True


def test_schwab_cancel_order_marked_destructive() -> None:
    connector, _ = _schwab()
    opts = get_toolify_options(connector.cancel_order)
    assert opts is not None and opts.destructive is True
