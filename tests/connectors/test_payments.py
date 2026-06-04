# pyright: strict
from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from maivn_tools.connectors.billcom import BillToolSet
from maivn_tools.connectors.brex import BrexToolSet
from maivn_tools.connectors.chargebee import ChargebeeToolSet
from maivn_tools.connectors.expensify import ExpensifyToolSet
from maivn_tools.connectors.netsuite import NetSuiteToolSet
from maivn_tools.connectors.paypal import PayPalToolSet
from maivn_tools.connectors.plaid import PlaidToolSet
from maivn_tools.connectors.quickbooks import QuickBooksToolSet
from maivn_tools.connectors.ramp import RampToolSet
from maivn_tools.connectors.recurly import RecurlyToolSet
from maivn_tools.connectors.square import SquareToolSet
from maivn_tools.connectors.stripe import StripeToolSet, stripe_form_encode
from maivn_tools.connectors.xero import XeroToolSet
from maivn_tools.core.permissions import PermissionFlag, PermissionSet
from maivn_tools.testing import MockTransport, json_response

# MARK: - Stripe


def test_stripe_form_encode_nested() -> None:
    out = stripe_form_encode({"customer": {"email": "x", "metadata": {"k": "v"}}})
    assert out["customer[email]"] == "x"
    assert out["customer[metadata][k]"] == "v"


def test_stripe() -> None:
    transport = MockTransport()
    connector = StripeToolSet(api_key="sk_test_xxx", api_version="2024-04-10", transport=transport)
    for _ in range(20):
        transport.enqueue(json_response({"id": "x"}))
    connector.list_customers(email="x@y", limit=50, starting_after="cus_1", ending_before="cus_0")
    connector.get_customer("cus_1")
    connector.create_customer(email="x@y", description="d")
    connector.update_customer("cus_1", email="z@y")
    connector.delete_customer("cus_1")
    connector.list_subscriptions(customer="cus_1", status="active")
    connector.create_subscription(
        customer="cus_1",
        items=[{"price": "p_1"}],
        default_payment_method="pm_1",
    )
    connector.cancel_subscription("sub_1", invoice_now=True, prorate=False)
    connector.list_invoices(customer="cus_1", status="draft")
    connector.create_invoice(customer="cus_1", description="d")
    connector.finalize_invoice("in_1")
    connector.create_payment_intent(
        amount=1000,
        currency="usd",
        customer="cus_1",
        confirm=False,
        idempotency_key="k1",
    )
    connector.confirm_payment_intent("pi_1", payment_method="pm_1")
    connector.refund_charge(charge="ch_1", amount=500, idempotency_key="k2")
    connector.list_charges(customer="cus_1")
    connector.list_disputes()
    connector.update_dispute("du_1", evidence={"customer_email_address": "x@y"})
    connector.create_checkout_session(line_items=[{"price": "p_1", "quantity": 1}])
    connector.list_products(active=True)
    connector.list_prices(product="p_1")
    assert transport.requests[0].headers["Stripe-Version"] == "2024-04-10"
    assert transport.requests[0].headers["Authorization"] == "Bearer sk_test_xxx"
    assert transport.requests[6].params["items[0][price]"] == "p_1"
    assert transport.requests[11].headers["Idempotency-Key"] == "k1"
    with pytest.raises(ValueError):
        StripeToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.list_customers(limit=0)
    with pytest.raises(ValueError):
        connector.get_customer("")
    with pytest.raises(ValueError):
        connector.create_customer()
    with pytest.raises(ValueError):
        connector.update_customer("", email="x")
    with pytest.raises(ValueError):
        connector.update_customer(
            "cus",
        )
    with pytest.raises(ValueError):
        connector.create_subscription(customer="", items=[])
    with pytest.raises(ValueError):
        connector.cancel_subscription("")
    with pytest.raises(ValueError):
        connector.create_invoice(customer="")
    with pytest.raises(ValueError):
        connector.finalize_invoice("")
    with pytest.raises(ValueError):
        connector.create_payment_intent(amount=0, currency="usd")
    with pytest.raises(ValueError):
        connector.confirm_payment_intent("")
    with pytest.raises(ValueError):
        connector.refund_charge()
    with pytest.raises(ValueError):
        connector.update_dispute("")
    with pytest.raises(ValueError):
        connector.create_checkout_session()


def test_stripe_balance() -> None:
    transport = MockTransport()
    connector = StripeToolSet(api_key="sk_test_xxx", transport=transport)
    transport.enqueue(json_response({"available": []}))
    connector.get_balance()


# MARK: - Square


def test_square() -> None:
    transport = MockTransport()
    connector = SquareToolSet(access_token="EAAA", transport=transport)
    for _ in range(15):
        transport.enqueue(json_response({}))
    connector.list_locations()
    connector.list_customers(limit=10, sort_field="DEFAULT", sort_order="ASC")
    connector.get_customer("c1")
    connector.create_customer({"email_address": "x@y"})
    connector.update_customer("c1", {"company_name": "Co"})
    connector.delete_customer("c1")
    connector.search_orders({"location_ids": ["L1"], "query": {"filter": {}}})
    connector.get_order("o1")
    connector.create_order(
        location_id="L1",
        order={"line_items": []},
        idempotency_key="i1",
    )
    connector.list_payments(
        begin_time="x",
        end_time="y",
        location_id="L1",
        cursor="c",
    )
    connector.create_payment(
        source_id="src",
        amount_money={"amount": 100, "currency": "USD"},
        idempotency_key="i",
        note="hi",
        order_id="o",
        customer_id="c",
        autocomplete=True,
    )
    connector.refund_payment(
        idempotency_key="r",
        amount_money={"amount": 50, "currency": "USD"},
        payment_id="p",
        reason="rejected",
    )
    connector.search_catalog({"object_types": ["ITEM"]})
    connector.upsert_catalog_object({"idempotency_key": "k", "object": {}})
    connector.list_inventory_counts(location_ids=["L1"], catalog_object_ids=["ITEM_1"], cursor="x")
    assert transport.requests[0].headers["Square-Version"] == "2026-01-22"
    with pytest.raises(ValueError):
        SquareToolSet(access_token="")
    with pytest.raises(ValueError):
        connector.get_customer("")
    with pytest.raises(ValueError):
        connector.create_customer({})
    with pytest.raises(ValueError):
        connector.update_customer("", {"x": 1})
    with pytest.raises(ValueError):
        connector.delete_customer("")
    with pytest.raises(ValueError):
        connector.search_orders({})
    with pytest.raises(ValueError):
        connector.get_order("")
    with pytest.raises(ValueError):
        connector.create_order(location_id="", order={"x": 1})
    with pytest.raises(ValueError):
        connector.create_payment(
            source_id="",
            amount_money={"amount": 1, "currency": "USD"},
            idempotency_key="i",
        )
    with pytest.raises(ValueError):
        connector.refund_payment(idempotency_key="r", amount_money={}, payment_id="")
    with pytest.raises(ValueError):
        connector.search_catalog({})
    with pytest.raises(ValueError):
        connector.upsert_catalog_object({})


# MARK: - PayPal


def test_paypal() -> None:
    transport = MockTransport()
    connector = PayPalToolSet(access_token="A21", transport=transport)
    for _ in range(13):
        transport.enqueue(json_response({}))
    connector.create_order(
        intent="CAPTURE",
        purchase_units=[{"amount": {"value": "10", "currency_code": "USD"}}],
        application_context={"brand_name": "MyCo"},
        payment_source={"paypal": {}},
    )
    connector.get_order("o1")
    connector.capture_order("o1")
    connector.authorize_order("o1")
    connector.get_capture("cap1")
    connector.refund_capture(
        "cap1",
        amount={"value": "5", "currency_code": "USD"},
        note_to_payer="sorry",
        invoice_id="inv-1",
    )
    connector.get_authorization("auth1")
    connector.void_authorization("auth1")
    connector.create_subscription(
        plan_id="P-1",
        subscriber={"email_address": "x@y"},
        application_context={"brand_name": "X"},
    )
    connector.get_subscription("s1")
    connector.cancel_subscription("s1", reason="bye")
    connector.suspend_subscription("s1")
    connector.list_disputes(status="OPEN")
    body = transport.requests[0].json_body
    assert body["intent"] == "CAPTURE"
    with pytest.raises(ValueError):
        PayPalToolSet(access_token="")
    with pytest.raises(ValueError):
        connector.create_order(intent="bogus", purchase_units=[{}])
    with pytest.raises(ValueError):
        connector.create_order(intent="CAPTURE", purchase_units=[])
    with pytest.raises(ValueError):
        connector.get_order("")
    with pytest.raises(ValueError):
        connector.capture_order("")
    with pytest.raises(ValueError):
        connector.authorize_order("")
    with pytest.raises(ValueError):
        connector.get_capture("")
    with pytest.raises(ValueError):
        connector.refund_capture("")
    with pytest.raises(ValueError):
        connector.get_authorization("")
    with pytest.raises(ValueError):
        connector.void_authorization("")
    with pytest.raises(ValueError):
        connector.create_subscription(plan_id="")
    with pytest.raises(ValueError):
        connector.get_subscription("")
    with pytest.raises(ValueError):
        connector.cancel_subscription("")
    with pytest.raises(ValueError):
        connector.suspend_subscription("")


def test_paypal_dispute_lookup() -> None:
    transport = MockTransport()
    connector = PayPalToolSet(access_token="A21", transport=transport)
    transport.enqueue(json_response({}))
    connector.get_dispute("d1")
    with pytest.raises(ValueError):
        connector.get_dispute("")


# MARK: - Plaid


def test_plaid() -> None:
    transport = MockTransport()
    connector = PlaidToolSet(
        client_id="cid",
        secret="sec",
        environment="sandbox",
        transport=transport,
    )
    for _ in range(11):
        transport.enqueue(json_response({}))
    connector.create_link_token(
        client_user_id="u1",
        client_name="MyApp",
        products=["transactions"],
        country_codes=["US"],
        webhook="https://x/w",
    )
    connector.exchange_public_token(public_token="public-sandbox-x")
    connector.get_accounts("access-1")
    connector.get_balance("access-1")
    connector.get_transactions(
        access_token="access-1",
        start_date="2026-01-01",
        end_date="2026-02-01",
        count=10,
        offset=0,
    )
    connector.sync_transactions(access_token="access-1", cursor="c1", count=100)
    connector.get_identity("access-1")
    connector.get_liabilities("access-1")
    connector.get_institution("ins_3", country_codes=["US"])
    connector.search_institutions(query="chase", country_codes=["US"], products=["auth"])
    connector.remove_item("access-1")
    body = transport.requests[0].json_body
    assert body["client_id"] == "cid"
    assert body["secret"] == "sec"
    with pytest.raises(ValueError):
        PlaidToolSet(client_id="", secret="x")
    with pytest.raises(ValueError):
        PlaidToolSet(client_id="x", secret="y", environment="bogus")
    with pytest.raises(ValueError):
        connector.create_link_token(
            client_user_id="",
            client_name="x",
            products=["transactions"],
            country_codes=["US"],
        )
    with pytest.raises(ValueError):
        connector.exchange_public_token(public_token="")
    with pytest.raises(ValueError):
        connector.get_accounts("")
    with pytest.raises(ValueError):
        connector.get_transactions(access_token="t", start_date="", end_date="2026-01-01")
    with pytest.raises(ValueError):
        connector.sync_transactions(access_token="")
    with pytest.raises(ValueError):
        connector.get_institution("", country_codes=["US"])
    with pytest.raises(ValueError):
        connector.search_institutions(query="", country_codes=["US"])
    with pytest.raises(ValueError):
        connector.remove_item("")


# MARK: - QuickBooks


def test_quickbooks() -> None:
    transport = MockTransport()
    connector = QuickBooksToolSet(
        access_token="qbo",
        realm_id="123",
        minor_version=70,
        transport=transport,
    )
    for _ in range(10):
        transport.enqueue(json_response({}))
    connector.query("SELECT * FROM Customer")
    connector.get_entity("Customer", "1")
    connector.create_entity("Customer", {"DisplayName": "X"})
    connector.update_entity("Customer", {"Id": "1", "SyncToken": "0", "DisplayName": "Y"})
    connector.delete_entity("Customer", {"Id": "1", "SyncToken": "0"})
    connector.list_customers(max_results=10)
    connector.list_invoices()
    connector.list_bills()
    connector.create_invoice({"Line": []})
    connector.create_payment({"TotalAmt": 100})
    assert "/v3/company/123/query" in transport.requests[0].url
    assert transport.requests[0].params["minorversion"] == 70
    with pytest.raises(ValueError):
        QuickBooksToolSet(access_token="", realm_id="x")
    with pytest.raises(ValueError):
        QuickBooksToolSet(access_token="x", realm_id="")
    with pytest.raises(ValueError):
        connector.query("")
    with pytest.raises(ValueError):
        connector.get_entity("", "1")
    with pytest.raises(ValueError):
        connector.create_entity("", {"x": 1})
    with pytest.raises(ValueError):
        connector.update_entity("Customer", {"x": 1})
    with pytest.raises(ValueError):
        connector.delete_entity("Customer", {"Id": "1"})


def test_quickbooks_company_info() -> None:
    transport = MockTransport()
    connector = QuickBooksToolSet(access_token="qbo", realm_id="123", transport=transport)
    transport.enqueue(json_response({}))
    connector.get_company_info()


# MARK: - Xero


def test_xero() -> None:
    transport = MockTransport()
    connector = XeroToolSet(access_token="xat", tenant_id="tnt", transport=transport)
    for _ in range(11):
        transport.enqueue(json_response({}))
    connector.list_connections()
    connector.list_contacts(where='Name="X"', order="UpdatedDateUTC DESC", page=2)
    connector.get_contact("c1")
    connector.upsert_contacts([{"Name": "X"}])
    connector.list_invoices(status="DRAFT", where='Type="ACCREC"')
    connector.upsert_invoices([{"Type": "ACCREC"}])
    connector.list_payments(where='Status="AUTHORISED"', order="Date DESC")
    connector.upsert_payments([{"Amount": 100}])
    connector.list_bank_transactions(where='Status="AUTHORISED"')
    connector.list_accounts(where='Type="BANK"')
    connector.get_organisation()
    assert transport.requests[0].headers["Xero-Tenant-Id"] == "tnt"
    with pytest.raises(ValueError):
        XeroToolSet(access_token="", tenant_id="x")
    with pytest.raises(ValueError):
        XeroToolSet(access_token="x", tenant_id="")
    with pytest.raises(ValueError):
        connector.get_contact("")
    with pytest.raises(ValueError):
        connector.upsert_contacts([])
    with pytest.raises(ValueError):
        connector.upsert_invoices([])
    with pytest.raises(ValueError):
        connector.upsert_payments([])


# MARK: - NetSuite


def test_netsuite() -> None:
    transport = MockTransport()
    connector = NetSuiteToolSet(account_id="123_TST", transport=transport)
    for _ in range(6):
        transport.enqueue(json_response({}))
    connector.suiteql("SELECT * FROM customer", limit=10)
    connector.list_records("customer", limit=10, q="name:Acme")
    connector.get_record("customer", 1)
    connector.create_record("customer", {"companyName": "Acme"})
    connector.update_record("customer", 1, {"companyName": "Acme2"})
    connector.delete_record("customer", 1)
    assert "123-tst" in transport.requests[0].url
    with pytest.raises(ValueError):
        NetSuiteToolSet(account_id="")
    with pytest.raises(ValueError):
        connector.suiteql("")
    with pytest.raises(ValueError):
        connector.list_records("")
    with pytest.raises(ValueError):
        connector.get_record("customer", "")
    with pytest.raises(ValueError):
        connector.create_record("", {"x": 1})
    with pytest.raises(ValueError):
        connector.update_record("customer", 1, {})
    with pytest.raises(ValueError):
        connector.delete_record("customer", "")


# MARK: - Ramp


def test_ramp() -> None:
    transport = MockTransport()
    connector = RampToolSet(access_token="r", transport=transport)
    for _ in range(9):
        transport.enqueue(json_response({}))
    connector.list_transactions(
        from_date="2026-01-01",
        to_date="2026-02-01",
        page_size=10,
        start="c",
    )
    connector.get_transaction("t1")
    connector.list_cards()
    connector.create_card(
        {
            "display_name": "Marketing",
            "user_id": "u1",
            "card_program_id": "cp1",
        }
    )
    connector.terminate_card("c1")
    connector.list_users()
    connector.list_reimbursements()
    connector.list_vendors()
    connector.list_departments()
    with pytest.raises(ValueError):
        RampToolSet(access_token="")
    with pytest.raises(ValueError):
        connector.get_transaction("")
    with pytest.raises(ValueError):
        connector.create_card({})
    with pytest.raises(ValueError):
        connector.terminate_card("")


# MARK: - Brex


def test_brex() -> None:
    transport = MockTransport()
    connector = BrexToolSet(access_token="b", transport=transport)
    for _ in range(10):
        transport.enqueue(json_response({}))
    connector.list_cash_accounts()
    connector.list_card_accounts()
    connector.list_transactions(account_id="acct_1", cursor="c", limit=20)
    connector.list_expenses(cursor="c")
    connector.get_expense("e1")
    connector.update_expense("e1", {"memo": "x"})
    connector.list_cards(cursor="c")
    connector.issue_card({"owner": {"type": "USER"}})
    connector.terminate_card("c1")
    connector.list_users(cursor="c")
    with pytest.raises(ValueError):
        BrexToolSet(access_token="")
    with pytest.raises(ValueError):
        connector.get_expense("")
    with pytest.raises(ValueError):
        connector.update_expense("e", {})
    with pytest.raises(ValueError):
        connector.issue_card({})
    with pytest.raises(ValueError):
        connector.terminate_card("")


def test_brex_vendors() -> None:
    transport = MockTransport()
    connector = BrexToolSet(access_token="b", transport=transport)
    transport.enqueue(json_response({}))
    connector.list_vendors()


# MARK: - Chargebee


def test_chargebee() -> None:
    transport = MockTransport()
    connector = ChargebeeToolSet(site="acme", api_key="cb", transport=transport)
    for _ in range(8):
        transport.enqueue(json_response({}))
    connector.list_customers(limit=5, offset="c", first_name="A", email="x@y")
    connector.get_customer("c1")
    connector.create_customer({"first_name": "A"})
    connector.list_subscriptions(status="active", customer_id="c1")
    connector.create_subscription_for_customer("c1", params={"item_price_id[0]": "pro"})
    connector.cancel_subscription("s1", end_of_term=True)
    connector.list_invoices(status="paid", customer_id="c1")
    connector.list_plans()
    assert "acme.chargebee.com" in transport.requests[0].url
    with pytest.raises(ValueError):
        ChargebeeToolSet(site="", api_key="x")
    with pytest.raises(ValueError):
        connector.get_customer("")
    with pytest.raises(ValueError):
        connector.create_customer({})
    with pytest.raises(ValueError):
        connector.create_subscription_for_customer("", params={"x": 1})
    with pytest.raises(ValueError):
        connector.cancel_subscription("")


# MARK: - Recurly


def test_recurly() -> None:
    transport = MockTransport()
    connector = RecurlyToolSet(api_key="rk", transport=transport)
    for _ in range(10):
        transport.enqueue(json_response({}))
    connector.list_accounts(cursor="c1")
    connector.get_account("a1")
    connector.create_account({"code": "u1"})
    connector.update_account("a1", {"first_name": "A"})
    connector.list_subscriptions(state="active")
    connector.create_subscription({"plan_code": "p"})
    connector.cancel_subscription("s1")
    connector.reactivate_subscription("s1")
    connector.list_invoices()
    connector.list_transactions()
    assert transport.requests[0].headers["Accept"].startswith("application/vnd.recurly.v")
    with pytest.raises(ValueError):
        RecurlyToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.get_account("")
    with pytest.raises(ValueError):
        connector.create_account({})
    with pytest.raises(ValueError):
        connector.update_account("a", {})
    with pytest.raises(ValueError):
        connector.create_subscription({})
    with pytest.raises(ValueError):
        connector.cancel_subscription("")
    with pytest.raises(ValueError):
        connector.reactivate_subscription("")


# MARK: - Bill.com


def test_billcom() -> None:
    transport = MockTransport()
    connector = BillToolSet(api_key="bk", dev_key="dk", transport=transport)
    for _ in range(9):
        transport.enqueue(json_response({}))
    connector.list_vendors()
    connector.create_vendor({"name": "Acme"})
    connector.get_vendor("v1")
    connector.list_bills()
    connector.create_bill({"vendorId": "v1"})
    connector.list_invoices()
    connector.create_invoice({"customerId": "c1"})
    connector.list_payments()
    connector.create_payment({"billId": "b1"})
    assert transport.requests[0].headers["sessionId"] == "bk"
    assert transport.requests[0].headers["devKey"] == "dk"
    with pytest.raises(ValueError):
        BillToolSet(api_key="", dev_key="dk")
    with pytest.raises(ValueError):
        connector.create_vendor({})
    with pytest.raises(ValueError):
        connector.get_vendor("")
    with pytest.raises(ValueError):
        connector.create_bill({})
    with pytest.raises(ValueError):
        connector.create_invoice({})
    with pytest.raises(ValueError):
        connector.create_payment({})


def test_billcom_customers() -> None:
    transport = MockTransport()
    connector = BillToolSet(api_key="bk", dev_key="dk", transport=transport)
    transport.enqueue(json_response({}))
    connector.list_customers()


# MARK: - Expensify


def test_expensify() -> None:
    transport = MockTransport()
    connector = ExpensifyToolSet(
        partner_user_id="pid",
        partner_user_secret="psec",
        transport=transport,
    )
    for _ in range(5):
        transport.enqueue(json_response({}))
    connector.export_report(report_id="r1", template_ftl="<#-- tpl -->")
    connector.report_export(
        report_state="APPROVED",
        template_ftl="<#-- tpl -->",
        approved_after="2026-01-01",
        approved_before="2026-02-01",
        policy_id="pol1",
    )
    connector.get_policy_list()
    connector.get_policy("pol1")
    connector.update_policy(policy_id="pol1", settings={"name": "New"})
    import json as _json

    request = transport.requests[0]
    job = _json.loads(request.params["requestJobDescription"])
    assert job["credentials"]["partnerUserID"] == "pid"
    assert job["credentials"]["partnerUserSecret"] == "psec"
    with pytest.raises(ValueError):
        ExpensifyToolSet(partner_user_id="", partner_user_secret="x")
    with pytest.raises(ValueError):
        connector.export_report(report_id="", template_ftl="<#-- tpl -->")
    with pytest.raises(ValueError):
        connector.export_report(report_id="r", file_extension="bogus", template_ftl="<#-- tpl -->")
    with pytest.raises(ValueError):
        connector.get_policy("")
    with pytest.raises(ValueError):
        connector.update_policy(policy_id="", settings={"x": 1})


# MARK: - Agent-ready behavior


def _is_destructive(method: Callable[..., object]) -> bool:
    from maivn._internal.utils.toolset import get_toolify_options

    opts = get_toolify_options(method)
    return bool(opts and opts.destructive)


# MARK: - Stripe agent-ready


def test_stripe_list_customers_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = StripeToolSet(api_key="sk_test_xxx", transport=transport)
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "cus_123",
                        "name": "Alice Example",
                        "email": "alice@example.test",
                        "description": "Top customer",
                        "currency": "usd",
                        "balance": -2500,
                        "delinquent": False,
                        "created": 1700000000,
                    }
                ],
                "has_more": True,
            }
        )
    )
    result = connector.list_customers(limit=5)
    assert result["customers"] == [
        {
            "customer_ref": "customer_1",
            "name": "Alice Example",
            "email": "alice@example.test",
            "description": "Top customer",
            "currency": "USD",
            "delinquent": False,
            "created": 1700000000,
            "balance": "-25.00 USD",
        }
    ]
    assert "customer_id" not in result["customers"][0]
    assert result["has_more"] is True
    assert result["next_cursor"] == "cus_123"


def test_stripe_list_customers_include_ids_exposes_raw_id() -> None:
    transport = MockTransport()
    connector = StripeToolSet(api_key="sk_test_xxx", transport=transport)
    transport.enqueue(json_response({"data": [{"id": "cus_999", "name": "Bob"}]}))
    result = connector.list_customers(include_ids=True)
    assert result["customers"][0]["customer_id"] == "cus_999"


def test_stripe_list_invoices_formats_money_and_hides_ids() -> None:
    transport = MockTransport()
    connector = StripeToolSet(api_key="sk_test_xxx", transport=transport)
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "in_1",
                        "number": "INV-001",
                        "status": "open",
                        "total": 12500,
                        "amount_due": 12500,
                        "amount_paid": 0,
                        "currency": "usd",
                        "customer": "cus_1",
                        "customer_email": "alice@example.test",
                        "due_date": 1700100000,
                        "created": 1700000000,
                    }
                ]
            }
        )
    )
    result = connector.list_invoices(limit=5)
    invoice = result["invoices"][0]
    assert invoice["invoice_ref"] == "invoice_1"
    assert invoice["total"] == "125.00 USD"
    assert invoice["status"] == "open"
    assert invoice["customer_email"] == "alice@example.test"
    assert "invoice_id" not in invoice
    assert "customer_id" not in invoice


def test_stripe_refund_charge_marks_destructive_and_accepts_dict() -> None:
    transport = MockTransport()
    connector = StripeToolSet(api_key="sk_test_xxx", transport=transport)
    transport.enqueue(json_response({"id": "re_1", "amount": 500}))
    assert _is_destructive(connector.refund_charge)
    connector.refund_charge(charge={"id": "ch_42"}, amount=500)
    assert transport.requests[0].params["charge"] == "ch_42"


def test_stripe_cancel_subscription_destructive_and_accepts_summary_dict() -> None:
    transport = MockTransport()
    connector = StripeToolSet(api_key="sk_test_xxx", transport=transport)
    transport.enqueue(json_response({"id": "sub_42", "status": "canceled"}))
    assert _is_destructive(connector.cancel_subscription)
    connector.cancel_subscription({"subscription_id": "sub_42"})
    assert "/v1/subscriptions/sub_42" in transport.requests[0].url


def test_stripe_update_customer_accepts_list_record() -> None:
    transport = MockTransport()
    connector = StripeToolSet(api_key="sk_test_xxx", transport=transport)
    transport.enqueue(json_response({"id": "cus_1"}))
    connector.update_customer({"customer_id": "cus_1", "name": "x"}, email="z@y")
    assert transport.requests[0].url.endswith("/v1/customers/cus_1")


# MARK: - Square agent-ready


def test_square_list_customers_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = SquareToolSet(access_token="EAAA", transport=transport)
    transport.enqueue(
        json_response(
            {
                "customers": [
                    {
                        "id": "cust_1",
                        "given_name": "Jane",
                        "family_name": "Doe",
                        "email_address": "jane@example.test",
                        "phone_number": "+15551234567",
                        "reference_id": "ext-1",
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                ],
                "cursor": "next-cursor",
            }
        )
    )
    result = connector.list_customers()
    assert result["customers"][0] == {
        "customer_ref": "customer_1",
        "name": "Jane Doe",
        "company": "",
        "email": "jane@example.test",
        "phone": "+15551234567",
        "reference_id": "ext-1",
        "created_at": "2026-01-01T00:00:00Z",
    }
    assert "customer_id" not in result["customers"][0]


def test_square_list_payments_formats_money_and_hides_ids() -> None:
    transport = MockTransport()
    connector = SquareToolSet(access_token="EAAA", transport=transport)
    transport.enqueue(
        json_response(
            {
                "payments": [
                    {
                        "id": "p_1",
                        "amount_money": {"amount": 4250, "currency": "USD"},
                        "status": "COMPLETED",
                        "source_type": "CARD",
                        "note": "Lunch",
                        "receipt_url": "https://sq/r/1",
                        "created_at": "2026-01-02T00:00:00Z",
                        "order_id": "o_1",
                        "customer_id": "c_1",
                    }
                ]
            }
        )
    )
    result = connector.list_payments()
    payment = result["payments"][0]
    assert payment["amount"] == "42.50 USD"
    assert payment["payment_ref"] == "payment_1"
    assert "payment_id" not in payment
    assert "order_id" not in payment


def test_square_list_payments_include_ids_exposes_raw_id() -> None:
    transport = MockTransport()
    connector = SquareToolSet(access_token="EAAA", transport=transport)
    transport.enqueue(
        json_response(
            {
                "payments": [
                    {
                        "id": "p_1",
                        "amount_money": {"amount": 100, "currency": "USD"},
                        "order_id": "o_1",
                        "customer_id": "c_1",
                    }
                ]
            }
        )
    )
    result = connector.list_payments(include_ids=True)
    assert result["payments"][0]["payment_id"] == "p_1"
    assert result["payments"][0]["order_id"] == "o_1"


def test_square_refund_payment_destructive_and_accepts_dict() -> None:
    transport = MockTransport()
    connector = SquareToolSet(access_token="EAAA", transport=transport)
    transport.enqueue(json_response({"refund": {"id": "r_1"}}))
    assert _is_destructive(connector.refund_payment)
    connector.refund_payment(
        idempotency_key="k1",
        amount_money={"amount": 100, "currency": "USD"},
        payment_id={"payment_id": "p_1"},
    )
    body = transport.requests[0].json_body
    assert body["payment_id"] == "p_1"


# MARK: - PayPal agent-ready


def test_paypal_list_disputes_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = PayPalToolSet(access_token="A21", transport=transport)
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "dispute_id": "PP-D-1",
                        "dispute_amount": {"value": "12.50", "currency_code": "USD"},
                        "status": "RESOLVED",
                        "dispute_state": "RESOLVED_BUYER_FAVOUR",
                        "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
                        "create_time": "2026-01-01T00:00:00Z",
                        "update_time": "2026-01-02T00:00:00Z",
                    }
                ]
            }
        )
    )
    result = connector.list_disputes()
    summary = result["disputes"][0]
    assert summary["dispute_ref"] == "dispute_1"
    assert summary["amount"] == "12.50 USD"
    assert "dispute_id" not in summary


def test_paypal_list_disputes_include_ids_exposes_raw_id() -> None:
    transport = MockTransport()
    connector = PayPalToolSet(access_token="A21", transport=transport)
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "dispute_id": "PP-D-1",
                        "dispute_amount": {"value": "12.50", "currency_code": "USD"},
                    }
                ]
            }
        )
    )
    result = connector.list_disputes(include_ids=True)
    assert result["disputes"][0]["dispute_id"] == "PP-D-1"


def test_paypal_refund_capture_destructive_and_accepts_dict() -> None:
    transport = MockTransport()
    connector = PayPalToolSet(access_token="A21", transport=transport)
    transport.enqueue(json_response({"id": "r1", "status": "COMPLETED"}))
    assert _is_destructive(connector.refund_capture)
    connector.refund_capture(
        {"capture_id": "cap42"},
        amount={"value": "5", "currency_code": "USD"},
    )
    assert "/v2/payments/captures/cap42/refund" in transport.requests[0].url


def test_paypal_cancel_subscription_destructive_and_accepts_dict() -> None:
    transport = MockTransport()
    connector = PayPalToolSet(access_token="A21", transport=transport)
    transport.enqueue(json_response({}))
    assert _is_destructive(connector.cancel_subscription)
    connector.cancel_subscription({"subscription_id": "S-42"})
    assert "/v1/billing/subscriptions/S-42/cancel" in transport.requests[0].url


def test_paypal_void_authorization_is_destructive() -> None:
    transport = MockTransport()
    connector = PayPalToolSet(access_token="A21", transport=transport)
    transport.enqueue(json_response({}))
    assert _is_destructive(connector.void_authorization)
    connector.void_authorization({"authorization_id": "auth42"})
    assert "/v2/payments/authorizations/auth42/void" in transport.requests[0].url


# MARK: - Plaid agent-ready


def test_plaid_get_transactions_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = PlaidToolSet(
        client_id="cid",
        secret="sec",
        environment="sandbox",
        transport=transport,
    )
    transport.enqueue(
        json_response(
            {
                "transactions": [
                    {
                        "transaction_id": "txn_1",
                        "account_id": "acc_1",
                        "name": "Starbucks",
                        "merchant_name": "Starbucks",
                        "amount": 5.75,
                        "iso_currency_code": "USD",
                        "date": "2026-01-01",
                        "category": ["Food and Drink", "Coffee"],
                        "pending": False,
                    }
                ],
                "total_transactions": 1,
            }
        )
    )
    result = connector.get_transactions(
        access_token="access-1",
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    summary = result["transactions"][0]
    assert summary["transaction_ref"] == "transaction_1"
    assert summary["amount"] == "5.75 USD"
    assert summary["category"] == "Food and Drink > Coffee"
    assert "transaction_id" not in summary


def test_plaid_get_transactions_include_ids_exposes_raw_id() -> None:
    transport = MockTransport()
    connector = PlaidToolSet(
        client_id="cid",
        secret="sec",
        environment="sandbox",
        transport=transport,
    )
    transport.enqueue(
        json_response(
            {
                "transactions": [
                    {
                        "transaction_id": "txn_1",
                        "account_id": "acc_1",
                        "name": "Starbucks",
                    }
                ]
            }
        )
    )
    result = connector.get_transactions(
        access_token="access-1",
        start_date="2026-01-01",
        end_date="2026-01-31",
        include_ids=True,
    )
    assert result["transactions"][0]["transaction_id"] == "txn_1"


def test_plaid_remove_item_is_destructive() -> None:
    assert _is_destructive(PlaidToolSet.remove_item)


# MARK: - QuickBooks agent-ready


def test_quickbooks_list_customers_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = QuickBooksToolSet(access_token="qbo", realm_id="123", transport=transport)
    transport.enqueue(
        json_response(
            {
                "QueryResponse": {
                    "Customer": [
                        {
                            "Id": "1",
                            "SyncToken": "0",
                            "DisplayName": "Acme",
                            "CompanyName": "Acme Inc",
                            "PrimaryEmailAddr": {"Address": "ar@acme.test"},
                            "PrimaryPhone": {"FreeFormNumber": "555-1212"},
                            "Balance": 100.5,
                            "Active": True,
                            "CurrencyRef": {"value": "USD"},
                        }
                    ]
                }
            }
        )
    )
    result = connector.list_customers()
    summary = result["customers"][0]
    assert summary["customer_ref"] == "customer_1"
    assert summary["display_name"] == "Acme"
    assert summary["balance"] == "100.50 USD"
    assert "customer_id" not in summary
    assert "sync_token" not in summary


def test_quickbooks_list_invoices_include_ids_exposes_raw_id() -> None:
    transport = MockTransport()
    connector = QuickBooksToolSet(access_token="qbo", realm_id="123", transport=transport)
    transport.enqueue(
        json_response(
            {
                "QueryResponse": {
                    "Invoice": [
                        {
                            "Id": "10",
                            "SyncToken": "2",
                            "DocNumber": "INV-10",
                            "TotalAmt": 500.0,
                            "Balance": 0.0,
                            "TxnDate": "2026-01-01",
                            "DueDate": "2026-01-15",
                            "CustomerRef": {"value": "1", "name": "Acme"},
                            "CurrencyRef": {"value": "USD"},
                        }
                    ]
                }
            }
        )
    )
    result = connector.list_invoices(include_ids=True)
    summary = result["invoices"][0]
    assert summary["invoice_id"] == "10"
    assert summary["sync_token"] == "2"
    assert summary["customer_id"] == "1"
    assert summary["status"] == "paid"


def test_quickbooks_delete_entity_is_destructive() -> None:
    assert _is_destructive(QuickBooksToolSet.delete_entity)


# MARK: - Xero agent-ready


def test_xero_list_invoices_formats_money_and_hides_ids() -> None:
    transport = MockTransport()
    connector = XeroToolSet(access_token="xat", tenant_id="tnt", transport=transport)
    transport.enqueue(
        json_response(
            {
                "Invoices": [
                    {
                        "InvoiceID": "guid-1",
                        "InvoiceNumber": "INV-1",
                        "Type": "ACCREC",
                        "Total": 250.0,
                        "AmountDue": 250.0,
                        "AmountPaid": 0.0,
                        "CurrencyCode": "USD",
                        "Status": "AUTHORISED",
                        "DateString": "2026-01-01T00:00:00",
                        "DueDateString": "2026-01-15T00:00:00",
                        "Contact": {"ContactID": "c-1", "Name": "Acme"},
                    }
                ]
            }
        )
    )
    result = connector.list_invoices()
    summary = result["invoices"][0]
    assert summary["invoice_ref"] == "invoice_1"
    assert summary["total"] == "250.00 USD"
    assert summary["contact_name"] == "Acme"
    assert "invoice_id" not in summary


def test_xero_list_contacts_include_ids_exposes_raw_id() -> None:
    transport = MockTransport()
    connector = XeroToolSet(access_token="xat", tenant_id="tnt", transport=transport)
    transport.enqueue(
        json_response(
            {
                "Contacts": [
                    {"ContactID": "guid-1", "Name": "Acme", "EmailAddress": "x@y"},
                ]
            }
        )
    )
    result = connector.list_contacts(include_ids=True)
    assert result["contacts"][0]["contact_id"] == "guid-1"


# MARK: - NetSuite agent-ready


def test_netsuite_list_records_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = NetSuiteToolSet(account_id="123_TST", transport=transport)
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "id": "1",
                        "entityId": "C-001",
                        "companyName": "Acme",
                        "email": "x@y",
                    }
                ],
                "count": 1,
                "hasMore": False,
                "offset": 0,
            }
        )
    )
    result = connector.list_records("customer")
    summary = result["records"][0]
    assert summary["record_ref"] == "customer_1"
    assert summary["entityId"] == "C-001"
    assert summary["companyName"] == "Acme"
    assert "record_id" not in summary


def test_netsuite_list_records_include_ids_exposes_raw_id() -> None:
    transport = MockTransport()
    connector = NetSuiteToolSet(account_id="123_TST", transport=transport)
    transport.enqueue(json_response({"items": [{"id": "1", "entityId": "C-001"}]}))
    result = connector.list_records("customer", include_ids=True)
    assert result["records"][0]["record_id"] == "1"


def test_netsuite_delete_record_destructive_and_accepts_dict() -> None:
    transport = MockTransport()
    connector = NetSuiteToolSet(account_id="123_TST", transport=transport)
    transport.enqueue(json_response({}))
    assert _is_destructive(connector.delete_record)
    connector.delete_record("customer", {"record_id": "42"})
    assert "/services/rest/record/v1/customer/42" in transport.requests[0].url


# MARK: - Ramp agent-ready


def test_ramp_list_transactions_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = RampToolSet(access_token="r", transport=transport)
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "t1",
                        "card_id": "c1",
                        "merchant_name": "AWS",
                        "amount": 12.34,
                        "currency_code": "USD",
                        "user_transaction_time": "2026-01-01T00:00:00Z",
                        "card_holder": {"first_name": "Alice", "last_name": "Doe"},
                        "state": "CLEARED",
                        "sk_category_name": "Software",
                    }
                ],
                "page": {"next": "next-cursor"},
            }
        )
    )
    result = connector.list_transactions()
    summary = result["transactions"][0]
    assert summary["transaction_ref"] == "transaction_1"
    assert summary["amount"] == "12.34 USD"
    assert summary["merchant"] == "AWS"
    assert summary["card_holder"] == "Alice Doe"
    assert "transaction_id" not in summary


def test_ramp_terminate_card_destructive_and_accepts_dict() -> None:
    transport = MockTransport()
    connector = RampToolSet(access_token="r", transport=transport)
    transport.enqueue(json_response({}))
    assert _is_destructive(connector.terminate_card)
    connector.terminate_card({"card_id": "c-42"})
    assert "/developer/v1/cards/c-42/deferred/termination" in transport.requests[0].url


# MARK: - Brex agent-ready


def test_brex_list_expenses_formats_money_and_hides_ids() -> None:
    transport = MockTransport()
    connector = BrexToolSet(access_token="b", transport=transport)
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "id": "e1",
                        "card_id": "card-1",
                        "merchant": {"raw_descriptor": "STRIPE.COM"},
                        "original_amount": {"amount": 7500, "currency": "USD"},
                        "status": "SUBMITTED",
                        "category": "SOFTWARE",
                        "memo": "Subscription",
                        "purchased_at": "2026-01-01T00:00:00Z",
                    }
                ],
                "next_cursor": "n",
            }
        )
    )
    result = connector.list_expenses()
    summary = result["expenses"][0]
    assert summary["expense_ref"] == "expense_1"
    assert summary["amount"] == "75.00 USD"
    assert summary["merchant"] == "STRIPE.COM"
    assert "expense_id" not in summary


def test_brex_list_cards_include_ids_exposes_raw_id() -> None:
    transport = MockTransport()
    connector = BrexToolSet(access_token="b", transport=transport)
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "id": "card-1",
                        "last_four": "1234",
                        "card_type": "VIRTUAL",
                        "status": "ACTIVE",
                    }
                ]
            }
        )
    )
    result = connector.list_cards(include_ids=True)
    assert result["cards"][0]["card_id"] == "card-1"


def test_brex_terminate_card_destructive_and_accepts_dict() -> None:
    transport = MockTransport()
    connector = BrexToolSet(access_token="b", transport=transport)
    transport.enqueue(json_response({}))
    assert _is_destructive(connector.terminate_card)
    connector.terminate_card({"card_id": "card-99"})
    assert "/v2/cards/card-99/terminate" in transport.requests[0].url


# MARK: - Chargebee agent-ready


def test_chargebee_list_customers_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = ChargebeeToolSet(site="acme", api_key="cb", transport=transport)
    transport.enqueue(
        json_response(
            {
                "list": [
                    {
                        "customer": {
                            "id": "c-1",
                            "first_name": "Jane",
                            "last_name": "Doe",
                            "company": "Acme",
                            "email": "jane@example.test",
                            "phone": "555-1212",
                            "preferred_currency_code": "USD",
                        }
                    }
                ]
            }
        )
    )
    result = connector.list_customers(limit=5)
    summary = result["customers"][0]
    assert summary["customer_ref"] == "customer_1"
    assert summary["name"] == "Jane Doe"
    assert summary["currency"] == "USD"
    assert "customer_id" not in summary


def test_chargebee_cancel_subscription_destructive_and_accepts_dict() -> None:
    transport = MockTransport()
    connector = ChargebeeToolSet(site="acme", api_key="cb", transport=transport)
    transport.enqueue(json_response({}))
    assert _is_destructive(connector.cancel_subscription)
    connector.cancel_subscription({"subscription_id": "s-42"}, end_of_term=True)
    assert "/api/v2/subscriptions/s-42/cancel_for_items" in transport.requests[0].url


# MARK: - Recurly agent-ready


def test_recurly_list_subscriptions_formats_money_and_hides_ids() -> None:
    transport = MockTransport()
    connector = RecurlyToolSet(api_key="rk", transport=transport)
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "sub-1",
                        "plan": {"code": "pro", "name": "Pro"},
                        "state": "active",
                        "quantity": 1,
                        "unit_amount": 49.0,
                        "currency": "USD",
                        "current_period_started_at": "2026-01-01T00:00:00Z",
                        "current_period_ends_at": "2026-02-01T00:00:00Z",
                        "account": {"id": "acct-1", "code": "u1"},
                    }
                ]
            }
        )
    )
    result = connector.list_subscriptions()
    summary = result["subscriptions"][0]
    assert summary["subscription_ref"] == "subscription_1"
    assert summary["unit_amount"] == "49.00 USD"
    assert summary["plan_code"] == "pro"
    assert "subscription_id" not in summary
    assert "account_id" not in summary


def test_recurly_cancel_subscription_destructive_and_accepts_dict() -> None:
    transport = MockTransport()
    connector = RecurlyToolSet(api_key="rk", transport=transport)
    transport.enqueue(json_response({}))
    assert _is_destructive(connector.cancel_subscription)
    connector.cancel_subscription({"subscription_id": "sub-42"})
    assert "/subscriptions/sub-42/cancel" in transport.requests[0].url


# MARK: - Bill.com agent-ready


def test_billcom_list_bills_formats_money_and_hides_ids() -> None:
    transport = MockTransport()
    connector = BillToolSet(api_key="bk", dev_key="dk", transport=transport)
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "id": "b-1",
                        "vendorId": "v-1",
                        "invoiceNumber": "INV-1",
                        "amount": 100.0,
                        "balance": 100.0,
                        "currency": "USD",
                        "dueDate": "2026-01-15",
                        "invoiceDate": "2026-01-01",
                        "approvalStatus": "APPROVED",
                        "paymentStatus": "OPEN",
                    }
                ]
            }
        )
    )
    result = connector.list_bills()
    summary = result["bills"][0]
    assert summary["bill_ref"] == "bill_1"
    assert summary["amount"] == "100.00 USD"
    assert "bill_id" not in summary
    assert "vendor_id" not in summary


def test_billcom_list_payments_include_ids_exposes_raw_id() -> None:
    transport = MockTransport()
    connector = BillToolSet(api_key="bk", dev_key="dk", transport=transport)
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "id": "p-1",
                        "vendorId": "v-1",
                        "billId": "b-1",
                        "amount": 50.0,
                        "currency": "USD",
                        "status": "SENT",
                    }
                ]
            }
        )
    )
    result = connector.list_payments(include_ids=True)
    summary = result["payments"][0]
    assert summary["payment_id"] == "p-1"
    assert summary["bill_id"] == "b-1"


# MARK: - Toolset tag filtering


def test_stripe_toolset_read_tag_excludes_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    read_method_names: set[str] = set()
    destructive_method_names: set[str] = set()
    for name in dir(StripeToolSet):
        raw_method = getattr(StripeToolSet, name, None)
        if not callable(raw_method):
            continue
        opts = get_toolify_options(raw_method)
        if opts is None:
            continue
        if opts.destructive:
            destructive_method_names.add(name)
        if cast(PermissionSet, opts.permissions).includes(PermissionFlag.READ):
            read_method_names.add(name)
    assert "list_customers" in read_method_names
    assert "list_invoices" in read_method_names
    assert "refund_charge" in destructive_method_names
    assert "cancel_subscription" in destructive_method_names
    assert "delete_customer" in destructive_method_names
