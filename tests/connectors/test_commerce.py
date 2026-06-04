# pyright: strict
from __future__ import annotations

from collections.abc import Callable

import pytest

from maivn_tools.connectors.amazon_seller import AmazonSellerToolSet
from maivn_tools.connectors.bigcommerce import BigCommerceToolSet
from maivn_tools.connectors.ebay import EbayToolSet
from maivn_tools.connectors.magento import MagentoToolSet
from maivn_tools.connectors.shopify import ShopifyToolSet
from maivn_tools.connectors.walmart_marketplace import WalmartMarketplaceToolSet
from maivn_tools.connectors.woocommerce import WooCommerceToolSet
from maivn_tools.testing import MockTransport, json_response


def _is_destructive(method: Callable[..., object]) -> bool:
    from maivn._internal.utils.toolset import get_toolify_options

    opts = get_toolify_options(method)
    return bool(opts and opts.destructive)


# MARK: - Shopify


def test_shopify() -> None:
    transport = MockTransport()
    connector = ShopifyToolSet(shop="acme", access_token="shpat_xxx", transport=transport)
    for _ in range(14):
        transport.enqueue(json_response({}))
    connector.get_shop()
    connector.list_products(limit=10, page_info="p", status="active")
    connector.get_product(1)
    connector.create_product({"title": "T"})
    connector.update_product(1, {"title": "T2"})
    connector.delete_product(1)
    connector.list_orders(financial_status="paid", fulfillment_status="any", page_info="p")
    connector.get_order(1)
    connector.create_order({"line_items": []})
    connector.cancel_order(1, reason="customer", refund=True, restock=False)
    connector.list_customers(page_info="p")
    connector.create_customer({"email": "x@y"})
    connector.search_customers("alice")
    connector.list_inventory_levels(location_ids=[1], inventory_item_ids=[2])
    assert "acme.myshopify.com" in transport.requests[0].url
    assert transport.requests[0].headers["X-Shopify-Access-Token"] == "shpat_xxx"
    with pytest.raises(ValueError):
        ShopifyToolSet(shop="", access_token="x")
    with pytest.raises(ValueError):
        connector.get_product("")
    with pytest.raises(ValueError):
        connector.create_product({})
    with pytest.raises(ValueError):
        connector.update_product(0, {"x": 1})
    with pytest.raises(ValueError):
        connector.delete_product("")
    with pytest.raises(ValueError):
        connector.get_order("")
    with pytest.raises(ValueError):
        connector.create_order({})
    with pytest.raises(ValueError):
        connector.cancel_order("")
    with pytest.raises(ValueError):
        connector.create_customer({})
    with pytest.raises(ValueError):
        connector.search_customers("")


def test_shopify_inventory_and_fulfillment() -> None:
    transport = MockTransport()
    connector = ShopifyToolSet(shop="acme", access_token="t", transport=transport)
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.set_inventory_level(inventory_item_id=1, location_id=2, available=10)
    connector.create_fulfillment(
        order_id=1,
        line_items_by_fulfillment_order=[{"fulfillment_order_id": 99}],
    )
    with pytest.raises(ValueError):
        connector.create_fulfillment(
            order_id=0,
            line_items_by_fulfillment_order=[{"fulfillment_order_id": 1}],
        )


def test_shopify_list_products_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = ShopifyToolSet(shop="acme", access_token="t", transport=transport)
    transport.enqueue(
        json_response(
            {
                "products": [
                    {
                        "id": 7001,
                        "title": "Widget",
                        "status": "active",
                        "vendor": "Acme",
                        "product_type": "gadget",
                        "variants": [{"sku": "WID-1", "price": "9.99"}],
                    }
                ]
            }
        )
    )
    result = connector.list_products()
    product = result["products"][0]
    assert product["product_ref"] == "product_1"
    assert product["title"] == "Widget"
    assert product["sku"] == "WID-1"
    assert product["price"] == "9.99"
    assert "product_id" not in product


def test_shopify_list_products_include_ids_exposes_raw_id() -> None:
    transport = MockTransport()
    connector = ShopifyToolSet(shop="acme", access_token="t", transport=transport)
    transport.enqueue(json_response({"products": [{"id": 9999, "title": "X"}]}))
    result = connector.list_products(include_ids=True)
    assert result["products"][0]["product_id"] == 9999


def test_shopify_list_orders_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = ShopifyToolSet(shop="acme", access_token="t", transport=transport)
    transport.enqueue(
        json_response(
            {
                "orders": [
                    {
                        "id": 555,
                        "name": "#1001",
                        "total_price": "42.00",
                        "currency": "USD",
                        "financial_status": "paid",
                        "fulfillment_status": "fulfilled",
                        "customer": {
                            "first_name": "Alice",
                            "last_name": "Example",
                            "email": "alice@x",
                        },
                    }
                ]
            }
        )
    )
    result = connector.list_orders()
    order = result["orders"][0]
    assert order["order_ref"] == "order_1"
    assert order["order_number"] == "#1001"
    assert order["customer_name"] == "Alice Example"
    assert order["total_price"] == "42.00"
    assert "order_id" not in order


def test_shopify_cancel_order_destructive_and_accepts_dict() -> None:
    transport = MockTransport()
    connector = ShopifyToolSet(shop="acme", access_token="t", transport=transport)
    assert _is_destructive(connector.cancel_order)
    transport.enqueue(json_response({}))
    connector.cancel_order({"order_id": 42, "order_number": "#1002"}, reason="fraud")
    assert "/orders/42/cancel.json" in transport.requests[0].url


def test_shopify_update_product_accepts_summary_dict() -> None:
    transport = MockTransport()
    connector = ShopifyToolSet(shop="acme", access_token="t", transport=transport)
    transport.enqueue(json_response({"product": {"id": 7}}))
    connector.update_product({"product_id": 7, "product_ref": "product_1"}, {"title": "new"})
    assert "/products/7.json" in transport.requests[0].url


def test_shopify_delete_product_destructive() -> None:
    assert _is_destructive(ShopifyToolSet.delete_product)


# MARK: - WooCommerce


def test_woocommerce() -> None:
    transport = MockTransport()
    connector = WooCommerceToolSet(
        site_url="https://shop.example.com",
        consumer_key="ck",
        consumer_secret="cs",
        transport=transport,
    )
    for _ in range(11):
        transport.enqueue(json_response({}))
    connector.list_products(per_page=10, search="hat", status="publish")
    connector.get_product(1)
    connector.create_product({"name": "Hat"})
    connector.update_product(1, {"name": "Hat2"})
    connector.delete_product(1, force=True)
    connector.list_orders(status="completed", customer=1)
    connector.create_order({"line_items": []})
    connector.update_order(1, {"status": "completed"})
    connector.list_customers(search="alice")
    connector.create_coupon({"code": "SAVE10"})
    connector.list_reports()
    auth = transport.requests[0].headers["Authorization"]
    assert auth.startswith("Basic ")
    with pytest.raises(ValueError):
        WooCommerceToolSet(site_url="", consumer_key="ck", consumer_secret="cs")
    with pytest.raises(ValueError):
        connector.get_product(0)
    with pytest.raises(ValueError):
        connector.create_product({})
    with pytest.raises(ValueError):
        connector.update_product(0, {"x": 1})
    with pytest.raises(ValueError):
        connector.update_product(1, {})
    with pytest.raises(ValueError):
        connector.delete_product(0)
    with pytest.raises(ValueError):
        connector.create_order({})
    with pytest.raises(ValueError):
        connector.update_order(0, {})
    with pytest.raises(ValueError):
        connector.update_order(1, {})
    with pytest.raises(ValueError):
        connector.create_coupon({})


def test_woocommerce_list_products_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = WooCommerceToolSet(
        site_url="https://x", consumer_key="ck", consumer_secret="cs", transport=transport
    )
    transport.enqueue(
        json_response(
            [
                {
                    "id": 101,
                    "name": "Hat",
                    "sku": "HAT-1",
                    "price": "19.99",
                    "status": "publish",
                    "stock_status": "instock",
                }
            ]
        )
    )
    result = connector.list_products()
    product = result["products"][0]
    assert product["product_ref"] == "product_1"
    assert product["name"] == "Hat"
    assert product["sku"] == "HAT-1"
    assert "product_id" not in product


def test_woocommerce_list_products_include_ids() -> None:
    transport = MockTransport()
    connector = WooCommerceToolSet(
        site_url="https://x", consumer_key="ck", consumer_secret="cs", transport=transport
    )
    transport.enqueue(json_response([{"id": 99, "name": "X"}]))
    result = connector.list_products(include_ids=True)
    assert result["products"][0]["product_id"] == 99


def test_woocommerce_update_order_accepts_summary_dict() -> None:
    transport = MockTransport()
    connector = WooCommerceToolSet(
        site_url="https://x", consumer_key="ck", consumer_secret="cs", transport=transport
    )
    transport.enqueue(json_response({}))
    connector.update_order({"order_id": 42}, {"status": "completed"})
    assert "/orders/42" in transport.requests[0].url


def test_woocommerce_delete_product_destructive() -> None:
    assert _is_destructive(WooCommerceToolSet.delete_product)


# MARK: - BigCommerce


def test_bigcommerce() -> None:
    transport = MockTransport()
    connector = BigCommerceToolSet(store_hash="abc", access_token="tok", transport=transport)
    for _ in range(9):
        transport.enqueue(json_response({}))
    connector.list_products(sku="SKU1", keyword="hat", limit=5)
    connector.create_product({"name": "X"})
    connector.update_product(1, {"name": "Y"})
    connector.delete_product(1)
    connector.list_orders(status_id=1)
    connector.get_order(1)
    connector.list_customers()
    connector.create_customers([{"email": "x@y"}])
    connector.get_cart("cart-1")
    assert "/stores/abc/v3/catalog/products" in transport.requests[0].url
    assert transport.requests[0].headers["X-Auth-Token"] == "tok"
    with pytest.raises(ValueError):
        BigCommerceToolSet(store_hash="", access_token="t")
    with pytest.raises(ValueError):
        connector.create_product({})
    with pytest.raises(ValueError):
        connector.update_product(0, {"x": 1})
    with pytest.raises(ValueError):
        connector.delete_product(0)
    with pytest.raises(ValueError):
        connector.create_customers([])


def test_bigcommerce_list_products_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = BigCommerceToolSet(store_hash="abc", access_token="t", transport=transport)
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": 555,
                        "name": "Hat",
                        "sku": "HAT-1",
                        "price": "19.99",
                        "is_visible": True,
                    }
                ]
            }
        )
    )
    result = connector.list_products()
    product = result["products"][0]
    assert product["product_ref"] == "product_1"
    assert product["name"] == "Hat"
    assert product["sku"] == "HAT-1"
    assert "product_id" not in product


def test_bigcommerce_list_products_include_ids() -> None:
    transport = MockTransport()
    connector = BigCommerceToolSet(store_hash="abc", access_token="t", transport=transport)
    transport.enqueue(json_response({"data": [{"id": 42, "name": "X"}]}))
    result = connector.list_products(include_ids=True)
    assert result["products"][0]["product_id"] == 42


def test_bigcommerce_delete_product_destructive_and_accepts_dict() -> None:
    transport = MockTransport()
    connector = BigCommerceToolSet(store_hash="abc", access_token="t", transport=transport)
    assert _is_destructive(connector.delete_product)
    transport.enqueue(json_response({}))
    connector.delete_product({"product_id": 7})
    assert "/catalog/products/7" in transport.requests[0].url


# MARK: - Magento


def test_magento() -> None:
    transport = MockTransport()
    connector = MagentoToolSet(
        base_url="https://shop.example.com",
        access_token="tok",
        transport=transport,
    )
    for _ in range(8):
        transport.enqueue(json_response({}))
    connector.list_products(filters=[{"field": "name", "value": "Hat"}])
    connector.get_product("SKU-1")
    connector.upsert_product({"sku": "SKU-1", "name": "Hat"})
    connector.delete_product("SKU-1")
    connector.list_orders()
    connector.get_order(1)
    connector.list_customers()
    connector.set_stock_item(sku="SKU-1", qty=10, is_in_stock=True, item_id=1)
    assert transport.requests[0].headers["Authorization"] == "Bearer tok"
    assert "searchCriteria[pageSize]" in transport.requests[0].params
    with pytest.raises(ValueError):
        MagentoToolSet(base_url="", access_token="t")
    with pytest.raises(ValueError):
        connector.get_product("")
    with pytest.raises(ValueError):
        connector.upsert_product({"name": "X"})
    with pytest.raises(ValueError):
        connector.delete_product("")
    with pytest.raises(ValueError):
        connector.set_stock_item(sku="", qty=10)


def test_magento_list_products_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = MagentoToolSet(base_url="https://x", access_token="t", transport=transport)
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "id": 555,
                        "sku": "SKU-1",
                        "name": "Hat",
                        "price": 19.99,
                        "status": 1,
                        "type_id": "simple",
                    }
                ],
                "total_count": 1,
            }
        )
    )
    result = connector.list_products()
    product = result["products"][0]
    assert product["product_ref"] == "product_1"
    assert product["name"] == "Hat"
    assert product["sku"] == "SKU-1"
    assert "product_id" not in product


def test_magento_list_products_include_ids() -> None:
    transport = MockTransport()
    connector = MagentoToolSet(base_url="https://x", access_token="t", transport=transport)
    transport.enqueue(json_response({"items": [{"id": 42, "sku": "X", "name": "x"}]}))
    result = connector.list_products(include_ids=True)
    assert result["products"][0]["product_id"] == 42


def test_magento_delete_product_destructive_and_accepts_dict() -> None:
    transport = MockTransport()
    connector = MagentoToolSet(base_url="https://x", access_token="t", transport=transport)
    assert _is_destructive(connector.delete_product)
    transport.enqueue(json_response({}))
    connector.delete_product({"sku": "SKU-1"})
    assert "/products/SKU-1" in transport.requests[0].url


# MARK: - Amazon Seller


def test_amazon_seller() -> None:
    transport = MockTransport()
    connector = AmazonSellerToolSet(access_token="atza", transport=transport)
    for _ in range(7):
        transport.enqueue(json_response({}))
    connector.list_orders(
        marketplace_ids=["ATVPDKIKX0DER"],
        created_after="2026-01-01T00:00:00Z",
        created_before="2026-02-01T00:00:00Z",
        order_statuses=["Unshipped"],
        next_token="t",
    )
    connector.get_order("123-456")
    connector.list_order_items("123-456")
    connector.list_inventory_summaries(
        marketplace_ids=["ATVPDKIKX0DER"],
        granularity_id="ATVPDKIKX0DER",
    )
    connector.get_catalog_item(
        "B00X",
        marketplace_ids=["ATVPDKIKX0DER"],
        included_data=["summaries"],
    )
    connector.search_catalog_items(
        marketplace_ids=["ATVPDKIKX0DER"],
        identifiers=["123"],
        identifiers_type="ASIN",
        keywords="hat",
    )
    connector.create_report(
        report_type="GET_FLAT_FILE_OPEN_LISTINGS_DATA",
        marketplace_ids=["ATVPDKIKX0DER"],
        data_start_time="2026-01-01T00:00:00Z",
        data_end_time="2026-02-01T00:00:00Z",
    )
    assert transport.requests[0].headers["x-amz-access-token"] == "atza"
    with pytest.raises(ValueError):
        AmazonSellerToolSet(access_token="")
    with pytest.raises(ValueError):
        connector.list_orders(marketplace_ids=[], created_after="x")
    with pytest.raises(ValueError):
        connector.get_order("")
    with pytest.raises(ValueError):
        connector.list_order_items("")
    with pytest.raises(ValueError):
        connector.list_inventory_summaries(marketplace_ids=[])
    with pytest.raises(ValueError):
        connector.get_catalog_item("", marketplace_ids=["X"])
    with pytest.raises(ValueError):
        connector.search_catalog_items(marketplace_ids=[])
    with pytest.raises(ValueError):
        connector.create_report(report_type="", marketplace_ids=["X"])


def test_amazon_seller_get_report() -> None:
    transport = MockTransport()
    connector = AmazonSellerToolSet(access_token="atza", transport=transport)
    transport.enqueue(json_response({}))
    connector.get_report("r1")
    with pytest.raises(ValueError):
        connector.get_report("")


def test_amazon_seller_list_orders_returns_summaries() -> None:
    transport = MockTransport()
    connector = AmazonSellerToolSet(access_token="atza", transport=transport)
    transport.enqueue(
        json_response(
            {
                "payload": {
                    "Orders": [
                        {
                            "AmazonOrderId": "123-1234567-1234567",
                            "PurchaseDate": "2026-01-01T00:00:00Z",
                            "OrderStatus": "Shipped",
                            "FulfillmentChannel": "AFN",
                            "OrderTotal": {"Amount": "29.99", "CurrencyCode": "USD"},
                        }
                    ],
                    "NextToken": "abc",
                }
            }
        )
    )
    result = connector.list_orders(
        marketplace_ids=["ATVPDKIKX0DER"],
        created_after="2026-01-01T00:00:00Z",
    )
    order = result["orders"][0]
    assert order["order_ref"] == "order_1"
    assert order["amazon_order_id"] == "123-1234567-1234567"
    assert order["total_amount"] == "29.99"
    assert result["next_token"] == "abc"


# MARK: - eBay


def test_ebay() -> None:
    transport = MockTransport()
    connector = EbayToolSet(access_token="t", marketplace_id="EBAY_US", transport=transport)
    for _ in range(9):
        transport.enqueue(json_response({}))
    connector.search_items(q="hat", category_ids=["1"], filter="price:[10..50]", sort="price")
    connector.get_item("v1|123|0")
    connector.list_inventory_items()
    connector.upsert_inventory_item("SKU-1", {"sku": "SKU-1"})
    connector.create_offer({"sku": "SKU-1"})
    connector.publish_offer("offer1")
    connector.list_orders(filter="creationdate:[2026-01-01..]")
    connector.get_order("o1")
    connector.issue_refund(
        "o1",
        reason_for_refund="BUYER_CANCEL",
        order_level_refund_amount={"value": "12.99", "currency": "USD"},
        comment="ok",
    )
    assert transport.requests[0].headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_US"
    with pytest.raises(ValueError):
        EbayToolSet(access_token="")
    with pytest.raises(ValueError):
        connector.get_item("")
    with pytest.raises(ValueError):
        connector.upsert_inventory_item("", {"x": 1})
    with pytest.raises(ValueError):
        connector.create_offer({})
    with pytest.raises(ValueError):
        connector.publish_offer("")
    with pytest.raises(ValueError):
        connector.get_order("")
    with pytest.raises(ValueError):
        connector.issue_refund("", reason_for_refund="X")
    with pytest.raises(ValueError):
        connector.issue_refund("o", reason_for_refund="")


def test_ebay_search_items_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = EbayToolSet(access_token="t", transport=transport)
    transport.enqueue(
        json_response(
            {
                "itemSummaries": [
                    {
                        "itemId": "v1|123|0",
                        "title": "Vintage Hat",
                        "price": {"value": "19.99", "currency": "USD"},
                        "condition": "Used",
                        "itemWebUrl": "https://ebay.com/itm/123",
                    }
                ],
                "total": 1,
            }
        )
    )
    result = connector.search_items(q="hat")
    item = result["items"][0]
    assert item["item_ref"] == "item_1"
    assert item["title"] == "Vintage Hat"
    assert item["price_value"] == "19.99"
    assert "item_id" not in item


def test_ebay_search_items_include_ids() -> None:
    transport = MockTransport()
    connector = EbayToolSet(access_token="t", transport=transport)
    transport.enqueue(json_response({"itemSummaries": [{"itemId": "v1|999|0", "title": "X"}]}))
    result = connector.search_items(q="x", include_ids=True)
    assert result["items"][0]["item_id"] == "v1|999|0"


def test_ebay_issue_refund_destructive() -> None:
    assert _is_destructive(EbayToolSet.issue_refund)


# MARK: - Walmart Marketplace


def test_walmart_marketplace() -> None:
    transport = MockTransport()
    connector = WalmartMarketplaceToolSet(
        access_token="t",
        consumer_id="cid",
        channel_type="WM",
        transport=transport,
    )
    for _ in range(9):
        transport.enqueue(json_response({}))
    connector.list_items()
    connector.get_item("SKU-1")
    connector.retire_item("SKU-1")
    connector.list_orders(
        created_start_date="2026-01-01",
        created_end_date="2026-02-01",
        status="Created",
        limit=10,
    )
    connector.get_order("po-1")
    connector.acknowledge_order("po-1")
    connector.get_inventory("SKU-1")
    connector.set_inventory(sku="SKU-1", quantity=5)
    connector.list_feeds(feed_id="f1")
    assert transport.requests[0].headers["WM_SEC.ACCESS_TOKEN"] == "t"
    assert transport.requests[0].headers["WM_CONSUMER.ID"] == "cid"
    with pytest.raises(ValueError):
        WalmartMarketplaceToolSet(access_token="")
    with pytest.raises(ValueError):
        connector.get_item("")
    with pytest.raises(ValueError):
        connector.retire_item("")
    with pytest.raises(ValueError):
        connector.list_orders(created_start_date="")
    with pytest.raises(ValueError):
        connector.get_order("")
    with pytest.raises(ValueError):
        connector.acknowledge_order("")
    with pytest.raises(ValueError):
        connector.get_inventory("")
    with pytest.raises(ValueError):
        connector.set_inventory(sku="", quantity=1)


def test_walmart_list_items_returns_summaries() -> None:
    transport = MockTransport()
    connector = WalmartMarketplaceToolSet(access_token="t", transport=transport)
    transport.enqueue(
        json_response(
            {
                "ItemResponses": {
                    "ItemResponse": [
                        {
                            "sku": "SKU-1",
                            "wpid": "WMPID-555",
                            "productName": "Hat",
                            "price": 19.99,
                            "publishedStatus": "PUBLISHED",
                        }
                    ],
                    "totalItems": 1,
                }
            }
        )
    )
    result = connector.list_items()
    item = result["items"][0]
    assert item["item_ref"] == "item_1"
    assert item["sku"] == "SKU-1"
    assert "wpid" not in item


def test_walmart_list_items_include_ids() -> None:
    transport = MockTransport()
    connector = WalmartMarketplaceToolSet(access_token="t", transport=transport)
    transport.enqueue(
        json_response({"ItemResponses": {"ItemResponse": [{"sku": "S", "wpid": "WID-1"}]}})
    )
    result = connector.list_items(include_ids=True)
    assert result["items"][0]["wpid"] == "WID-1"


def test_walmart_retire_item_destructive_and_accepts_dict() -> None:
    transport = MockTransport()
    connector = WalmartMarketplaceToolSet(access_token="t", transport=transport)
    assert _is_destructive(connector.retire_item)
    transport.enqueue(json_response({}))
    connector.retire_item({"sku": "SKU-1"})
    assert "/items/SKU-1" in transport.requests[0].url
