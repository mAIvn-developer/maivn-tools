"""Tests for analytics / BI connectors.

Amplitude, Mixpanel, Segment, PostHog, Looker, Tableau, Metabase, Hex, Sigma.
"""

# pyright: strict

from __future__ import annotations

import pytest

from maivn_tools.connectors.amplitude import AmplitudeToolSet
from maivn_tools.connectors.hex import HexToolSet
from maivn_tools.connectors.looker import LookerToolSet
from maivn_tools.connectors.metabase import MetabaseToolSet
from maivn_tools.connectors.mixpanel import MixpanelToolSet
from maivn_tools.connectors.posthog import PostHogToolSet
from maivn_tools.connectors.segment import SegmentToolSet
from maivn_tools.connectors.sigma import SigmaToolSet
from maivn_tools.connectors.tableau import TableauToolSet
from maivn_tools.testing import MockTransport, json_response

# MARK: - Amplitude


def _amplitude() -> tuple[AmplitudeToolSet, MockTransport]:
    transport = MockTransport()
    return (
        AmplitudeToolSet(api_key="k", secret_key="s", transport=transport),
        transport,
    )


def test_amplitude_requires_args() -> None:
    with pytest.raises(ValueError):
        AmplitudeToolSet(api_key="", secret_key="s")
    with pytest.raises(ValueError):
        AmplitudeToolSet(api_key="k", secret_key="")
    with pytest.raises(ValueError):
        AmplitudeToolSet(api_key="k", secret_key="s", region="bogus")


def test_amplitude_endpoints() -> None:
    connector, transport = _amplitude()
    for _ in range(10):
        transport.enqueue(json_response({"data": []}))
    connector.upload_events(
        [{"event_type": "x", "user_id": "u"}],
        options={"min_id_length": 1},
    )
    connector.identify([{"user_id": "u", "user_properties": {"k": "v"}}])
    connector.event_segmentation(
        event={"event_type": "x"},
        start="20260101",
        end="20260102",
        interval=1,
        segment_definitions=[],
        group_by=[{"prop": "p"}],
    )
    connector.funnel_analysis(
        events=[{"event_type": "x"}],
        start="20260101",
        end="20260102",
        conversion_window=86400,
        mode="ordered",
    )
    connector.retention_analysis(
        starting_event={"event_type": "x"},
        returning_event={"event_type": "y"},
        start="20260101",
        end="20260131",
    )
    connector.get_user_activity("u")
    connector.get_user_search("u")
    connector.list_cohorts()
    connector.get_cohort("cohort-1", props=True)
    connector.export_raw_events(start="20260101T00", end="20260102T00")
    with pytest.raises(ValueError):
        connector.upload_events([])
    with pytest.raises(ValueError):
        connector.identify([])
    with pytest.raises(ValueError):
        connector.event_segmentation(event={}, start="a", end="b")
    with pytest.raises(ValueError):
        connector.funnel_analysis(events=[], start="a", end="b")
    with pytest.raises(ValueError):
        connector.funnel_analysis(events=[{"x": 1}], start="a", end="b", mode="bogus")
    with pytest.raises(ValueError):
        connector.retention_analysis(starting_event={}, returning_event={}, start="", end="b")
    with pytest.raises(ValueError):
        connector.get_user_activity("")
    with pytest.raises(ValueError):
        connector.get_user_search("")
    with pytest.raises(ValueError):
        connector.get_cohort("")
    with pytest.raises(ValueError):
        connector.export_raw_events(start="", end="b")


# MARK: - Mixpanel


def _mixpanel() -> tuple[MixpanelToolSet, MockTransport]:
    transport = MockTransport()
    return (
        MixpanelToolSet(
            project_token="pt",
            service_account_user="su",
            service_account_secret="ss",
            project_id=1,
            transport=transport,
        ),
        transport,
    )


def test_mixpanel_requires_args() -> None:
    with pytest.raises(ValueError):
        MixpanelToolSet(
            project_token="",
            service_account_user="u",
            service_account_secret="s",
            project_id=1,
        )
    with pytest.raises(ValueError):
        MixpanelToolSet(
            project_token="t",
            service_account_user="u",
            service_account_secret="s",
            project_id=1,
            region="bogus",
        )


def test_mixpanel_ingest_and_query() -> None:
    connector, transport = _mixpanel()
    for _ in range(10):
        transport.enqueue(json_response({"status": 1}))
    connector.track(event="x", properties={"k": "v"}, distinct_id="u")
    connector.import_events([{"event": "x", "properties": {"time": 1}}])
    connector.engage([{"$token": "t", "$distinct_id": "u", "$set": {"k": "v"}}])
    connector.group_update([{"$token": "t", "$group_key": "g", "$group_id": "1", "$set": {}}])
    connector.events_query(event=["x"], type="general", unit="day", interval=7)
    connector.segmentation(
        event="x",
        from_date="2026-01-01",
        to_date="2026-01-31",
        on="properties.region",
    )
    connector.funnels(funnel_id=1, from_date="2026-01-01", to_date="2026-01-31")
    connector.retention(
        from_date="2026-01-01",
        to_date="2026-01-31",
        born_event="signup",
        event="purchase",
        retention_type="birth",
    )
    connector.export_events(
        from_date="2026-01-01",
        to_date="2026-01-31",
        event=["x"],
        where="properties.k=='v'",
    )
    connector.query_jql(script="function main(){return [];}")
    with pytest.raises(ValueError):
        connector.track(event="", properties={"k": "v"})
    with pytest.raises(ValueError):
        connector.track(event="x", properties={})
    with pytest.raises(ValueError):
        connector.import_events([])
    with pytest.raises(ValueError):
        connector.engage([])
    with pytest.raises(ValueError):
        connector.group_update([])
    with pytest.raises(ValueError):
        connector.events_query(event=[])
    with pytest.raises(ValueError):
        connector.segmentation(event="", from_date="a", to_date="b")
    with pytest.raises(ValueError):
        connector.funnels(funnel_id=0, from_date="a", to_date="b")
    with pytest.raises(ValueError):
        connector.retention(from_date="", to_date="b")
    with pytest.raises(ValueError):
        connector.export_events(from_date="", to_date="b")
    with pytest.raises(ValueError):
        connector.query_jql(script="")


# MARK: - Segment


def test_segment_requires_at_least_one_key() -> None:
    with pytest.raises(ValueError):
        SegmentToolSet()


def _segment() -> tuple[SegmentToolSet, MockTransport]:
    transport = MockTransport()
    return (
        SegmentToolSet(
            write_key="wk",
            public_api_token="pt",
            transport=transport,
        ),
        transport,
    )


def test_segment_tracking() -> None:
    connector, transport = _segment()
    for _ in range(5):
        transport.enqueue(json_response({"success": True}))
    connector.track(user_id="u", event="signed_up", properties={"plan": "pro"})
    connector.identify(user_id="u", traits={"email": "a@b"})
    connector.group(user_id="u", group_id="g1", traits={"plan": "pro"})
    connector.page(user_id="u", name="home", properties={"k": "v"})
    connector.batch(batch=[{"type": "track", "event": "x"}], context={"app": "y"})
    with pytest.raises(ValueError):
        connector.track(event="x")
    with pytest.raises(ValueError):
        connector.track(user_id="u", event="")
    with pytest.raises(ValueError):
        connector.identify()
    with pytest.raises(ValueError):
        connector.group(group_id="g")
    with pytest.raises(ValueError):
        connector.group(user_id="u", group_id="")
    with pytest.raises(ValueError):
        connector.page()
    with pytest.raises(ValueError):
        connector.batch(batch=[])


def test_segment_public_api() -> None:
    connector, transport = _segment()
    for _ in range(4):
        transport.enqueue(json_response({"data": []}))
    connector.get_workspace()
    connector.list_sources(page_size=10, cursor="cur")
    connector.list_destinations(page_size=10, cursor="cur")
    connector.list_warehouses(page_size=10, cursor="cur")
    transport.enqueue(json_response({"data": {}}))
    connector.get_source("s1")
    with pytest.raises(ValueError):
        connector.get_source("")


def test_segment_no_tracking() -> None:
    transport = MockTransport()
    public_only = SegmentToolSet(public_api_token="t", transport=transport)
    with pytest.raises(ValueError):
        public_only.track(user_id="u", event="x")


# MARK: - PostHog


def _posthog() -> tuple[PostHogToolSet, MockTransport]:
    transport = MockTransport()
    return (
        PostHogToolSet(
            personal_api_key="k",
            project_api_key="phc",
            project_id=1,
            transport=transport,
        ),
        transport,
    )


def test_posthog_requires_args() -> None:
    with pytest.raises(ValueError):
        PostHogToolSet(personal_api_key="", project_id=1)
    with pytest.raises(ValueError):
        PostHogToolSet(personal_api_key="k", project_id=0)


def test_posthog_endpoints() -> None:
    connector, transport = _posthog()
    for _ in range(11):
        transport.enqueue(json_response({"results": []}))
    connector.capture(
        event="x",
        distinct_id="u",
        properties={"k": "v"},
        timestamp="2026-01-01",
    )
    connector.list_events(
        after="2026-01-01",
        before="2026-01-02",
        distinct_id="u",
        event="x",
        limit=10,
    )
    connector.list_insights(limit=10)
    connector.get_insight(1)
    connector.query_hogql(query="SELECT 1")
    connector.list_feature_flags()
    connector.create_feature_flag(
        key="ff",
        name="N",
        filters={"groups": []},
        active=True,
    )
    connector.update_feature_flag(1, active=False, name="N2")
    connector.list_persons(search="x", distinct_id="u", limit=10)
    connector.list_cohorts()
    transport.enqueue(json_response({"results": []}))
    connector.list_events()
    with pytest.raises(ValueError):
        connector.capture(event="", distinct_id="u")
    with pytest.raises(ValueError):
        connector.capture(event="x", distinct_id="")
    with pytest.raises(ValueError):
        connector.get_insight(0)
    with pytest.raises(ValueError):
        connector.query_hogql(query="")
    with pytest.raises(ValueError):
        connector.create_feature_flag(key="")
    with pytest.raises(ValueError):
        connector.update_feature_flag(0)
    with pytest.raises(ValueError):
        connector.update_feature_flag(1)


def test_posthog_capture_requires_project_key() -> None:
    transport = MockTransport()
    no_project = PostHogToolSet(
        personal_api_key="k",
        project_id=1,
        transport=transport,
    )
    with pytest.raises(ValueError):
        no_project.capture(event="x", distinct_id="u")


# MARK: - Looker


def _looker() -> tuple[LookerToolSet, MockTransport]:
    transport = MockTransport()
    return (
        LookerToolSet(
            base_url="https://looker.example:19999",
            access_token="t",
            transport=transport,
        ),
        transport,
    )


def test_looker_requires_args() -> None:
    with pytest.raises(ValueError):
        LookerToolSet(base_url="", access_token="t")
    with pytest.raises(ValueError):
        LookerToolSet(base_url="x", access_token="")


def test_looker_endpoints() -> None:
    connector, transport = _looker()
    for _ in range(10):
        transport.enqueue(json_response({"id": 1}))
    connector.me()
    connector.list_looks(fields="id,title", limit=25, offset=0)
    connector.get_look(1, fields="id,title")
    connector.run_look(1, result_format="json", limit=100)
    connector.list_dashboards(fields="id,title")
    connector.get_dashboard("d1", fields="id,title")
    connector.create_query(
        model="ecom",
        view="orders",
        fields=["orders.count"],
        filters={"orders.created_date": "30 days"},
        sorts=["orders.count desc"],
        limit=100,
    )
    connector.run_query(1, result_format="json")
    connector.list_users(limit=25, offset=0, sorts="id desc")
    connector.search_content("terms", types="dashboard", limit=25, offset=0)
    assert transport.requests[0].headers["Authorization"] == "token t"
    with pytest.raises(ValueError):
        connector.get_look(0)
    with pytest.raises(ValueError):
        connector.run_look(0)
    with pytest.raises(ValueError):
        connector.run_look(1, result_format="bogus")
    with pytest.raises(ValueError):
        connector.get_dashboard("")
    with pytest.raises(ValueError):
        connector.create_query(model="", view="o", fields=["x"])
    with pytest.raises(ValueError):
        connector.run_query(0)
    with pytest.raises(ValueError):
        connector.search_content("")


# MARK: - Tableau


def _tableau() -> tuple[TableauToolSet, MockTransport]:
    transport = MockTransport()
    return (
        TableauToolSet(
            server_url="https://tableau.example",
            site_id="site-1",
            auth_token="t",
            transport=transport,
        ),
        transport,
    )


def test_tableau_requires_args() -> None:
    with pytest.raises(ValueError):
        TableauToolSet(server_url="", site_id="s", auth_token="t")
    with pytest.raises(ValueError):
        TableauToolSet(server_url="u", site_id="", auth_token="t")
    with pytest.raises(ValueError):
        TableauToolSet(server_url="u", site_id="s", auth_token="")


def test_tableau_endpoints() -> None:
    connector, transport = _tableau()
    for _ in range(12):
        transport.enqueue(json_response({"data": []}))
    connector.get_server_info()
    connector.list_sites(page_size=10, page_number=1)
    connector.list_projects(page_size=10, page_number=1)
    connector.list_workbooks(
        page_size=10,
        page_number=1,
        filter="name:eq:X",
        sort="updatedAt:desc",
    )
    connector.get_workbook("w1")
    connector.list_views_for_workbook("w1")
    connector.query_view_data("v1", format="csv", max_age=300)
    connector.list_datasources(page_size=10, page_number=1)
    connector.refresh_datasource("ds1")
    connector.refresh_workbook("w1")
    connector.get_job("j1")
    connector.delete_workbook("w1")
    assert transport.requests[0].headers["X-Tableau-Auth"] == "t"
    assert transport.requests[11].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_workbook("")
    with pytest.raises(ValueError):
        connector.list_views_for_workbook("")
    with pytest.raises(ValueError):
        connector.query_view_data("")
    with pytest.raises(ValueError):
        connector.query_view_data("v", format="bogus")
    with pytest.raises(ValueError):
        connector.refresh_datasource("")
    with pytest.raises(ValueError):
        connector.refresh_workbook("")
    with pytest.raises(ValueError):
        connector.get_job("")
    with pytest.raises(ValueError):
        connector.delete_workbook("")


# MARK: - Metabase


def _metabase() -> tuple[MetabaseToolSet, MockTransport]:
    transport = MockTransport()
    return (
        MetabaseToolSet(
            base_url="https://mb.example",
            api_key="k",
            transport=transport,
        ),
        transport,
    )


def test_metabase_requires_args() -> None:
    with pytest.raises(ValueError):
        MetabaseToolSet(base_url="", api_key="k")
    with pytest.raises(ValueError):
        MetabaseToolSet(base_url="u", api_key="")
    with pytest.raises(ValueError):
        MetabaseToolSet(base_url="u", api_key="k", key_kind="bogus")


def test_metabase_endpoints() -> None:
    connector, transport = _metabase()
    for _ in range(10):
        transport.enqueue(json_response({"data": []}))
    connector.get_current_user()
    connector.list_databases()
    connector.list_cards(collection_id=1, archived=False)
    connector.get_card(1)
    connector.run_card_query(1, parameters=[{"value": 1}])
    connector.list_dashboards(f="all")
    connector.get_dashboard(1)
    connector.list_collections()
    connector.query_dataset(
        database=1,
        query_type="native",
        native={"query": "SELECT 1"},
        parameters=[],
    )
    connector.search("term", models=["card"], limit=10)
    assert transport.requests[0].headers["X-API-KEY"] == "k"
    with pytest.raises(ValueError):
        connector.get_card(0)
    with pytest.raises(ValueError):
        connector.run_card_query(0)
    with pytest.raises(ValueError):
        connector.get_dashboard(0)
    with pytest.raises(ValueError):
        connector.query_dataset(database=0, query_type="native", native={"query": "x"})
    with pytest.raises(ValueError):
        connector.query_dataset(database=1, query_type="bogus")
    with pytest.raises(ValueError):
        connector.query_dataset(database=1, query_type="native")
    with pytest.raises(ValueError):
        connector.query_dataset(database=1, query_type="query")
    with pytest.raises(ValueError):
        connector.search("")


# MARK: - Hex


def _hex() -> tuple[HexToolSet, MockTransport]:
    transport = MockTransport()
    return HexToolSet(api_token="t", transport=transport), transport


def test_hex_requires_token() -> None:
    with pytest.raises(ValueError):
        HexToolSet(api_token="")


def test_hex_endpoints() -> None:
    connector, transport = _hex()
    for _ in range(6):
        transport.enqueue(json_response({"data": {}}))
    connector.list_projects(
        limit=10,
        after="cur",
        include_archived=True,
        include_trashed=True,
    )
    connector.get_project("p1")
    connector.run_project(
        "p1",
        input_params={"a": 1},
        update_published_results=True,
        notifications=[{"type": "email"}],
    )
    connector.get_run_status(project_id="p1", run_id="r1")
    connector.list_project_runs("p1", limit=10, offset=0, status_filter="OK")
    connector.cancel_run(project_id="p1", run_id="r1")
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert transport.requests[5].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_project("")
    with pytest.raises(ValueError):
        connector.run_project("")
    with pytest.raises(ValueError):
        connector.get_run_status(project_id="", run_id="r")
    with pytest.raises(ValueError):
        connector.list_project_runs("")
    with pytest.raises(ValueError):
        connector.cancel_run(project_id="", run_id="r")


# MARK: - Sigma


def _sigma() -> tuple[SigmaToolSet, MockTransport]:
    transport = MockTransport()
    return SigmaToolSet(access_token="t", transport=transport), transport


def test_sigma_requires_token() -> None:
    with pytest.raises(ValueError):
        SigmaToolSet(access_token="")


def test_sigma_endpoints() -> None:
    connector, transport = _sigma()
    for _ in range(8):
        transport.enqueue(json_response({"data": []}))
    connector.list_workbooks(page="1", limit=10)
    connector.get_workbook("w1")
    connector.export_workbook(
        workbook_id="w1",
        format="csv",
        element_id="e1",
        parameters={"k": "v"},
    )
    connector.list_datasets(page="1", limit=10)
    connector.get_dataset("ds1")
    connector.list_members(page="1", limit=10)
    connector.list_schedules(page="1", limit=10)
    connector.create_embed(
        workbook_id="w1",
        embed_type="secure",
        source_type="element",
        source_id="e1",
    )
    with pytest.raises(ValueError):
        connector.get_workbook("")
    with pytest.raises(ValueError):
        connector.export_workbook(workbook_id="", format="csv")
    with pytest.raises(ValueError):
        connector.export_workbook(workbook_id="w", format="bogus")
    with pytest.raises(ValueError):
        connector.get_dataset("")
    with pytest.raises(ValueError):
        connector.create_embed(workbook_id="")
    with pytest.raises(ValueError):
        connector.create_embed(workbook_id="w", source_type="bogus")


# MARK: - Agent-ready summary tests


def _destructive_method_names(toolset: object) -> set[str]:
    """Return the names of @toolify methods on ``toolset`` flagged destructive."""
    names: set[str] = set()
    for name in dir(toolset):
        attr = getattr(toolset.__class__, name, None)
        spec = getattr(attr, "__maivn_toolify__", None) if attr is not None else None
        if spec is not None and getattr(spec, "destructive", False):
            names.add(name)
    return names


def test_amplitude_list_cohorts_returns_summaries_without_ids() -> None:
    connector, transport = _amplitude()
    transport.enqueue(
        json_response(
            {
                "cohorts": [
                    {
                        "id": "abc123",
                        "name": "Power users",
                        "description": "Logged in 5 days/week",
                        "size": 1024,
                        "owner": "alice@example.com",
                        "last_mod": "2026-01-15",
                    }
                ]
            }
        )
    )
    result = connector.list_cohorts(limit=5)
    assert result["cohorts"] == [
        {
            "cohort_ref": "cohort_1",
            "name": "Power users",
            "description": "Logged in 5 days/week",
            "size": 1024,
            "owner": "alice@example.com",
            "last_modified": "2026-01-15",
        }
    ]
    assert "cohort_id" not in result["cohorts"][0]


def test_amplitude_list_cohorts_include_ids() -> None:
    connector, transport = _amplitude()
    transport.enqueue(
        json_response(
            {
                "cohorts": [
                    {
                        "id": "abc123",
                        "name": "Power users",
                    }
                ]
            }
        )
    )
    result = connector.list_cohorts(include_ids=True)
    assert result["cohorts"][0]["cohort_id"] == "abc123"


def test_amplitude_get_user_search_returns_summaries() -> None:
    connector, transport = _amplitude()
    transport.enqueue(
        json_response(
            {
                "matches": [
                    {
                        "user_id": "u_42",
                        "amplitude_id": 9876,
                        "device_id": "d_x",
                        "last_seen": "2026-05-10",
                    }
                ],
                "type": "match_user_or_device_id",
            }
        )
    )
    result = connector.get_user_search("u_42")
    assert result["users"] == [
        {
            "user_ref": "user_1",
            "user_id": "u_42",
            "last_seen": "2026-05-10",
        }
    ]
    result_with_ids = None
    transport.enqueue(
        json_response(
            {
                "matches": [
                    {
                        "user_id": "u_42",
                        "amplitude_id": 9876,
                        "device_id": "d_x",
                    }
                ]
            }
        )
    )
    result_with_ids = connector.get_user_search("u_42", include_ids=True)
    assert result_with_ids["users"][0]["amplitude_id"] == 9876
    assert result_with_ids["users"][0]["device_id"] == "d_x"


def test_posthog_list_events_returns_summaries_without_ids() -> None:
    connector, transport = _posthog()
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "id": "evt_1",
                        "event": "Signed Up",
                        "distinct_id": "user-7",
                        "timestamp": "2026-05-12T10:00:00Z",
                        "person": {"name": "Bob"},
                    }
                ],
                "next": "next-cursor",
            }
        )
    )
    result = connector.list_events(limit=5)
    assert result["events"] == [
        {
            "event_ref": "event_1",
            "event": "Signed Up",
            "distinct_id": "user-7",
            "timestamp": "2026-05-12T10:00:00Z",
            "person_name": "Bob",
        }
    ]
    assert result["next"] == "next-cursor"
    assert "event_id" not in result["events"][0]


def test_posthog_list_events_include_ids() -> None:
    connector, transport = _posthog()
    transport.enqueue(json_response({"results": [{"id": "evt_1", "event": "x"}]}))
    result = connector.list_events(include_ids=True)
    assert result["events"][0]["event_id"] == "evt_1"


def test_posthog_list_persons_includes_emails() -> None:
    connector, transport = _posthog()
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "id": "p1",
                        "distinct_ids": ["user-7"],
                        "properties": {"name": "Bob", "email": "bob@example.test"},
                        "created_at": "2026-01-01",
                    }
                ]
            }
        )
    )
    result = connector.list_persons(limit=5)
    assert result["persons"][0]["name"] == "Bob"
    assert result["persons"][0]["email"] == "bob@example.test"
    assert "person_id" not in result["persons"][0]


def test_segment_list_sources_returns_summaries_without_ids() -> None:
    connector, transport = _segment()
    transport.enqueue(
        json_response(
            {
                "data": {
                    "sources": [
                        {
                            "id": "src_1",
                            "name": "Web JS",
                            "slug": "web-js",
                            "enabled": True,
                            "metadata": {"slug": "javascript", "name": "JavaScript"},
                        }
                    ],
                    "pagination": {"next": "cur-2"},
                }
            }
        )
    )
    result = connector.list_sources()
    assert result["sources"] == [
        {
            "source_ref": "source_1",
            "name": "Web JS",
            "slug": "web-js",
            "enabled": True,
            "category": "javascript",
        }
    ]
    assert result["nextCursor"] == "cur-2"
    assert "source_id" not in result["sources"][0]


def test_segment_list_sources_include_ids() -> None:
    connector, transport = _segment()
    transport.enqueue(
        json_response(
            {
                "data": {
                    "sources": [{"id": "src_1", "name": "Web JS"}],
                    "pagination": {"next": None},
                }
            }
        )
    )
    result = connector.list_sources(include_ids=True)
    assert result["sources"][0]["source_id"] == "src_1"


def test_looker_list_dashboards_returns_summaries_without_ids() -> None:
    connector, transport = _looker()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 5,
                    "title": "Revenue overview",
                    "description": "Top-line MRR",
                    "view_count": 42,
                    "updated_at": "2026-05-01",
                }
            ]
        )
    )
    result = connector.list_dashboards()
    assert result["dashboards"] == [
        {
            "dashboard_ref": "dashboard_1",
            "title": "Revenue overview",
            "description": "Top-line MRR",
            "view_count": 42,
            "updated_at": "2026-05-01",
        }
    ]
    assert "dashboard_id" not in result["dashboards"][0]


def test_looker_list_dashboards_include_ids() -> None:
    connector, transport = _looker()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 5,
                    "title": "Revenue overview",
                }
            ]
        )
    )
    result = connector.list_dashboards(include_ids=True)
    assert result["dashboards"][0]["dashboard_id"] == 5


def test_tableau_list_workbooks_returns_summaries_without_ids() -> None:
    connector, transport = _tableau()
    transport.enqueue(
        json_response(
            {
                "workbooks": {
                    "workbook": [
                        {
                            "id": "wb-1",
                            "name": "Sales",
                            "description": "Q1 sales",
                            "owner": {"name": "Alice"},
                            "project": {"name": "Default"},
                            "updatedAt": "2026-04-01",
                        }
                    ]
                },
                "pagination": {"totalAvailable": "1"},
            }
        )
    )
    result = connector.list_workbooks()
    assert result["workbooks"] == [
        {
            "workbook_ref": "workbook_1",
            "name": "Sales",
            "description": "Q1 sales",
            "owner_name": "Alice",
            "project_name": "Default",
            "updated_at": "2026-04-01",
        }
    ]
    assert "workbook_id" not in result["workbooks"][0]


def test_tableau_list_workbooks_include_ids() -> None:
    connector, transport = _tableau()
    transport.enqueue(
        json_response(
            {
                "workbooks": {
                    "workbook": [{"id": "wb-1", "name": "Sales"}],
                }
            }
        )
    )
    result = connector.list_workbooks(include_ids=True)
    assert result["workbooks"][0]["workbook_id"] == "wb-1"


def test_tableau_delete_workbook_accepts_summary_dict() -> None:
    connector, transport = _tableau()
    transport.enqueue(json_response({"ok": True}))
    result = connector.delete_workbook({"workbook_id": "wb-1", "name": "Sales"})
    assert result["workbook_id"] == "wb-1"
    assert result["deleted"] is True
    assert transport.requests[0].method == "DELETE"


def test_metabase_list_cards_returns_summaries_without_ids() -> None:
    connector, transport = _metabase()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 17,
                    "name": "Active users",
                    "description": "Daily active",
                    "display": "line",
                    "creator": {"email": "alice@example.com"},
                    "updated_at": "2026-04-01",
                }
            ]
        )
    )
    result = connector.list_cards()
    assert result["cards"] == [
        {
            "card_ref": "card_1",
            "name": "Active users",
            "description": "Daily active",
            "display": "line",
            "creator_email": "alice@example.com",
            "updated_at": "2026-04-01",
        }
    ]
    assert "card_id" not in result["cards"][0]


def test_metabase_list_cards_include_ids() -> None:
    connector, transport = _metabase()
    transport.enqueue(json_response([{"id": 17, "name": "Active users"}]))
    result = connector.list_cards(include_ids=True)
    assert result["cards"][0]["card_id"] == 17


def test_hex_list_projects_returns_summaries_without_ids() -> None:
    connector, transport = _hex()
    transport.enqueue(
        json_response(
            {
                "values": [
                    {
                        "id": "p1",
                        "title": "Retention",
                        "description": "Weekly retention",
                        "creator": {"email": "alice@example.com"},
                        "lastEditedAt": "2026-04-01",
                    }
                ],
                "pagination": {"after": "after-2"},
            }
        )
    )
    result = connector.list_projects()
    assert result["projects"] == [
        {
            "project_ref": "project_1",
            "title": "Retention",
            "description": "Weekly retention",
            "creator_email": "alice@example.com",
            "last_edited_at": "2026-04-01",
            "archived": False,
        }
    ]
    assert result["nextAfter"] == "after-2"
    assert "project_id" not in result["projects"][0]


def test_hex_list_projects_include_ids() -> None:
    connector, transport = _hex()
    transport.enqueue(
        json_response(
            {
                "values": [{"id": "p1", "title": "Retention"}],
            }
        )
    )
    result = connector.list_projects(include_ids=True)
    assert result["projects"][0]["project_id"] == "p1"


def test_sigma_list_workbooks_returns_summaries_without_ids() -> None:
    connector, transport = _sigma()
    transport.enqueue(
        json_response(
            {
                "entries": [
                    {
                        "workbookId": "wb-1",
                        "name": "Trends",
                        "description": "Quarterly trends",
                        "ownerEmail": "alice@example.com",
                        "updatedAt": "2026-04-01",
                    }
                ],
                "nextPage": 2,
            }
        )
    )
    result = connector.list_workbooks()
    assert result["workbooks"] == [
        {
            "workbook_ref": "workbook_1",
            "name": "Trends",
            "description": "Quarterly trends",
            "owner_email": "alice@example.com",
            "updated_at": "2026-04-01",
        }
    ]
    assert "workbook_id" not in result["workbooks"][0]


def test_sigma_list_workbooks_include_ids() -> None:
    connector, transport = _sigma()
    transport.enqueue(
        json_response(
            {
                "entries": [{"workbookId": "wb-1", "name": "Trends"}],
            }
        )
    )
    result = connector.list_workbooks(include_ids=True)
    assert result["workbooks"][0]["workbook_id"] == "wb-1"


# MARK: - Destructive tool tagging


def test_tableau_delete_workbook_is_tagged_destructive() -> None:
    connector, _ = _tableau()
    assert "delete_workbook" in _destructive_method_names(connector)


def test_hex_cancel_run_is_tagged_destructive() -> None:
    connector, _ = _hex()
    assert "cancel_run" in _destructive_method_names(connector)
