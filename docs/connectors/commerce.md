# E-commerce

Shopping carts, marketplaces, and order management. Each toolset gives
an agent a uniform surface over products, orders, customers, and
inventory for one storefront or marketplace platform.

All commerce connectors follow the same agent-ready pattern:
`list_products`, `list_orders`, `list_customers`, `list_items`, and
`search_items` return compact summaries with stable ordinal refs
(`product_ref`, `order_ref`, `customer_ref`, `item_ref`) plus
user-facing fields (`title` / `name`, `sku` / `handle`, `status`,
`total_price` / `price`, `customer_name`, `email`). Raw provider IDs
are hidden unless `include_ids=True` is passed; pass `include_raw=True`
(Shopify / WooCommerce / BigCommerce / Magento / Amazon / eBay /
Walmart) to receive the unmodified provider payload. Default `limit` is
**25** across the connectors. Write tools that take an ID accept either
the raw ID or the dict returned by the corresponding list/get tool.

> Tip: register with `add_toolset(..., exclude_tags=["destructive"])`
> to drop irreversible tools (delete_product, cancel_order, retire_item).

## ShopifyToolSet

```python
from maivn_tools import ShopifyToolSet

connector = ShopifyToolSet(
    shop="acme",  # -> acme.myshopify.com
    access_token=secrets["SHOPIFY_ADMIN_TOKEN"],
)
```

Tools: `get_shop`,
`list_products(limit, page_info, status, include_ids, include_raw)`,
`get_product(product_id)`, `create_product(product)`,
`update_product(product_id, product)`,
`delete_product(product_id)` (destructive),
`list_orders(status, limit, financial_status, fulfillment_status, page_info, include_ids, include_raw)`,
`get_order(order_id)`, `create_order(order)`,
`cancel_order(order_id, reason, refund, restock)` (destructive),
`list_customers(limit, page_info, include_ids, include_raw)`,
`create_customer(customer)`, `search_customers(query, ...)`,
`list_inventory_levels(...)`, `set_inventory_level(...)`,
`create_fulfillment(order_id, fulfillment)`.

### Agent-ready behavior

- `list_products`, `list_orders`, `list_customers` return compact
  summaries with stable refs (`product_ref`, `order_ref`,
  `customer_ref`) plus user-facing fields (`title`, `vendor`, `sku`,
  `price`, `status`, `order_number`, `customer_name`, `total_price`,
  `currency`, `financial_status`, `fulfillment_status`).
- Raw Shopify numeric IDs hidden by default; pass `include_ids=True` to
  opt in (needed by `update_product`, `delete_product`, `cancel_order`,
  `get_order`). Pass `include_raw=True` for the unmodified payload.
- Default `limit` is **25** (max 250). Pagination via `page_info`
  (cursor from Shopify's `Link` response header).
- `update_product`, `delete_product`, `cancel_order` accept either a
  raw ID or a dict returned by `list_*` (with `include_ids=True`) /
  `get_*`.
- Destructive tools: `delete_product`, `cancel_order`.

Example:

```python
orders = connector.list_orders(status="open", financial_status="paid")
# {"orders": [{"order_ref": "order_1", "order_number": "#1042", "customer_name": "Alice", "total_price": "129.99", "currency": "USD", ...}], "count": 25}
```

## WooCommerceToolSet

```python
from maivn_tools import WooCommerceToolSet

connector = WooCommerceToolSet(
    site_url="https://shop.example.com",
    consumer_key=secrets["WOO_CK"],
    consumer_secret=secrets["WOO_CS"],
)
```

Tools: `list_products(per_page, page, search, status, include_ids, include_raw)`,
`get_product(product_id)`, `create_product(product)`,
`update_product(product_id, product)`,
`delete_product(product_id, force)` (destructive),
`list_orders(per_page, page, status, customer, include_ids, include_raw)`,
`create_order(order)`, `update_order(order_id, order)`,
`list_customers(per_page, page, search, include_ids, include_raw)`,
`create_coupon(coupon)`, `list_reports(...)`.

### Agent-ready behavior

- `list_products`, `list_orders`, `list_customers` return compact
  summaries with stable refs (`product_ref`, `order_ref`,
  `customer_ref`) plus user-facing fields (`name`, `sku`,
  `regular_price`, `status`, `number`, `total`, `customer_name`,
  `email`).
- Raw WooCommerce IDs hidden by default; pass `include_ids=True` for
  follow-up `update_*` / `delete_product` calls. Pass `include_raw=True`
  for the unmodified payload.
- Default `per_page` is **25**. Pagination via `page`.
- `update_product`, `delete_product`, `update_order` accept a raw ID
  or a dict from `list_*(include_ids=True)`. WooCommerce treats
  cancellation as `update_order(order_id, {"status": "cancelled"})` --
  also destructive in effect.
- Destructive tools: `delete_product`.

## BigCommerceToolSet

```python
from maivn_tools import BigCommerceToolSet

connector = BigCommerceToolSet(
    store_hash="abc",
    access_token=secrets["BC_TOKEN"],
)
```

Tools:
`list_products(limit, page, include_ids, include_raw)`,
`create_product(product)`, `update_product(product_id, product)`,
`delete_product(product_id)` (destructive),
`list_orders(limit, page, status_id, include_ids, include_raw)`,
`get_order(order_id)`,
`list_customers(limit, page, include_ids, include_raw)`,
`create_customers(customers)` (bulk), `list_carts(...)`.

### Agent-ready behavior

- `list_products`, `list_orders`, `list_customers` return compact
  summaries with stable refs (`product_ref`, `order_ref`,
  `customer_ref`) plus user-facing fields (`name`, `sku`, `price`,
  `is_visible`, order status / totals, customer name / email).
- Raw IDs hidden by default; pass `include_ids=True` to opt in. Pass
  `include_raw=True` for the unmodified payload.
- Default `limit` is **25** (BigCommerce caps at 250 per page on v3).
- `update_product` and `delete_product` accept a raw ID or a dict from
  `list_products(include_ids=True)`.
- Destructive tools: `delete_product`. The connector wraps the
  legacy v2 orders endpoint where there is no order-cancel tool; treat
  any order mutation as destructive in effect.

## MagentoToolSet

```python
from maivn_tools import MagentoToolSet

connector = MagentoToolSet(
    base_url="https://shop.example.com",
    access_token=secrets["MAGENTO_TOKEN"],
)
```

Tools:
`list_products(page_size, current_page, filters, include_ids, include_raw)`,
`get_product(sku)`, `upsert_product(product)`,
`delete_product(sku)` (destructive),
`list_orders(page_size, current_page, filters, include_ids, include_raw)`,
`get_order(order_id)`,
`list_customers(page_size, current_page, filters, include_ids, include_raw)`,
`set_stock_item(sku, stock_item)`.

### Agent-ready behavior

- `list_products`, `list_orders`, `list_customers` return compact
  summaries with stable refs plus user-facing fields. Products are
  addressed by `sku` (user-facing); orders show `increment_id` (the
  customer-facing order number).
- Raw Magento IDs hidden by default; pass `include_ids=True` to opt
  in. Pass `include_raw=True` for the unmodified payload.
- Default `page_size` is **25**. Filters use Magento's
  `searchCriteria[...]` syntax.
- `upsert_product` and `delete_product` are SKU-addressed (so the
  user-facing identifier is enough). `delete_product` accepts either
  the raw SKU string or a dict returned by `list_products(include_ids=True)`.
- Destructive tools: `delete_product`.

## AmazonSellerToolSet

Wraps Amazon Selling Partner API. Caller supplies an LWA bearer token;
pass a custom ``AuthStrategy`` for SigV4 if needed.

```python
from maivn_tools import AmazonSellerToolSet

connector = AmazonSellerToolSet(access_token=secrets["LWA_ACCESS_TOKEN"])
```

Tools:
`list_orders(marketplace_ids, created_after, ..., max_results, include_ids, include_raw)`,
`get_order(order_id)`, `list_order_items(order_id)`,
`list_inventory_summaries(marketplace_ids, ...)`,
`get_catalog_item(asin, marketplace_ids)`,
`search_catalog_items(keywords, marketplace_ids, ...)`,
`create_report(...)`, `get_report(report_id)`.

### Agent-ready behavior

- `list_orders` returns compact summaries with `order_ref` plus the
  always-shown user-facing `amazon_order_id` (formatted like
  `123-1234567-1234567` -- these appear on packing slips and in Seller
  Central, so they are not hidden), `purchase_date`, `order_status`,
  `fulfillment_channel`, `buyer_email`, `total_amount` /
  `total_currency`, and shipped / unshipped item counts.
- `include_ids=True` adds `seller_order_id` (the merchant-side ID).
  Pass `include_raw=True` for the unmodified SP-API payload. The
  `NextToken` pagination cursor is preserved as `next_token`.
- Default `max_results` is **25**.
- No `destructive=True` tools -- Amazon order cancellation and product
  retirement are handled via SP-API workflows that this surface does
  not expose.

## EbayToolSet

```python
from maivn_tools import EbayToolSet

connector = EbayToolSet(access_token=secrets["EBAY_TOKEN"])
```

Tools:
`search_items(q, category_ids, filter, limit, offset, include_ids, include_raw)`,
`get_item(item_id)`,
`list_inventory_items(limit, offset, include_ids, include_raw)`,
`upsert_inventory_item(sku, payload)`, `create_offer(payload)`,
`publish_offer(offer_id)`,
`list_orders(limit, offset, filter, include_ids, include_raw)`,
`get_order(order_id)`,
`issue_refund(order_id, payload)` (destructive).

### Agent-ready behavior

- `search_items` returns compact summaries with `item_ref` plus
  user-facing `title`, `price`, `condition`, `seller_username`, `item_web_url`.
  `list_orders` returns `order_ref` plus user-facing `order_id` (the
  eBay buyer-visible order number), `buyer_username`, `creation_date`,
  `order_fulfillment_status`, `total_amount`, and `total_currency`.
- Raw eBay IDs hidden by default; pass `include_ids=True` to opt in
  (needed for `get_item`, `issue_refund`). Pass `include_raw=True` for
  the unmodified payload.
- Default `limit` is **25**.
- `issue_refund` accepts either the raw order ID or the dict from
  `list_orders(include_ids=True)`.
- Destructive tools: `issue_refund`. `publish_offer` is destructive in
  effect (makes a listing live).

## WalmartMarketplaceToolSet

```python
from maivn_tools import WalmartMarketplaceToolSet

connector = WalmartMarketplaceToolSet(access_token=secrets["WM_ACCESS_TOKEN"])
```

Tools:
`list_items(limit, offset, include_ids, include_raw)`,
`get_item(sku)`, `retire_item(sku)` (destructive),
`list_orders(created_start_date, created_end_date, status, limit, include_ids, include_raw)`,
`get_order(purchase_order_id)`,
`acknowledge_order(purchase_order_id)`, `get_inventory(sku)`,
`set_inventory(sku, quantity, unit)`, `list_feeds(feed_id)`.

### Agent-ready behavior

- `list_items` returns compact summaries with `item_ref` plus
  user-facing `sku`, `product_name`, `price`, `publish_status`,
  `lifecycle_status`. `list_orders` returns `order_ref` plus the
  user-facing `purchase_order_id` and `customer_order_id`, `order_date`,
  `customer_name`, `customer_email_id`.
- `include_ids=True` adds the WPID / GTIN for items and a raw copy of
  the purchase-order ID. Pass `include_raw=True` for the unmodified
  payload. The orders list also preserves the `next_cursor` for paging.
- Default `limit` is **20**.
- `retire_item` accepts either the raw SKU or the dict from
  `list_items` / `get_item`. Other order / inventory write tools are
  SKU- / purchase-order-id-addressed (user-facing identifiers).
- Destructive tools: `retire_item`.
