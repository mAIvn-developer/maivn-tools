"""Tests for marketing / ads connectors.

Marketo, Iterable, Braze, Google Ads, Meta Ads, LinkedIn Ads, TikTok Ads.
"""

# pyright: strict

from __future__ import annotations

import pytest

from maivn_tools.connectors.braze import BrazeToolSet
from maivn_tools.connectors.google_ads import GoogleAdsToolSet
from maivn_tools.connectors.iterable import IterableToolSet
from maivn_tools.connectors.linkedin_ads import LinkedInAdsToolSet
from maivn_tools.connectors.marketo import MarketoToolSet
from maivn_tools.connectors.meta_ads import MetaAdsToolSet
from maivn_tools.connectors.tiktok_ads import TikTokAdsToolSet
from maivn_tools.testing import MockTransport, json_response

# MARK: - Marketo


def _marketo() -> tuple[MarketoToolSet, MockTransport]:
    transport = MockTransport()
    return (
        MarketoToolSet(
            munchkin_id="123-ABC-456",
            access_token="t",
            transport=transport,
        ),
        transport,
    )


def test_marketo_requires_args() -> None:
    with pytest.raises(ValueError):
        MarketoToolSet(munchkin_id="", access_token="t")
    with pytest.raises(ValueError):
        MarketoToolSet(munchkin_id="m", access_token="")


def test_marketo_endpoints() -> None:
    connector, transport = _marketo()
    for _ in range(10):
        transport.enqueue(json_response({"result": []}))
    connector.get_lead_by_filter(
        filter_type="email",
        filter_values=["a@b"],
        fields=["id"],
        batch_size=10,
        next_page_token="np",
    )
    connector.create_or_update_leads(
        action="createOrUpdate",
        input=[{"email": "a@b"}],
        lookup_field="email",
    )
    connector.delete_leads([1, 2])
    connector.list_programs(
        max_return=10,
        offset=0,
        status="on",
    )
    connector.list_campaigns(
        program_name="P",
        is_trigger=True,
        batch_size=10,
        next_page_token="np",
    )
    connector.trigger_campaign(
        1,
        input=[{"id": 1}],
        tokens=[{"name": "T"}],
    )
    connector.list_static_lists(batch_size=10, next_page_token="np")
    connector.add_leads_to_list(1, input=[{"id": 1}])
    connector.remove_leads_from_list(1, input=[{"id": 1}])
    connector.create_bulk_lead_export(
        fields=["email"],
        filter={"createdAt": {}},
        format="CSV",
    )
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert transport.requests[8].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_lead_by_filter(filter_type="", filter_values=["x"])
    with pytest.raises(ValueError):
        connector.get_lead_by_filter(filter_type="email", filter_values=[])
    with pytest.raises(ValueError):
        connector.create_or_update_leads(action="", input=[{"x": 1}])
    with pytest.raises(ValueError):
        connector.create_or_update_leads(action="bogus", input=[{"x": 1}])
    with pytest.raises(ValueError):
        connector.delete_leads([])
    with pytest.raises(ValueError):
        connector.trigger_campaign(0, input=[{"x": 1}])
    with pytest.raises(ValueError):
        connector.trigger_campaign(1, input=[])
    with pytest.raises(ValueError):
        connector.add_leads_to_list(0, input=[{"x": 1}])
    with pytest.raises(ValueError):
        connector.add_leads_to_list(1, input=[])
    with pytest.raises(ValueError):
        connector.remove_leads_from_list(0, input=[{"x": 1}])
    with pytest.raises(ValueError):
        connector.create_bulk_lead_export(fields=[], filter={"x": 1})


# MARK: - Iterable


def _iterable() -> tuple[IterableToolSet, MockTransport]:
    transport = MockTransport()
    return IterableToolSet(api_key="k", transport=transport), transport


def test_iterable_requires_key() -> None:
    with pytest.raises(ValueError):
        IterableToolSet(api_key="")


def test_iterable_endpoints() -> None:
    connector, transport = _iterable()
    for _ in range(10):
        transport.enqueue(json_response({"data": {}}))
    connector.update_user(
        email="a@b",
        user_id="u",
        data_fields={"k": "v"},
        prefer_user_id=True,
        merge_nested_objects=True,
    )
    connector.get_user(email="a@b")
    connector.delete_user("a@b")
    connector.track_event(
        email="a@b",
        event_name="signed_up",
        data_fields={"k": "v"},
        created_at=100,
    )
    connector.track_purchase(
        user={"email": "a@b"},
        items=[{"id": "1"}],
        total=10.0,
        created_at=100,
        data_fields={"k": "v"},
    )
    connector.list_lists()
    connector.add_subscribers(
        list_id=1,
        subscribers=[{"email": "a@b"}],
    )
    connector.remove_subscribers(
        list_id=1,
        subscribers=[{"email": "a@b"}],
    )
    connector.list_campaigns()
    connector.list_templates(template_type="Standard", message_medium="Email")
    assert transport.requests[0].headers["Api-Key"] == "k"
    assert transport.requests[2].method == "DELETE"
    with pytest.raises(ValueError):
        connector.update_user()
    with pytest.raises(ValueError):
        connector.get_user(email="")
    with pytest.raises(ValueError):
        connector.delete_user("")
    with pytest.raises(ValueError):
        connector.track_event(event_name="")
    with pytest.raises(ValueError):
        connector.track_event(event_name="x")
    with pytest.raises(ValueError):
        connector.track_purchase(user={}, items=[{"x": 1}], total=10.0)
    with pytest.raises(ValueError):
        connector.add_subscribers(list_id=0, subscribers=[{"x": 1}])
    with pytest.raises(ValueError):
        connector.add_subscribers(list_id=1, subscribers=[])
    with pytest.raises(ValueError):
        connector.remove_subscribers(list_id=0, subscribers=[{"x": 1}])


# MARK: - Braze


def _braze() -> tuple[BrazeToolSet, MockTransport]:
    transport = MockTransport()
    return (
        BrazeToolSet(
            rest_endpoint="https://rest.iad-01.braze.com",
            api_key="k",
            transport=transport,
        ),
        transport,
    )


def test_braze_requires_args() -> None:
    with pytest.raises(ValueError):
        BrazeToolSet(rest_endpoint="", api_key="k")
    with pytest.raises(ValueError):
        BrazeToolSet(rest_endpoint="u", api_key="")


def test_braze_endpoints() -> None:
    connector, transport = _braze()
    for _ in range(10):
        transport.enqueue(json_response({"message": "success"}))
    connector.track_users(
        attributes=[{"external_id": "u", "k": "v"}],
        events=[{"name": "x", "external_id": "u"}],
        purchases=[{"external_id": "u", "product_id": "p", "currency": "USD", "price": 1}],
    )
    connector.export_user_ids(
        external_ids=["u"],
        fields_to_export=["email"],
    )
    connector.delete_users(external_ids=["u"])
    connector.send_messages(
        external_user_ids=["u"],
        messages={"email": {"subject": "Hi"}},
    )
    connector.trigger_campaign(
        campaign_id="c1",
        recipients=[{"external_user_id": "u"}],
        broadcast=False,
        trigger_properties={"k": "v"},
    )
    connector.trigger_canvas(
        canvas_id="cv1",
        recipients=[{"external_user_id": "u"}],
        broadcast=False,
        canvas_entry_properties={"k": "v"},
    )
    connector.list_campaigns(page=0, include_archived=False, sort_direction="desc")
    connector.list_canvases(page=0, include_archived=False, sort_direction="desc")
    connector.subscribe_users(
        subscription_group_id="g1",
        subscription_state="subscribed",
        external_ids=["u"],
    )
    connector.export_segment(
        segment_id="s1",
        fields_to_export=["email"],
    )
    assert transport.requests[0].headers["Authorization"] == "Bearer k"
    with pytest.raises(ValueError):
        connector.track_users()
    with pytest.raises(ValueError):
        connector.export_user_ids()
    with pytest.raises(ValueError):
        connector.delete_users()
    with pytest.raises(ValueError):
        connector.send_messages()
    with pytest.raises(ValueError):
        connector.send_messages(external_user_ids=["u"])
    with pytest.raises(ValueError):
        connector.trigger_campaign(campaign_id="")
    with pytest.raises(ValueError):
        connector.trigger_canvas(canvas_id="")
    with pytest.raises(ValueError):
        connector.subscribe_users(
            subscription_group_id="",
            subscription_state="subscribed",
        )
    with pytest.raises(ValueError):
        connector.subscribe_users(
            subscription_group_id="g",
            subscription_state="bogus",
        )
    with pytest.raises(ValueError):
        connector.export_segment(segment_id="", fields_to_export=["x"])


# MARK: - Google Ads


def _google_ads() -> tuple[GoogleAdsToolSet, MockTransport]:
    transport = MockTransport()
    return (
        GoogleAdsToolSet(
            access_token="at",
            developer_token="dt",
            login_customer_id="111-222-3333",
            transport=transport,
        ),
        transport,
    )


def test_google_ads_requires_args() -> None:
    with pytest.raises(ValueError):
        GoogleAdsToolSet(access_token="", developer_token="d")
    with pytest.raises(ValueError):
        GoogleAdsToolSet(access_token="a", developer_token="")


def test_google_ads_endpoints() -> None:
    connector, transport = _google_ads()
    for _ in range(8):
        transport.enqueue(json_response({"results": []}))
    connector.list_accessible_customers()
    connector.search(
        customer_id="1",
        query="SELECT campaign.id FROM campaign",
        page_size=10,
        page_token="pt",
    )
    connector.search_stream(
        customer_id="1",
        query="SELECT campaign.id FROM campaign",
    )
    connector.mutate_campaigns(
        customer_id="1",
        operations=[{"create": {"name": "C"}}],
        partial_failure=True,
        validate_only=False,
    )
    connector.mutate_ad_groups(
        customer_id="1",
        operations=[{"create": {"name": "AG"}}],
    )
    connector.mutate_ad_group_ads(
        customer_id="1",
        operations=[{"create": {"final_urls": ["https://x"]}}],
    )
    connector.upload_click_conversions(
        customer_id="1",
        conversions=[{"conversion_action": "x"}],
    )
    connector.upload_offline_user_data(
        customer_id="1",
        operations=[{"create": {}}],
    )
    headers = transport.requests[0].headers
    assert headers["Authorization"] == "Bearer at"
    assert headers["developer-token"] == "dt"
    assert headers["login-customer-id"] == "111-222-3333"
    with pytest.raises(ValueError):
        connector.search(customer_id="", query="x")
    with pytest.raises(ValueError):
        connector.search(customer_id="1", query="")
    with pytest.raises(ValueError):
        connector.search_stream(customer_id="", query="x")
    with pytest.raises(ValueError):
        connector.mutate_campaigns(customer_id="", operations=[{"x": 1}])
    with pytest.raises(ValueError):
        connector.mutate_campaigns(customer_id="1", operations=[])
    with pytest.raises(ValueError):
        connector.upload_click_conversions(customer_id="1", conversions=[])


def test_google_ads_mutate_budgets() -> None:
    connector, transport = _google_ads()
    transport.enqueue(json_response({"results": []}))
    connector.mutate_campaign_budgets(
        customer_id="1",
        operations=[{"create": {"amount_micros": 1000000}}],
    )
    with pytest.raises(ValueError):
        connector.mutate_campaign_budgets(customer_id="", operations=[{"x": 1}])


# MARK: - Meta Ads


def _meta_ads() -> tuple[MetaAdsToolSet, MockTransport]:
    transport = MockTransport()
    return MetaAdsToolSet(access_token="t", transport=transport), transport


def test_meta_ads_requires_token() -> None:
    with pytest.raises(ValueError):
        MetaAdsToolSet(access_token="")


def test_meta_ads_endpoints() -> None:
    connector, transport = _meta_ads()
    for _ in range(10):
        transport.enqueue(json_response({"data": []}))
    connector.list_ad_accounts(fields=["name"], limit=10)
    connector.get_ad_account("act_1", fields=["name"])
    connector.list_campaigns(
        "act_1",
        fields=["name"],
        limit=10,
        effective_status=["ACTIVE"],
    )
    connector.create_campaign(
        "act_1",
        name="C",
        objective="OUTCOME_TRAFFIC",
        status="PAUSED",
        special_ad_categories=["NONE"],
        daily_budget=1000,
        lifetime_budget=None,
    )
    connector.update_campaign("c1", fields={"name": "C2"})
    connector.delete_campaign("c1")
    connector.list_ad_sets("act_1", fields=["name"], limit=10)
    connector.list_ads("act_1", fields=["name"], limit=10)
    connector.get_insights(
        "act_1",
        level="account",
        fields=["impressions"],
        time_range={"since": "2026-01-01", "until": "2026-01-31"},
        breakdowns=["age"],
        limit=10,
    )
    connector.list_custom_audiences("act_1", fields=["name"], limit=10)
    assert transport.requests[0].params["access_token"] == "t"
    assert transport.requests[5].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_ad_account("")
    with pytest.raises(ValueError):
        connector.list_campaigns("")
    with pytest.raises(ValueError):
        connector.create_campaign("", name="C", objective="X")
    with pytest.raises(ValueError):
        connector.create_campaign("a", name="", objective="X")
    with pytest.raises(ValueError):
        connector.create_campaign("a", name="C", objective="X", status="bogus")
    with pytest.raises(ValueError):
        connector.update_campaign("", fields={"x": 1})
    with pytest.raises(ValueError):
        connector.update_campaign("c", fields={})
    with pytest.raises(ValueError):
        connector.delete_campaign("")
    with pytest.raises(ValueError):
        connector.list_ad_sets("")
    with pytest.raises(ValueError):
        connector.list_ads("")
    with pytest.raises(ValueError):
        connector.get_insights("")
    with pytest.raises(ValueError):
        connector.get_insights("a", level="bogus")
    with pytest.raises(ValueError):
        connector.list_custom_audiences("")


# MARK: - LinkedIn Ads


def _linkedin_ads() -> tuple[LinkedInAdsToolSet, MockTransport]:
    transport = MockTransport()
    return (
        LinkedInAdsToolSet(access_token="t", transport=transport),
        transport,
    )


def test_linkedin_ads_requires_token() -> None:
    with pytest.raises(ValueError):
        LinkedInAdsToolSet(access_token="")


def test_linkedin_ads_endpoints() -> None:
    connector, transport = _linkedin_ads()
    for _ in range(9):
        transport.enqueue(json_response({"elements": []}))
    connector.list_ad_accounts(
        q="search",
        search={"status": ["ACTIVE"]},
        count=10,
        start=0,
    )
    connector.get_ad_account(1)
    connector.list_campaigns(1, page_size=10, page_token="pt")
    connector.get_campaign(ad_account_id=1, campaign_id=2)
    connector.update_campaign(
        ad_account_id=1,
        campaign_id=2,
        patch={"status": "PAUSED"},
    )
    connector.list_creatives(1, page_size=10, page_token="pt")
    connector.ad_analytics(
        pivot="CAMPAIGN",
        date_range={
            "start": {"year": 2026, "month": 1, "day": 1},
            "end": {"year": 2026, "month": 1, "day": 31},
        },
        time_granularity="DAILY",
        accounts=["urn:li:sponsoredAccount:1"],
        campaigns=["urn:li:sponsoredCampaign:2"],
        creatives=["urn:li:sponsoredCreative:3"],
        fields=["impressions"],
    )
    connector.list_dmp_segments(account="urn:li:sponsoredAccount:1")
    connector.add_users_to_dmp_segment(
        segment_id="seg1",
        users=[{"action": "ADD"}],
    )
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    with pytest.raises(ValueError):
        connector.get_ad_account(0)
    with pytest.raises(ValueError):
        connector.list_campaigns(0)
    with pytest.raises(ValueError):
        connector.get_campaign(ad_account_id=0, campaign_id=1)
    with pytest.raises(ValueError):
        connector.update_campaign(ad_account_id=0, campaign_id=1, patch={"x": 1})
    with pytest.raises(ValueError):
        connector.list_creatives(0)
    with pytest.raises(ValueError):
        connector.ad_analytics(pivot="", date_range={"start": {"year": 1}})
    with pytest.raises(ValueError):
        connector.ad_analytics(pivot="bogus", date_range={"start": {"year": 1}})
    with pytest.raises(ValueError):
        connector.list_dmp_segments(account="")
    with pytest.raises(ValueError):
        connector.add_users_to_dmp_segment(segment_id="", users=[{"x": 1}])


# MARK: - TikTok Ads


def _tiktok_ads() -> tuple[TikTokAdsToolSet, MockTransport]:
    transport = MockTransport()
    return (
        TikTokAdsToolSet(access_token="t", transport=transport),
        transport,
    )


def test_tiktok_ads_requires_token() -> None:
    with pytest.raises(ValueError):
        TikTokAdsToolSet(access_token="")


def test_tiktok_ads_endpoints() -> None:
    connector, transport = _tiktok_ads()
    for _ in range(10):
        transport.enqueue(json_response({"data": {}}))
    connector.list_advertisers(app_id="a", secret="s")
    connector.get_advertiser_info(advertiser_ids=["1"])
    connector.list_campaigns(
        advertiser_id="1",
        filtering={"campaign_status": "ACTIVE"},
        page=1,
        page_size=10,
    )
    connector.create_campaign(
        advertiser_id="1",
        campaign_name="C",
        objective_type="TRAFFIC",
        budget_mode="BUDGET_MODE_DAY",
        budget=100.0,
    )
    connector.update_campaign(
        advertiser_id="1",
        campaign_id="c1",
        fields={"name": "C2"},
    )
    connector.update_campaign_status(
        advertiser_id="1",
        campaign_ids=["c1"],
        operation_status="DISABLE",
    )
    connector.list_ad_groups(
        advertiser_id="1",
        filtering={"x": 1},
        page=1,
        page_size=10,
    )
    connector.list_ads(
        advertiser_id="1",
        filtering={"x": 1},
        page=1,
        page_size=10,
    )
    connector.get_reports(
        advertiser_id="1",
        report_type="BASIC",
        data_level="AUCTION_CAMPAIGN",
        dimensions=["campaign_id"],
        metrics=["impressions"],
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    connector.list_audiences(advertiser_id="1", page=1, page_size=10)
    assert transport.requests[0].headers["Access-Token"] == "t"
    with pytest.raises(ValueError):
        connector.list_advertisers(app_id="", secret="s")
    with pytest.raises(ValueError):
        connector.get_advertiser_info(advertiser_ids=[])
    with pytest.raises(ValueError):
        connector.list_campaigns(advertiser_id="")
    with pytest.raises(ValueError):
        connector.create_campaign(
            advertiser_id="",
            campaign_name="c",
            objective_type="x",
        )
    with pytest.raises(ValueError):
        connector.update_campaign(
            advertiser_id="",
            campaign_id="c",
            fields={"x": 1},
        )
    with pytest.raises(ValueError):
        connector.update_campaign_status(
            advertiser_id="1",
            campaign_ids=["c"],
            operation_status="bogus",
        )
    with pytest.raises(ValueError):
        connector.list_ad_groups(advertiser_id="")
    with pytest.raises(ValueError):
        connector.list_ads(advertiser_id="")
    with pytest.raises(ValueError):
        connector.get_reports(
            advertiser_id="",
            report_type="b",
            data_level="d",
            dimensions=["x"],
            metrics=["y"],
            start_date="a",
            end_date="b",
        )
    with pytest.raises(ValueError):
        connector.list_audiences(advertiser_id="")


# MARK: - Agent-ready summary defaults


def test_marketo_list_campaigns_returns_summaries_without_ids() -> None:
    connector, transport = _marketo()
    transport.enqueue(
        json_response(
            {
                "result": [
                    {
                        "id": 101,
                        "name": "Spring Onboarding",
                        "programName": "Onboarding",
                        "type": "batch",
                        "active": True,
                        "workspaceName": "Default",
                        "createdAt": "2026-01-01",
                        "updatedAt": "2026-02-01",
                        "programId": 22,
                    }
                ],
                "nextPageToken": "np",
                "moreResult": False,
            }
        )
    )
    result = connector.list_campaigns()
    assert result["campaigns"] == [
        {
            "campaign_ref": "campaign_1",
            "name": "Spring Onboarding",
            "program_name": "Onboarding",
            "type": "batch",
            "active": True,
            "workspace_name": "Default",
            "created_at": "2026-01-01",
            "updated_at": "2026-02-01",
        }
    ]
    assert result["next_page_token"] == "np"
    assert "campaign_id" not in result["campaigns"][0]


def test_marketo_list_campaigns_include_ids() -> None:
    connector, transport = _marketo()
    transport.enqueue(
        json_response(
            {
                "result": [
                    {
                        "id": 101,
                        "name": "Spring",
                        "programId": 22,
                    }
                ],
            }
        )
    )
    result = connector.list_campaigns(include_ids=True)
    assert result["campaigns"][0]["campaign_id"] == 101
    assert result["campaigns"][0]["program_id"] == 22


def test_marketo_list_static_lists_returns_summaries() -> None:
    connector, transport = _marketo()
    transport.enqueue(
        json_response(
            {
                "result": [
                    {
                        "id": 9,
                        "name": "VIPs",
                        "programName": "Loyalty",
                        "workspaceName": "Default",
                        "createdAt": "2026-01-01",
                        "updatedAt": "2026-02-01",
                    }
                ]
            }
        )
    )
    result = connector.list_static_lists()
    assert result["lists"][0]["list_ref"] == "list_1"
    assert result["lists"][0]["name"] == "VIPs"
    assert "list_id" not in result["lists"][0]


def test_marketo_trigger_campaign_accepts_dict() -> None:
    connector, transport = _marketo()
    transport.enqueue(json_response({"success": True}))
    connector.trigger_campaign(
        {"campaign_id": 555, "campaign_ref": "campaign_1"},
        input=[{"id": 1}],
    )
    assert transport.requests[-1].url.endswith("/rest/v1/campaigns/555/trigger.json")


def test_marketo_add_leads_accepts_dict_list_id() -> None:
    connector, transport = _marketo()
    transport.enqueue(json_response({"success": True}))
    connector.add_leads_to_list(
        {"list_id": 9, "list_ref": "list_1"},
        input=[{"id": 1}],
    )
    assert transport.requests[-1].url.endswith("/rest/v1/lists/9/leads.json")


def test_marketo_destructive_tools_tagged() -> None:
    for name in ("delete_leads", "remove_leads_from_list"):
        method = getattr(MarketoToolSet, name)
        meta = getattr(method, "__maivn_toolify__", None)
        assert meta is not None
        assert getattr(meta, "destructive", False) is True


def test_iterable_list_campaigns_returns_summaries() -> None:
    connector, transport = _iterable()
    transport.enqueue(
        json_response(
            {
                "campaigns": [
                    {
                        "id": 17,
                        "name": "Newsletter",
                        "campaignState": "Running",
                        "messageMedium": "Email",
                        "sendSize": 12000,
                        "createdAt": 1700000000,
                        "updatedAt": 1700001000,
                        "templateId": 99,
                    }
                ]
            }
        )
    )
    result = connector.list_campaigns()
    assert result["campaigns"][0]["campaign_ref"] == "campaign_1"
    assert result["campaigns"][0]["name"] == "Newsletter"
    assert "campaign_id" not in result["campaigns"][0]

    transport.enqueue(
        json_response(
            {
                "campaigns": [
                    {"id": 17, "name": "Newsletter", "templateId": 99},
                ]
            }
        )
    )
    result = connector.list_campaigns(include_ids=True)
    assert result["campaigns"][0]["campaign_id"] == 17
    assert result["campaigns"][0]["template_id"] == 99


def test_iterable_list_lists_returns_summaries() -> None:
    connector, transport = _iterable()
    transport.enqueue(
        json_response(
            {"lists": [{"id": 4, "name": "VIP", "listType": "Standard", "createdAt": 1700000000}]}
        )
    )
    result = connector.list_lists()
    assert result["lists"][0]["list_ref"] == "list_1"
    assert result["lists"][0]["name"] == "VIP"
    assert "list_id" not in result["lists"][0]


def test_iterable_add_subscribers_accepts_dict_list_id() -> None:
    connector, transport = _iterable()
    transport.enqueue(json_response({"successCount": 1}))
    connector.add_subscribers(
        list_id={"list_id": 7, "list_ref": "list_1"},
        subscribers=[{"email": "a@b"}],
    )
    body = transport.requests[-1].json_body
    assert body["listId"] == 7


def test_iterable_destructive_tools_tagged() -> None:
    for name in ("delete_user", "remove_subscribers"):
        method = getattr(IterableToolSet, name)
        meta = getattr(method, "__maivn_toolify__", None)
        assert meta is not None
        assert getattr(meta, "destructive", False) is True


def test_braze_list_campaigns_returns_summaries() -> None:
    connector, transport = _braze()
    transport.enqueue(
        json_response(
            {
                "campaigns": [
                    {
                        "id": "c1-abc",
                        "name": "Spring Send",
                        "is_api_campaign": False,
                        "tags": ["promo"],
                        "last_edited": "2026-04-01T00:00:00Z",
                    }
                ],
                "message": "success",
            }
        )
    )
    result = connector.list_campaigns()
    assert result["campaigns"][0]["campaign_ref"] == "campaign_1"
    assert result["campaigns"][0]["name"] == "Spring Send"
    assert "campaign_id" not in result["campaigns"][0]

    transport.enqueue(
        json_response(
            {"campaigns": [{"id": "c1-abc", "name": "Spring Send"}], "message": "success"}
        )
    )
    result = connector.list_campaigns(include_ids=True)
    assert result["campaigns"][0]["campaign_id"] == "c1-abc"


def test_braze_list_canvases_returns_summaries() -> None:
    connector, transport = _braze()
    transport.enqueue(
        json_response(
            {
                "canvases": [
                    {
                        "id": "cv1",
                        "name": "Onboarding journey",
                        "tags": [],
                        "last_edited": "2026-04-01T00:00:00Z",
                    }
                ],
                "message": "success",
            }
        )
    )
    result = connector.list_canvases()
    assert result["canvases"][0]["canvas_ref"] == "canvas_1"
    assert "canvas_id" not in result["canvases"][0]


def test_braze_trigger_campaign_accepts_dict() -> None:
    connector, transport = _braze()
    transport.enqueue(json_response({"message": "success"}))
    connector.trigger_campaign(
        campaign_id={"campaign_id": "abc", "campaign_ref": "campaign_1"},
        recipients=[{"external_user_id": "u"}],
    )
    body = transport.requests[-1].json_body
    assert body["campaign_id"] == "abc"


def test_braze_destructive_tools_tagged() -> None:
    method = BrazeToolSet.delete_users
    meta = getattr(method, "__maivn_toolify__", None)
    assert meta is not None
    assert getattr(meta, "destructive", False) is True


def test_meta_ads_list_campaigns_returns_summaries() -> None:
    connector, transport = _meta_ads()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "1234",
                        "name": "Q2 Push",
                        "status": "ACTIVE",
                        "effective_status": "ACTIVE",
                        "objective": "OUTCOME_TRAFFIC",
                        "daily_budget": "5000",
                    }
                ],
                "paging": {"cursors": {"after": "x"}},
            }
        )
    )
    result = connector.list_campaigns("act_1")
    assert result["campaigns"][0]["campaign_ref"] == "campaign_1"
    assert result["campaigns"][0]["name"] == "Q2 Push"
    assert "campaign_id" not in result["campaigns"][0]
    assert result["paging"]["cursors"]["after"] == "x"

    transport.enqueue(json_response({"data": [{"id": "1234", "name": "Q2 Push"}]}))
    result = connector.list_campaigns("act_1", include_ids=True)
    assert result["campaigns"][0]["campaign_id"] == "1234"


def test_meta_ads_list_ads_returns_summaries() -> None:
    connector, transport = _meta_ads()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "ad-1",
                        "name": "Hero ad",
                        "status": "ACTIVE",
                        "effective_status": "ACTIVE",
                    }
                ]
            }
        )
    )
    result = connector.list_ads("act_1")
    assert result["ads"][0]["ad_ref"] == "ad_1"
    assert "ad_id" not in result["ads"][0]


def test_meta_ads_list_custom_audiences_returns_summaries() -> None:
    connector, transport = _meta_ads()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "aud-1",
                        "name": "Lookalike 1%",
                        "subtype": "LOOKALIKE",
                        "approximate_count": 50000,
                    }
                ]
            }
        )
    )
    result = connector.list_custom_audiences("act_1")
    assert result["audiences"][0]["audience_ref"] == "audience_1"
    assert result["audiences"][0]["name"] == "Lookalike 1%"
    assert "audience_id" not in result["audiences"][0]


def test_meta_ads_update_campaign_accepts_dict() -> None:
    connector, transport = _meta_ads()
    transport.enqueue(json_response({"success": True}))
    connector.update_campaign(
        {"campaign_id": "1234", "campaign_ref": "campaign_1"},
        fields={"status": "PAUSED"},
    )
    assert transport.requests[-1].url.endswith("/1234")


def test_meta_ads_destructive_tools_tagged() -> None:
    method = MetaAdsToolSet.delete_campaign
    meta = getattr(method, "__maivn_toolify__", None)
    assert meta is not None
    assert getattr(meta, "destructive", False) is True


def test_linkedin_ads_list_campaigns_returns_summaries() -> None:
    connector, transport = _linkedin_ads()
    transport.enqueue(
        json_response(
            {
                "elements": [
                    {
                        "id": 555,
                        "name": "Q3 Awareness",
                        "status": "ACTIVE",
                        "type": "SPONSORED_UPDATES",
                        "costType": "CPM",
                        "dailyBudget": {"amount": "100", "currencyCode": "USD"},
                    }
                ],
                "paging": {"start": 0, "count": 10},
            }
        )
    )
    result = connector.list_campaigns(1)
    assert result["campaigns"][0]["campaign_ref"] == "campaign_1"
    assert result["campaigns"][0]["name"] == "Q3 Awareness"
    assert "campaign_id" not in result["campaigns"][0]

    transport.enqueue(json_response({"elements": [{"id": 555, "name": "Q3 Awareness"}]}))
    result = connector.list_campaigns(1, include_ids=True)
    assert result["campaigns"][0]["campaign_id"] == 555


def test_linkedin_ads_list_ad_accounts_returns_summaries() -> None:
    connector, transport = _linkedin_ads()
    transport.enqueue(
        json_response(
            {
                "elements": [
                    {
                        "id": 12,
                        "name": "Acme Ads",
                        "status": "ACTIVE",
                        "type": "BUSINESS",
                        "currency": "USD",
                        "reference": "urn:li:organization:1",
                    }
                ]
            }
        )
    )
    result = connector.list_ad_accounts()
    assert result["accounts"][0]["account_ref"] == "account_1"
    assert result["accounts"][0]["name"] == "Acme Ads"
    assert "ad_account_id" not in result["accounts"][0]


def test_linkedin_ads_list_dmp_segments_returns_summaries() -> None:
    connector, transport = _linkedin_ads()
    transport.enqueue(
        json_response(
            {
                "elements": [
                    {
                        "id": "seg-1",
                        "name": "Retargeting",
                        "description": "30-day list",
                        "status": "READY",
                        "type": "USER",
                        "audienceSizeLowerBound": 1000,
                        "audienceSizeUpperBound": 5000,
                    }
                ]
            }
        )
    )
    result = connector.list_dmp_segments(account="urn:li:sponsoredAccount:1")
    assert result["segments"][0]["segment_ref"] == "segment_1"
    assert "segment_id" not in result["segments"][0]


def test_linkedin_ads_get_ad_account_accepts_dict() -> None:
    connector, transport = _linkedin_ads()
    transport.enqueue(json_response({"id": 7}))
    connector.get_ad_account({"ad_account_id": 7, "account_ref": "account_1"})
    assert transport.requests[-1].url.endswith("/rest/adAccounts/7")


def test_tiktok_ads_list_campaigns_returns_summaries() -> None:
    connector, transport = _tiktok_ads()
    transport.enqueue(
        json_response(
            {
                "code": 0,
                "message": "OK",
                "data": {
                    "list": [
                        {
                            "campaign_id": "1234567890",
                            "campaign_name": "Boost Q4",
                            "operation_status": "ENABLE",
                            "status": "CAMPAIGN_STATUS_DELIVERY_OK",
                            "budget_mode": "BUDGET_MODE_DAY",
                            "budget": 250.0,
                            "objective_type": "TRAFFIC",
                            "create_time": "2026-01-01 00:00:00",
                            "modify_time": "2026-01-02 00:00:00",
                            "advertiser_id": "adv1",
                        }
                    ],
                    "page_info": {"page": 1, "page_size": 10, "total_number": 1},
                },
            }
        )
    )
    result = connector.list_campaigns(advertiser_id="adv1")
    assert result["campaigns"][0]["campaign_ref"] == "campaign_1"
    assert result["campaigns"][0]["campaign_name"] == "Boost Q4"
    assert "campaign_id" not in result["campaigns"][0]
    assert result["page_info"]["page"] == 1

    transport.enqueue(
        json_response(
            {
                "code": 0,
                "data": {
                    "list": [{"campaign_id": "1234567890", "campaign_name": "Boost Q4"}],
                },
            }
        )
    )
    result = connector.list_campaigns(advertiser_id="adv1", include_ids=True)
    assert result["campaigns"][0]["campaign_id"] == "1234567890"


def test_tiktok_ads_list_ads_returns_summaries() -> None:
    connector, transport = _tiktok_ads()
    transport.enqueue(
        json_response(
            {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "ad_id": "ad-1",
                            "ad_name": "Hero",
                            "status": "AD_STATUS_DELIVERY_OK",
                            "operation_status": "ENABLE",
                            "ad_format": "SINGLE_VIDEO",
                        }
                    ],
                    "page_info": {"page": 1, "page_size": 10},
                },
            }
        )
    )
    result = connector.list_ads(advertiser_id="adv1")
    assert result["ads"][0]["ad_ref"] == "ad_1"
    assert "ad_id" not in result["ads"][0]


def test_tiktok_ads_list_audiences_returns_summaries() -> None:
    connector, transport = _tiktok_ads()
    transport.enqueue(
        json_response(
            {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "audience_id": "aud-1",
                            "audience_name": "Customers 2024",
                            "audience_type": "CUSTOMER_FILE",
                            "audience_subtype": "EMAIL",
                            "cover_num": 10000,
                            "create_time": "2026-01-01",
                            "calculate_type": "AUTO",
                        }
                    ],
                    "page_info": {"page": 1, "page_size": 10},
                },
            }
        )
    )
    result = connector.list_audiences(advertiser_id="adv1")
    assert result["audiences"][0]["audience_ref"] == "audience_1"
    assert result["audiences"][0]["audience_name"] == "Customers 2024"
    assert "audience_id" not in result["audiences"][0]


def test_tiktok_ads_update_campaign_accepts_dict() -> None:
    connector, transport = _tiktok_ads()
    transport.enqueue(json_response({"code": 0}))
    connector.update_campaign(
        advertiser_id="adv1",
        campaign_id={"campaign_id": "987", "campaign_ref": "campaign_1"},
        fields={"campaign_name": "Renamed"},
    )
    body = transport.requests[-1].json_body
    assert body["campaign_id"] == "987"


def test_tiktok_ads_update_status_accepts_dict_ids() -> None:
    connector, transport = _tiktok_ads()
    transport.enqueue(json_response({"code": 0}))
    connector.update_campaign_status(
        advertiser_id="adv1",
        campaign_ids=[{"campaign_id": "987", "campaign_ref": "campaign_1"}],
        operation_status="DISABLE",
    )
    body = transport.requests[-1].json_body
    assert body["campaign_ids"] == ["987"]


def test_google_ads_search_accepts_dict_customer_id() -> None:
    connector, transport = _google_ads()
    transport.enqueue(json_response({"results": []}))
    connector.search(
        customer_id={"resourceName": "customers/1234567890"},
        query="SELECT campaign.id FROM campaign",
    )
    assert transport.requests[-1].url.endswith("/v24/customers/1234567890/googleAds:search")


def test_google_ads_search_strips_dashes_from_customer_id() -> None:
    connector, transport = _google_ads()
    transport.enqueue(json_response({"results": []}))
    connector.search(customer_id="123-456-7890", query="SELECT campaign.id FROM campaign")
    assert "/v24/customers/1234567890/" in transport.requests[-1].url
