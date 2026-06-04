# Trading & market data

Brokerage, exchange, and market-data providers. **All order-placement
and cancellation tools are explicitly marked destructive -- they move
real money on a live account.** Defaults favor paper/sandbox endpoints
where the provider supports them (Alpaca `paper=True`, Tradier
`sandbox=True`, Binance `base_url` switchable to testnet). Live trading
requires explicit opt-in (`paper=False`, `sandbox=False`, live base URL).
Coinbase, Kraken, Interactive Brokers, and Schwab have no separate
provider sandbox host -- every order tool on those connectors targets the
authenticated live account and must be guarded with explicit user
confirmation.

> When integrating these into an agent, prefer
> `add_toolset(..., exclude_tags=["destructive"])` or
> `include_tags=["read"]` for analyst-style agents.

All connectors follow the same agent-ready pattern: list/search tools
return compact summaries with a stable ordinal ref (`position_ref`,
`order_ref`, `account_ref`, `asset_ref`, `product_ref`, `ticker_ref`,
`contract_ref`, etc.) plus user-facing fields (symbol / pair, side,
quantity, price, status, timestamps). Raw provider order IDs / txids /
UUIDs are hidden unless `include_ids=True` is passed; pass `raw=True`
(where supported) for the unmodified provider response. Write tools that
take an ID accept either the raw ID string or the dict returned by the
matching `list_*` / `get_*` tool.

## AlpacaToolSet

```python
from maivn_tools import AlpacaToolSet

connector = AlpacaToolSet(
    api_key=secrets["ALPACA_KEY"],
    api_secret=secrets["ALPACA_SECRET"],
    paper=True,  # default; set False for live (real money)
)
```

Tools: `get_account`,
`list_positions(include_ids, raw)`, `get_position(symbol)`,
`list_activities(...)`,
`list_assets(status, asset_class, include_ids, raw)`,
`list_watchlists`, `create_watchlist(...)`,
`list_orders(status, include_ids, raw)`, `get_order(order_id)`,
`submit_order(symbol, qty, notional, side, type, ...)` (destructive),
`cancel_order(order)` (destructive),
`cancel_all_orders` (destructive),
`close_position(position, qty)` (destructive),
`get_latest_quote(symbol, feed)`,
`get_latest_trade(symbol, feed)`,
`get_bars(symbol, timeframe, start, end, limit, feed)`,
`get_clock`, `get_calendar(start, end)`.

### Agent-ready behavior

- `paper=True` is the default -- `submit_order`, `cancel_order`,
  `cancel_all_orders`, `close_position` route to
  `https://paper-api.alpaca.markets`. Set `paper=False` only after
  explicit user confirmation; list tools echo the active mode
  (`"paper"` / `"live"`) in a `mode` field on the response.
- `list_positions`, `list_assets`, `list_orders` return compact
  summaries with stable refs (`position_ref`, `asset_ref`,
  `order_ref`) plus user-facing fields (`symbol`, `qty`, `side`,
  `market_value`, `unrealized_pl`, order `status`, `filled_qty`,
  `filled_avg_price`).
- Raw Alpaca UUIDs hidden by default; pass `include_ids=True` to opt
  in. Pass `raw=True` for the unmodified provider list.
- Default `limit` for `get_bars` is **100** (max 10000).
- `cancel_order` accepts a raw order ID string or an order dict from
  `list_orders(include_ids=True)`. `close_position` accepts either a
  symbol string (`"AAPL"`) or a position dict from `list_positions`.
- Destructive tools: `submit_order`, `cancel_order`,
  `cancel_all_orders`, `close_position`. `cancel_all_orders` cancels
  every pending order on the account -- always confirm.

Example:

```python
orders = connector.list_orders(status="open")
# {"orders": [{"order_ref": "order_1", "symbol": "AAPL", "side": "buy", ...}], "count": 5}
connector.cancel_order(orders["orders"][0])  # accepts the dict if include_ids=True was used
```

## PolygonToolSet

Market data only (no order placement).

```python
from maivn_tools import PolygonToolSet

connector = PolygonToolSet(api_key=secrets["POLYGON_KEY"])
```

Tools:
`list_tickers(ticker, market, active, limit, cursor, raw)`,
`get_ticker_details(ticker)`,
`get_aggregates(ticker, multiplier, timespan, ...)`,
`get_last_trade(ticker)`, `get_last_quote(ticker)`,
`get_daily_open_close(ticker, date)`, `get_previous_close(ticker)`,
`list_news(ticker, limit, raw, ...)`, `get_market_status`,
`list_option_contracts(underlying_ticker, limit, raw, ...)`.

### Agent-ready behavior

- `list_tickers`, `list_news`, `list_option_contracts` return compact
  summaries with stable refs (`ticker_ref`, `article_ref`,
  `contract_ref`) plus user-facing fields (`ticker`, `name`, `market`,
  article `title` / `author` / `published_utc`, contract `expiration_date`
  / `strike_price` / `contract_type`).
- No `include_ids` flag -- Polygon identifiers (ticker symbols, option
  contract symbols) are already user-facing and always included.
- Pass `raw=True` for the unmodified Polygon response. Pagination
  cursors (`next_url`) are preserved.
- Default `limit` is **25** (Polygon's max is 1000).
- No `destructive=True` tools -- Polygon is read-only market data.

## TradierToolSet

```python
from maivn_tools import TradierToolSet

connector = TradierToolSet(
    access_token=secrets["TRADIER_TOKEN"],
    sandbox=True,  # default; set False for live (real money)
)
```

Tools: `get_profile`, `get_balances(account_id)`,
`list_positions(account_id, include_ids, raw)`,
`list_orders(account_id, include_ids, raw)`,
`get_order(account_id, order_id)`,
`place_equity_order(account_id, symbol, side, quantity, type, ..., preview)` (destructive),
`cancel_order(account_id, order)` (destructive),
`get_quotes(symbols, greeks)`,
`get_option_chains(symbol, expiration, greeks)`, `get_clock`,
`list_watchlists`.

### Agent-ready behavior

- `sandbox=True` is the default -- order tools route to
  `https://sandbox.tradier.com`. Set `sandbox=False` only after
  explicit user confirmation. `place_equity_order` also accepts a
  per-call `preview=True` flag that validates the order without
  submitting it (recommended for testing intent on the live host).
- `list_positions`, `list_orders` return compact summaries with stable
  refs (`position_ref`, `order_ref`) plus user-facing fields
  (`symbol`, `quantity`, `cost_basis`, order `side`, `status`,
  `quantity`, `price`).
- Raw Tradier numeric IDs hidden by default; pass `include_ids=True` to
  opt in for `cancel_order` / `get_order`. Pass `raw=True` for the
  unmodified payload.
- `cancel_order` accepts a raw numeric order ID, a string ID, or an
  order dict from `list_orders(include_ids=True)`.
- Destructive tools: `place_equity_order`, `cancel_order`.

## InteractiveBrokersToolSet

Talks to a locally running Client Portal gateway
(`https://localhost:5000` by default).

```python
from maivn_tools import InteractiveBrokersToolSet

connector = InteractiveBrokersToolSet()  # gateway must already be authenticated
```

Tools: `authentication_status`, `reauthenticate`, `list_accounts`,
`get_account_summary(account_id)`,
`list_positions(account_id, page_id, include_ids, raw)`,
`search_contract(symbol, name, sec_type)`,
`market_data_snapshot(conids, fields)`,
`preview_order(account_id, orders)` (destructive),
`place_order(account_id, orders)` (destructive),
`cancel_order(account_id, order)` (destructive),
`list_orders(include_ids, raw)`,
`history(conid, period, bar)`.

### Agent-ready behavior

- IBKR has no public sandbox via the Client Portal Web API -- order
  tools target whichever account is logged into the local gateway. Use
  a paper-trading account when testing; the connector reports the
  account `type` (e.g. `"DEMO"`) via `list_accounts`.
- `list_positions`, `list_orders` return compact summaries with stable
  refs (`position_ref`, `order_ref`) plus user-facing fields
  (`symbol` / `ticker`, `position`, `mkt_price`, `mkt_value`, `avg_cost`,
  order `side`, `status`, `quantity`, `order_type`).
- Raw IBKR `orderId` and contract `conid` hidden by default; pass
  `include_ids=True` to opt in. Pass `raw=True` for the unmodified
  Client Portal response.
- `cancel_order` accepts a raw `order_id` (numeric or string) or the
  order dict from `list_orders(include_ids=True)`.
- Destructive tools: `preview_order`, `place_order`, `cancel_order`.
  `preview_order` is marked destructive because it shares the same
  input shape as `place_order` -- agents should treat it as a
  confirmation step rather than a free-form read.

## CoinbaseToolSet (Advanced Trade)

Coinbase Advanced uses CDP API key + JWT signing; pass a custom
`AuthStrategy`.

```python
from maivn_tools import CoinbaseToolSet

connector = CoinbaseToolSet(auth=my_cdp_jwt_signer)
```

Tools: `list_accounts(limit, cursor, include_ids, raw)`,
`get_account(account_uuid)`,
`list_products(product_type, limit, raw)`,
`get_product(product_id)`,
`get_product_candles(product_id, start, end, granularity)`,
`get_market_trades(product_id, limit)`,
`list_orders(product_id, order_status, cursor, limit, include_ids, raw)`,
`list_fills(order_id, product_id, cursor, limit)`,
`create_order(payload)` (destructive),
`cancel_orders(orders)` (destructive),
`list_portfolios(portfolio_type)`.

### Agent-ready behavior

- Coinbase Advanced Trade has no separate sandbox host -- orders go to
  the live account. Confirm with the user before calling `create_order`
  or `cancel_orders`.
- `list_accounts`, `list_products`, `list_orders` return compact
  summaries with stable refs (`account_ref`, `product_ref`,
  `order_ref`) plus user-facing fields (`name`, `currency`,
  `available_balance`, `product_id` like `"BTC-USD"`, `base_currency`,
  `quote_currency`, `price`, order `side`, `status`, `filled_size`,
  `average_filled_price`).
- Raw Coinbase `account_uuid` / `order_id` / `client_order_id` hidden
  by default; pass `include_ids=True` to opt in. Pass `raw=True` for
  the unmodified Coinbase response.
- Default `limit` is **25** (Coinbase max 250 / 1000 depending on
  endpoint). Pagination via `cursor` with `has_next` returned.
- `cancel_orders` accepts a raw `order_id` string, a list of strings,
  or order dicts (single or list) from
  `list_orders(include_ids=True)` -- it walks any nested structure to
  collect IDs.
- Destructive tools: `create_order`, `cancel_orders`.

## KrakenToolSet

Public + private endpoints. Private endpoints expect API-key signing
provided through a custom `AuthStrategy`.

Tools: `server_time`, `system_status`, `get_assets`, `get_asset_pairs`,
`get_ticker`, `get_ohlc`, `get_order_book`, `get_balance`,
`open_orders(include_ids, raw)`,
`closed_orders(start, end, ofs)`,
`add_order(pair, type, ordertype, volume, ..., validate)` (destructive),
`cancel_order(txid)` (destructive), `list_ledgers`, `trade_history`.

### Agent-ready behavior

- Kraken has no separate sandbox host -- orders go to the live account.
  Confirm with the user before calling `add_order` or `cancel_order`.
  `add_order` accepts a per-call `validate=True` flag that runs the
  order as a dry-run without submitting it (recommended for testing).
- `open_orders` returns compact summaries with `order_ref` plus
  user-facing fields (`pair`, `side`, `ordertype`, `status`, `volume`,
  `volume_executed`, `price`, `opentm`).
- The Kraken `txid` (handle for `cancel_order`) is hidden by default;
  pass `include_ids=True` to opt in. Pass `raw=True` for the
  unmodified Kraken response.
- `cancel_order` accepts a raw `txid` string or an order dict from
  `open_orders(include_ids=True)`.
- Destructive tools: `add_order`, `cancel_order`.

## BinanceToolSet (Spot)

Public endpoints work with just an API key in the header. Signed
endpoints expect the caller to provide `timestamp` and `signature`
(HMAC-SHA256 over the query string). Set `base_url` to
`https://testnet.binance.vision` for the testnet sandbox.

Tools: `server_time`, `exchange_info`, `ticker_price`, `ticker_24h`,
`get_klines`, `order_book`, `recent_trades`,
`account(timestamp, signature)`,
`list_open_orders(timestamp, signature, symbol, include_ids, raw)`,
`new_order(symbol, side, type, ..., timestamp, signature, test)` (destructive),
`cancel_order(symbol, timestamp, signature, order, order_id, orig_client_order_id)` (destructive).

### Agent-ready behavior

- The connector defaults to `https://api.binance.com` (live). Pass
  `base_url="https://testnet.binance.vision"` for the testnet
  sandbox. `new_order` additionally accepts `test=True` to validate the
  order against `/api/v3/order/test` without submitting it.
- `list_open_orders` returns compact summaries with `order_ref` plus
  user-facing fields (`symbol`, `side`, `type`, `status`, `orig_qty`,
  `executed_qty`, `price`, `stop_price`, `time_in_force`, `time`).
- The Binance `order_id` and `client_order_id` are hidden by default;
  pass `include_ids=True` to opt in. Pass `raw=True` for the
  unmodified Binance response.
- `cancel_order` accepts either explicit `order_id` /
  `orig_client_order_id` arguments, or an `order` dict from
  `list_open_orders(include_ids=True)` (it pulls whichever identifier
  is available). `symbol` is always required by Binance.
- Destructive tools: `new_order`, `cancel_order`.

## SchwabToolSet

Charles Schwab Developer API (Trader + Market Data).

```python
from maivn_tools import SchwabToolSet

connector = SchwabToolSet(access_token=secrets["SCHWAB_TOKEN"])
```

Tools: `list_accounts(fields, include_ids, raw)`,
`get_account(account_hash, fields)`,
`list_orders(account_hash, from_entered_time, to_entered_time, status, max_results, include_ids, raw)`,
`place_order(account_hash, payload)` (destructive),
`cancel_order(account_hash, order)` (destructive),
`get_quotes(symbols, fields)`,
`get_option_chains(symbol, ...)`, `get_price_history(symbol, ...)`,
`market_hours(markets, date)`.

### Agent-ready behavior

- Schwab does not provide a separate sandbox endpoint -- every order
  tool places real orders on the linked account. Confirm with the
  user before calling `place_order` or `cancel_order`.
- `list_accounts`, `list_orders` return compact summaries with stable
  refs (`account_ref`, `order_ref`) plus user-facing fields
  (`account_number`, `type`, `current_balance`, order `symbol`,
  `side`, `quantity`, `filled_quantity`, `order_type`, `status`,
  `price`, `duration`, `entered_time`).
- The Schwab `account_hash` (handle other tools need) and `order_id`
  are hidden by default; pass `include_ids=True` to opt in. Pass
  `raw=True` for the unmodified Schwab response.
- Default `max_results` for `list_orders` is **25** (Schwab max 3000).
- `cancel_order` accepts a raw `order_id` (numeric or string) or an
  order dict from `list_orders(include_ids=True)`.
- Destructive tools: `place_order`, `cancel_order`.
