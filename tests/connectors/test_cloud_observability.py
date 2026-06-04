"""Tests for cloud and observability connectors.

Datadog, Sentry, PagerDuty, New Relic, Splunk, Grafana, Statuspage,
Cloudflare, and Kubernetes.
"""

# pyright: strict

from __future__ import annotations

import pytest

from maivn_tools.connectors.cloudflare import CloudflareToolSet
from maivn_tools.connectors.datadog import DatadogToolSet
from maivn_tools.connectors.grafana import GrafanaToolSet
from maivn_tools.connectors.kubernetes import KubernetesToolSet
from maivn_tools.connectors.new_relic import NewRelicToolSet
from maivn_tools.connectors.pagerduty import PagerDutyToolSet
from maivn_tools.connectors.sentry import SentryToolSet
from maivn_tools.connectors.splunk import SplunkToolSet
from maivn_tools.connectors.statuspage import StatuspageToolSet
from maivn_tools.testing import MockTransport, json_response, text_response

# MARK: - Datadog


def _datadog() -> tuple[DatadogToolSet, MockTransport]:
    transport = MockTransport()
    return (
        DatadogToolSet(api_key="k", app_key="a", transport=transport),
        transport,
    )


def test_datadog_requires_key() -> None:
    with pytest.raises(ValueError):
        DatadogToolSet(api_key="")


def test_datadog_logs_and_metrics() -> None:
    connector, transport = _datadog()
    for _ in range(4):
        transport.enqueue(json_response({"data": []}))
    connector.search_logs(
        query="status:error",
        from_time="now-15m",
        to_time="now",
        limit=10,
        cursor="c",
        indexes=["main"],
    )
    connector.submit_logs([{"message": "hi", "ddsource": "x"}])
    connector.query_metrics(from_time=1, to_time=2, query="avg:system.cpu.user{*}")
    connector.submit_metrics([{"metric": "x", "points": [[1, 0.5]]}])
    assert transport.requests[0].headers["DD-API-KEY"] == "k"
    assert transport.requests[0].headers["DD-APPLICATION-KEY"] == "a"
    with pytest.raises(ValueError):
        connector.search_logs(query="", from_time="x", to_time="y")
    with pytest.raises(ValueError):
        connector.submit_logs([])
    with pytest.raises(ValueError):
        connector.query_metrics(from_time=1, to_time=2, query="")
    with pytest.raises(ValueError):
        connector.submit_metrics([])


def test_datadog_monitors_and_events() -> None:
    connector, transport = _datadog()
    for _ in range(7):
        transport.enqueue(json_response({"id": 1}))
    connector.list_monitors(name="x", tags=["env:prod"], page=0, page_size=50)
    connector.get_monitor(1)
    connector.create_monitor(
        type="metric alert",
        query="avg(last_5m):x > 1",
        name="n",
        message="m",
        tags=["t"],
        options={"thresholds": {"critical": 1}},
    )
    connector.delete_monitor(1)
    connector.mute_monitor(1, scope="env:prod", end=1234567890)
    connector.post_event(title="t", text="x", priority="normal", tags=["t"], alert_type="info")
    connector.list_dashboards()
    assert transport.requests[3].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_monitor(0)
    with pytest.raises(ValueError):
        connector.create_monitor(type="", query="x", name="n", message="m")
    with pytest.raises(ValueError):
        connector.delete_monitor(0)
    with pytest.raises(ValueError):
        connector.mute_monitor(0)
    with pytest.raises(ValueError):
        connector.post_event(title="", text="x")


def test_datadog_dashboard() -> None:
    connector, transport = _datadog()
    transport.enqueue(json_response({"id": "d"}))
    connector.get_dashboard("d")
    with pytest.raises(ValueError):
        connector.get_dashboard("")


# MARK: - Sentry


def _sentry() -> tuple[SentryToolSet, MockTransport]:
    transport = MockTransport()
    return SentryToolSet(auth_token="t", transport=transport), transport


def test_sentry_requires_token() -> None:
    with pytest.raises(ValueError):
        SentryToolSet(auth_token="")


def test_sentry_endpoints() -> None:
    connector, transport = _sentry()
    for _ in range(11):
        transport.enqueue(json_response({"id": "1"}))
    connector.list_organizations()
    connector.list_projects("org")
    connector.get_project(org_slug="org", project_slug="p")
    connector.list_issues(
        org_slug="org",
        project_slug="p",
        query="is:unresolved",
        limit=10,
        cursor="cur",
    )
    connector.get_issue("i1", org_slug="org")
    connector.update_issue(
        "i1",
        org_slug="org",
        status="resolved",
        assigned_to="user",
        is_bookmarked=True,
        has_seen=True,
    )
    connector.delete_issue("i1", org_slug="org")
    connector.list_events_for_issue("i1", org_slug="org", full=True, cursor="cur")
    connector.list_releases("org")
    connector.create_release(
        org_slug="org",
        version="1.0.0",
        projects=["p"],
        ref="abc",
        url="https://x",
        commits=[{"id": "c"}],
    )
    connector.list_alert_rules(org_slug="org", project_slug="p")
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert transport.requests[5].method == "PUT"
    assert transport.requests[6].method == "DELETE"
    with pytest.raises(ValueError):
        connector.list_projects("")
    with pytest.raises(ValueError):
        connector.get_project(org_slug="", project_slug="p")
    with pytest.raises(ValueError):
        connector.list_issues(org_slug="", project_slug="p")
    with pytest.raises(ValueError):
        connector.get_issue("", org_slug="org")
    with pytest.raises(ValueError):
        connector.update_issue("", org_slug="org")
    with pytest.raises(ValueError):
        connector.update_issue("i1", org_slug="org")
    with pytest.raises(ValueError):
        connector.delete_issue("", org_slug="org")
    with pytest.raises(ValueError):
        connector.list_events_for_issue("", org_slug="org")
    with pytest.raises(ValueError):
        connector.list_releases("")
    with pytest.raises(ValueError):
        connector.create_release(org_slug="", version="v", projects=["p"])
    with pytest.raises(ValueError):
        connector.create_release(org_slug="o", version="", projects=["p"])
    with pytest.raises(ValueError):
        connector.create_release(org_slug="o", version="v", projects=[])
    with pytest.raises(ValueError):
        connector.list_alert_rules(org_slug="", project_slug="p")


# MARK: - PagerDuty


def _pagerduty() -> tuple[PagerDutyToolSet, MockTransport]:
    transport = MockTransport()
    return (
        PagerDutyToolSet(
            api_key="k",
            from_email="me@example.com",
            events_routing_key="rk",
            transport=transport,
        ),
        transport,
    )


def test_pagerduty_requires_key() -> None:
    with pytest.raises(ValueError):
        PagerDutyToolSet(api_key="")


def test_pagerduty_incidents() -> None:
    connector, transport = _pagerduty()
    for _ in range(4):
        transport.enqueue(json_response({"incident": {}}))
    connector.list_incidents(
        statuses=["triggered"],
        service_ids=["s1"],
        limit=10,
        offset=0,
    )
    connector.get_incident("I1")
    connector.update_incident(
        "I1",
        status="acknowledged",
        priority_id="p1",
        resolution="fixed",
    )
    connector.create_incident(
        title="T",
        service_id="s1",
        urgency="high",
        body="b",
        priority_id="p1",
    )
    assert transport.requests[2].headers["From"] == "me@example.com"
    with pytest.raises(ValueError):
        connector.get_incident("")
    with pytest.raises(ValueError):
        connector.update_incident("")
    with pytest.raises(ValueError):
        connector.update_incident("I1")
    with pytest.raises(ValueError):
        connector.create_incident(title="", service_id="s")
    with pytest.raises(ValueError):
        connector.create_incident(title="t", service_id="")
    with pytest.raises(ValueError):
        connector.create_incident(title="t", service_id="s", urgency="bogus")


def test_pagerduty_events_and_listing() -> None:
    connector, transport = _pagerduty()
    for _ in range(6):
        transport.enqueue(json_response({"status": "success"}))
    connector.trigger_event(
        summary="summary",
        source="src",
        severity="error",
        dedup_key="d",
        custom_details={"k": "v"},
    )
    connector.resolve_event("d")
    connector.list_services()
    connector.list_schedules()
    connector.list_on_calls(
        schedule_ids=["s1"],
        since="2026-01-01T00:00:00Z",
        until="2026-02-01T00:00:00Z",
    )
    connector.list_users()
    with pytest.raises(ValueError):
        connector.trigger_event(summary="", source="s")
    with pytest.raises(ValueError):
        connector.trigger_event(summary="x", source="")
    with pytest.raises(ValueError):
        connector.trigger_event(summary="x", source="s", severity="bogus")
    with pytest.raises(ValueError):
        connector.resolve_event("")


def test_pagerduty_no_from_email() -> None:
    transport = MockTransport()
    no_from = PagerDutyToolSet(api_key="k", events_routing_key="rk", transport=transport)
    with pytest.raises(ValueError):
        no_from.create_incident(title="t", service_id="s")


# MARK: - New Relic


def _new_relic() -> tuple[NewRelicToolSet, MockTransport]:
    transport = MockTransport()
    return (
        NewRelicToolSet(
            api_key="k",
            account_id=1,
            ingest_license_key="L",
            transport=transport,
        ),
        transport,
    )


def test_new_relic_requires_key() -> None:
    with pytest.raises(ValueError):
        NewRelicToolSet(api_key="")
    with pytest.raises(ValueError):
        NewRelicToolSet(api_key="k", region="bogus")


def test_new_relic_endpoints() -> None:
    connector, transport = _new_relic()
    for _ in range(8):
        transport.enqueue(json_response({"data": {}}))
    connector.nerdgraph_query("query { actor { user { email } } }", variables={"a": 1})
    connector.nrql_query("SELECT count(*) FROM Transaction")
    connector.submit_logs([{"message": "hi"}])
    connector.submit_metrics([{"name": "x", "value": 1, "timestamp": 1}])
    connector.list_alert_policies()
    connector.create_alert_policy(name="p", incident_preference="PER_POLICY")
    connector.delete_alert_policy(1)
    connector.list_applications()
    assert transport.requests[0].headers["API-Key"] == "k"
    assert transport.requests[2].headers["Api-Key"] == "L"
    with pytest.raises(ValueError):
        connector.nerdgraph_query("")
    with pytest.raises(ValueError):
        connector.nrql_query("")
    with pytest.raises(ValueError):
        connector.create_alert_policy(name="")
    with pytest.raises(ValueError):
        connector.create_alert_policy(name="p", incident_preference="bogus")
    with pytest.raises(ValueError):
        connector.delete_alert_policy(0)


def test_new_relic_ingest_required() -> None:
    transport = MockTransport()
    bare = NewRelicToolSet(api_key="k", account_id=1, transport=transport)
    with pytest.raises(ValueError):
        bare.submit_logs([{"x": 1}])
    with pytest.raises(ValueError):
        bare.submit_metrics([{"x": 1}])
    with pytest.raises(ValueError):
        bare.submit_logs([])
    transport2 = MockTransport()
    no_account = NewRelicToolSet(api_key="k", transport=transport2)
    with pytest.raises(ValueError):
        no_account.nrql_query("SELECT 1")


# MARK: - Splunk


def _splunk() -> tuple[SplunkToolSet, MockTransport]:
    transport = MockTransport()
    return (
        SplunkToolSet(
            token="t",
            base_url="https://splunk.example:8089",
            transport=transport,
        ),
        transport,
    )


def test_splunk_requires_args() -> None:
    with pytest.raises(ValueError):
        SplunkToolSet(token="", base_url="x")
    with pytest.raises(ValueError):
        SplunkToolSet(token="t", base_url="")


def test_splunk_jobs_and_searches() -> None:
    connector, transport = _splunk()
    for _ in range(8):
        transport.enqueue(json_response({"sid": "1"}))
    connector.create_search_job(
        search="search index=main",
        earliest_time="-1h",
        latest_time="now",
        exec_mode="normal",
    )
    connector.get_search_job("sid1")
    connector.get_search_results("sid1", count=50, offset=0)
    connector.cancel_search_job("sid1")
    connector.list_indexes()
    connector.list_saved_searches()
    connector.create_saved_search(
        name="ss",
        search="search index=main",
        is_scheduled=True,
        cron_schedule="*/5 * * * *",
    )
    connector.update_saved_search(name="ss", search="new query")
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    with pytest.raises(ValueError):
        connector.create_search_job(search="")
    with pytest.raises(ValueError):
        connector.create_search_job(search="x", exec_mode="bogus")
    with pytest.raises(ValueError):
        connector.get_search_job("")
    with pytest.raises(ValueError):
        connector.get_search_results("")
    with pytest.raises(ValueError):
        connector.cancel_search_job("")
    with pytest.raises(ValueError):
        connector.create_saved_search(name="", search="x")
    with pytest.raises(ValueError):
        connector.create_saved_search(name="n", search="")
    with pytest.raises(ValueError):
        connector.update_saved_search(name="")
    with pytest.raises(ValueError):
        connector.update_saved_search(name="n")


# MARK: - Grafana


def _grafana() -> tuple[GrafanaToolSet, MockTransport]:
    transport = MockTransport()
    return (
        GrafanaToolSet(
            api_key="k",
            base_url="https://g.example",
            transport=transport,
        ),
        transport,
    )


def test_grafana_requires_args() -> None:
    with pytest.raises(ValueError):
        GrafanaToolSet(api_key="", base_url="x")
    with pytest.raises(ValueError):
        GrafanaToolSet(api_key="k", base_url="")


def test_grafana_endpoints() -> None:
    connector, transport = _grafana()
    for _ in range(10):
        transport.enqueue(json_response({"id": 1}))
    connector.search_dashboards(query="q", tag=["t"], type="dash-db", limit=50, page=1)
    connector.get_dashboard_by_uid("uid")
    connector.create_or_update_dashboard(
        dashboard={"title": "x"},
        folder_uid="f",
        message="msg",
        overwrite=True,
    )
    connector.delete_dashboard_by_uid("uid")
    connector.list_folders(limit=10)
    connector.create_folder(title="f", uid="u", parent_uid="p")
    connector.list_datasources()
    connector.create_annotation(
        text="x",
        time=1,
        time_end=2,
        tags=["t"],
        dashboard_uid="d",
        panel_id=1,
    )
    connector.list_alert_rules()
    connector.get_health()
    assert transport.requests[0].headers["Authorization"] == "Bearer k"
    assert transport.requests[3].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_dashboard_by_uid("")
    with pytest.raises(ValueError):
        connector.create_or_update_dashboard(dashboard={})
    with pytest.raises(ValueError):
        connector.delete_dashboard_by_uid("")
    with pytest.raises(ValueError):
        connector.create_folder(title="")
    with pytest.raises(ValueError):
        connector.create_annotation(text="", time=1)
    with pytest.raises(ValueError):
        connector.create_annotation(text="x", time=0)


# MARK: - Statuspage


def _statuspage() -> tuple[StatuspageToolSet, MockTransport]:
    transport = MockTransport()
    return (
        StatuspageToolSet(api_key="k", page_id="page1", transport=transport),
        transport,
    )


def test_statuspage_requires_args() -> None:
    with pytest.raises(ValueError):
        StatuspageToolSet(api_key="", page_id="p")
    with pytest.raises(ValueError):
        StatuspageToolSet(api_key="k", page_id="")


def test_statuspage_endpoints() -> None:
    connector, transport = _statuspage()
    for _ in range(8):
        transport.enqueue(json_response({"id": "x"}))
    connector.get_page()
    connector.list_components()
    connector.update_component(
        "c1",
        status="degraded_performance",
        name="N",
        description="d",
    )
    connector.list_incidents(q="search", page=1, per_page=10)
    connector.create_incident(
        name="N",
        status="investigating",
        impact_override="critical",
        body="b",
        component_ids=["c1"],
    )
    connector.update_incident("i1", status="identified", body="b", impact_override="major")
    connector.delete_incident("i1")
    connector.schedule_maintenance(
        name="M",
        scheduled_for="2026-01-01T00:00:00Z",
        scheduled_until="2026-01-01T01:00:00Z",
        body="b",
        component_ids=["c1"],
        auto_in_progress=True,
        auto_completed=True,
    )
    assert transport.requests[0].headers["Authorization"] == "OAuth k"
    assert "/v1/pages/page1" in transport.requests[0].url
    assert transport.requests[6].method == "DELETE"
    with pytest.raises(ValueError):
        connector.update_component("")
    with pytest.raises(ValueError):
        connector.update_component("c", status="bogus")
    with pytest.raises(ValueError):
        connector.update_component("c")
    with pytest.raises(ValueError):
        connector.create_incident(name="")
    with pytest.raises(ValueError):
        connector.create_incident(name="n", status="bogus")
    with pytest.raises(ValueError):
        connector.update_incident("")
    with pytest.raises(ValueError):
        connector.update_incident("i1")
    with pytest.raises(ValueError):
        connector.delete_incident("")
    with pytest.raises(ValueError):
        connector.schedule_maintenance(name="", scheduled_for="x", scheduled_until="y")


def test_statuspage_subscribers() -> None:
    connector, transport = _statuspage()
    transport.enqueue(json_response([]))
    connector.list_subscribers(type="email", page=1, per_page=10)


# MARK: - Cloudflare


def _cloudflare() -> tuple[CloudflareToolSet, MockTransport]:
    transport = MockTransport()
    return (
        CloudflareToolSet(api_token="t", transport=transport),
        transport,
    )


def test_cloudflare_requires_token() -> None:
    with pytest.raises(ValueError):
        CloudflareToolSet(api_token="")


def test_cloudflare_zones_and_dns() -> None:
    connector, transport = _cloudflare()
    for _ in range(8):
        transport.enqueue(json_response({"result": []}))
    connector.verify_token()
    connector.list_zones(name="x", status="active", page=1, per_page=10)
    connector.get_zone("z1")
    connector.list_dns_records(
        "z1",
        type="A",
        name="x",
        content="1.2.3.4",
        page=1,
        per_page=10,
    )
    connector.create_dns_record(
        "z1",
        type="A",
        name="x",
        content="1.2.3.4",
        ttl=300,
        proxied=True,
        priority=10,
    )
    connector.update_dns_record(
        zone_id="z1",
        record_id="r1",
        name="new",
        proxied=False,
    )
    connector.delete_dns_record(zone_id="z1", record_id="r1")
    connector.purge_cache(
        "z1",
        purge_everything=False,
        files=["https://x/path"],
        tags=["t"],
        hosts=["h"],
    )
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert transport.requests[5].method == "PATCH"
    assert transport.requests[6].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_zone("")
    with pytest.raises(ValueError):
        connector.list_dns_records("")
    with pytest.raises(ValueError):
        connector.create_dns_record("", type="A", name="x", content="c")
    with pytest.raises(ValueError):
        connector.update_dns_record(zone_id="", record_id="r")
    with pytest.raises(ValueError):
        connector.update_dns_record(zone_id="z", record_id="r")
    with pytest.raises(ValueError):
        connector.delete_dns_record(zone_id="", record_id="r")
    with pytest.raises(ValueError):
        connector.purge_cache("")
    with pytest.raises(ValueError):
        connector.purge_cache("z")


def test_cloudflare_workers_and_r2() -> None:
    connector, transport = _cloudflare()
    for _ in range(3):
        transport.enqueue(json_response({"result": []}))
    connector.list_workers("acct")
    connector.list_r2_buckets("acct")
    connector.create_r2_bucket(account_id="acct", name="b", location_hint="WEUR")
    with pytest.raises(ValueError):
        connector.list_workers("")
    with pytest.raises(ValueError):
        connector.list_r2_buckets("")
    with pytest.raises(ValueError):
        connector.create_r2_bucket(account_id="", name="b")
    with pytest.raises(ValueError):
        connector.create_r2_bucket(account_id="a", name="")


# MARK: - Kubernetes


def _k8s() -> tuple[KubernetesToolSet, MockTransport]:
    transport = MockTransport()
    return (
        KubernetesToolSet(
            api_server="https://k8s.example:6443",
            token="t",
            transport=transport,
        ),
        transport,
    )


def test_kubernetes_requires_api_server() -> None:
    with pytest.raises(ValueError):
        KubernetesToolSet(api_server="")


def test_kubernetes_endpoints() -> None:
    connector, transport = _k8s()
    for _ in range(11):
        transport.enqueue(json_response({"items": []}))
    connector.get_version()
    connector.list_namespaces()
    connector.list_pods(
        namespace="default",
        label_selector="app=x",
        field_selector="status.phase=Running",
        limit=100,
    )
    connector.list_pods()
    connector.get_pod(namespace="default", name="pod-1")
    connector.list_deployments(namespace="default", label_selector="app=x")
    connector.scale_deployment(namespace="default", name="d1", replicas=3)
    connector.delete_pod(namespace="default", name="pod-1", grace_period_seconds=30)
    connector.list_services(namespace="default")
    connector.list_events(namespace="default", field_selector="type=Warning", limit=100)
    connector.list_nodes()
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert transport.requests[6].method == "PATCH"
    assert transport.requests[7].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_pod(namespace="", name="x")
    with pytest.raises(ValueError):
        connector.scale_deployment(namespace="", name="d", replicas=1)
    with pytest.raises(ValueError):
        connector.scale_deployment(namespace="ns", name="d", replicas=-1)
    with pytest.raises(ValueError):
        connector.delete_pod(namespace="", name="x")


def test_kubernetes_logs_and_apply() -> None:
    connector, transport = _k8s()
    transport.enqueue(text_response("log line 1\nlog line 2"))
    transport.enqueue(json_response({"kind": "Deployment"}))
    connector.get_pod_logs(
        namespace="default",
        name="p",
        container="c",
        tail_lines=10,
        since_seconds=60,
        previous=True,
    )
    connector.apply_manifest(
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "d", "namespace": "default"},
            "spec": {},
        },
    )
    with pytest.raises(ValueError):
        connector.get_pod_logs(namespace="", name="p")
    with pytest.raises(ValueError):
        connector.apply_manifest({})
    with pytest.raises(ValueError):
        connector.apply_manifest({"apiVersion": "v1"})


# MARK: - Agent-ready summaries (Datadog)


def test_datadog_search_logs_summary_hides_ids() -> None:
    connector, transport = _datadog()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "AAAA",
                        "attributes": {
                            "timestamp": "2026-05-16T00:00:00Z",
                            "service": "api",
                            "status": "error",
                            "host": "h1",
                            "message": "boom",
                            "tags": ["env:prod"],
                        },
                    },
                    {
                        "id": "BBBB",
                        "attributes": {
                            "timestamp": "2026-05-16T00:00:01Z",
                            "service": "worker",
                            "status": "warn",
                            "host": "h2",
                            "message": "slow query",
                        },
                    },
                ],
                "meta": {"page": {"after": "next-token"}},
            }
        )
    )
    result = connector.search_logs(query="status:error", from_time="now-15m", to_time="now")
    assert "logs" in result
    assert result["logs"][0]["log_ref"] == "log_1"
    assert result["logs"][0]["service"] == "api"
    assert result["logs"][0]["status"] == "error"
    assert result["logs"][0]["message"] == "boom"
    assert "log_id" not in result["logs"][0]
    assert result["next_cursor"] == "next-token"


def test_datadog_search_logs_include_ids() -> None:
    connector, transport = _datadog()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {"id": "AAAA", "attributes": {"message": "x"}},
                ],
            }
        )
    )
    result = connector.search_logs(query="*", from_time="now-1h", to_time="now", include_ids=True)
    assert result["logs"][0]["log_id"] == "AAAA"


def test_datadog_list_monitors_summary_hides_ids() -> None:
    connector, transport = _datadog()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 12345,
                    "name": "High CPU",
                    "type": "metric alert",
                    "overall_state": "Alert",
                    "message": "Page on-call",
                    "tags": ["team:platform"],
                },
            ]
        )
    )
    result = connector.list_monitors()
    assert "monitors" in result
    assert result["monitors"][0]["monitor_ref"] == "monitor_1"
    assert result["monitors"][0]["name"] == "High CPU"
    assert "monitor_id" not in result["monitors"][0]


def test_datadog_list_monitors_include_ids() -> None:
    connector, transport = _datadog()
    transport.enqueue(json_response([{"id": 99, "name": "M"}]))
    result = connector.list_monitors(include_ids=True)
    assert result["monitors"][0]["monitor_id"] == 99


def test_datadog_list_dashboards_summary() -> None:
    connector, transport = _datadog()
    transport.enqueue(
        json_response(
            {
                "dashboards": [
                    {
                        "id": "abc-123",
                        "title": "Overview",
                        "description": "Service overview",
                        "layout_type": "ordered",
                        "url": "/dashboard/abc",
                    },
                ]
            }
        )
    )
    result = connector.list_dashboards()
    assert result["dashboards"][0]["dashboard_ref"] == "dashboard_1"
    assert "dashboard_id" not in result["dashboards"][0]

    transport.enqueue(json_response({"dashboards": [{"id": "abc-123", "title": "x"}]}))
    result = connector.list_dashboards(include_ids=True)
    assert result["dashboards"][0]["dashboard_id"] == "abc-123"


def test_datadog_destructive_tools_marked() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _datadog()
    opts = get_toolify_options(connector.delete_monitor)
    assert opts is not None and opts.destructive is True


def test_datadog_delete_monitor_accepts_dict() -> None:
    connector, transport = _datadog()
    transport.enqueue(json_response({"deleted_monitor_id": 7}))
    connector.delete_monitor({"monitor_id": 7})
    assert transport.requests[0].method == "DELETE"
    assert "/monitor/7" in transport.requests[0].url


# MARK: - Agent-ready summaries (Sentry)


def test_sentry_list_issues_summary_hides_ids() -> None:
    connector, transport = _sentry()
    transport.enqueue(
        json_response(
            [
                {
                    "id": "issue-id-1",
                    "title": "TypeError: foo",
                    "culprit": "module.fn",
                    "status": "unresolved",
                    "level": "error",
                    "count": "42",
                    "lastSeen": "2026-05-16T00:00:00Z",
                    "permalink": "https://sentry.io/issues/1",
                },
            ]
        )
    )
    result = connector.list_issues(org_slug="org", project_slug="p")
    assert "issues" in result
    assert result["issues"][0]["issue_ref"] == "issue_1"
    assert result["issues"][0]["title"] == "TypeError: foo"
    assert "issue_id" not in result["issues"][0]


def test_sentry_list_issues_include_ids() -> None:
    connector, transport = _sentry()
    transport.enqueue(json_response([{"id": "iid", "title": "x"}]))
    result = connector.list_issues(org_slug="org", project_slug="p", include_ids=True)
    assert result["issues"][0]["issue_id"] == "iid"


def test_sentry_list_alert_rules_summary() -> None:
    connector, transport = _sentry()
    transport.enqueue(
        json_response(
            [
                {
                    "id": "rule-id-1",
                    "name": "Spike alert",
                    "environment": "production",
                    "frequency": 30,
                    "conditions": [{}, {}],
                    "actions": [{}],
                },
            ]
        )
    )
    result = connector.list_alert_rules(org_slug="org", project_slug="p")
    assert result["alerts"][0]["alert_ref"] == "alert_1"
    assert result["alerts"][0]["conditions_count"] == 2
    assert result["alerts"][0]["actions_count"] == 1
    assert "alert_id" not in result["alerts"][0]


def test_sentry_destructive_tool_marked() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _sentry()
    opts = get_toolify_options(connector.delete_issue)
    assert opts is not None and opts.destructive is True


def test_sentry_update_issue_accepts_dict() -> None:
    connector, transport = _sentry()
    transport.enqueue(json_response({"id": "iid"}))
    connector.update_issue({"issue_id": "iid"}, org_slug="org", status="resolved")
    assert transport.requests[0].method == "PUT"
    assert "/issues/iid/" in transport.requests[0].url


# MARK: - Agent-ready summaries (PagerDuty)


def test_pagerduty_list_incidents_summary_hides_ids() -> None:
    connector, transport = _pagerduty()
    transport.enqueue(
        json_response(
            {
                "incidents": [
                    {
                        "id": "PINCIDENT",
                        "incident_number": 42,
                        "title": "API down",
                        "status": "triggered",
                        "urgency": "high",
                        "created_at": "2026-05-16T00:00:00Z",
                        "service": {"summary": "API"},
                    }
                ],
                "more": False,
            }
        )
    )
    result = connector.list_incidents()
    assert result["incidents"][0]["incident_ref"] == "incident_1"
    assert result["incidents"][0]["title"] == "API down"
    assert result["incidents"][0]["service_name"] == "API"
    assert "incident_id" not in result["incidents"][0]


def test_pagerduty_list_incidents_include_ids() -> None:
    connector, transport = _pagerduty()
    transport.enqueue(json_response({"incidents": [{"id": "PI", "title": "x"}]}))
    result = connector.list_incidents(include_ids=True)
    assert result["incidents"][0]["incident_id"] == "PI"


def test_pagerduty_acknowledge_incident_accepts_dict() -> None:
    connector, transport = _pagerduty()
    transport.enqueue(json_response({"incident": {"id": "PI"}}))
    connector.acknowledge_incident({"incident_id": "PI"})
    assert transport.requests[0].method == "PUT"
    assert "/incidents/PI" in transport.requests[0].url
    assert transport.requests[0].headers["From"] == "me@example.com"


def test_pagerduty_list_services_summary() -> None:
    connector, transport = _pagerduty()
    transport.enqueue(
        json_response(
            {
                "services": [
                    {
                        "id": "PS",
                        "name": "API",
                        "description": "Main API",
                        "status": "active",
                    }
                ]
            }
        )
    )
    result = connector.list_services()
    assert result["services"][0]["service_ref"] == "service_1"
    assert result["services"][0]["name"] == "API"
    assert "service_id" not in result["services"][0]


def test_pagerduty_list_schedules_summary() -> None:
    connector, transport = _pagerduty()
    transport.enqueue(
        json_response(
            {
                "schedules": [
                    {
                        "id": "PSCHED",
                        "name": "Primary",
                        "description": "Primary on-call",
                        "time_zone": "UTC",
                    }
                ]
            }
        )
    )
    result = connector.list_schedules()
    assert result["schedules"][0]["schedule_ref"] == "schedule_1"
    assert "schedule_id" not in result["schedules"][0]


def test_pagerduty_list_oncalls_summary() -> None:
    connector, transport = _pagerduty()
    transport.enqueue(
        json_response(
            {
                "oncalls": [
                    {
                        "user": {"id": "PU", "summary": "Alice"},
                        "schedule": {"id": "PSCHED", "summary": "Primary"},
                        "escalation_level": 1,
                        "start": "2026-05-16T00:00:00Z",
                        "end": "2026-05-17T00:00:00Z",
                    }
                ]
            }
        )
    )
    result = connector.list_on_calls()
    assert result["oncalls"][0]["oncall_ref"] == "oncall_1"
    assert result["oncalls"][0]["user_name"] == "Alice"
    assert result["oncalls"][0]["schedule_name"] == "Primary"
    assert "user_id" not in result["oncalls"][0]


def test_pagerduty_list_users_summary() -> None:
    connector, transport = _pagerduty()
    transport.enqueue(
        json_response(
            {
                "users": [
                    {
                        "id": "PU",
                        "name": "Alice",
                        "email": "alice@x.com",
                        "role": "responder",
                        "time_zone": "UTC",
                    }
                ]
            }
        )
    )
    result = connector.list_users()
    assert result["users"][0]["user_ref"] == "user_1"
    assert result["users"][0]["email"] == "alice@x.com"
    assert "user_id" not in result["users"][0]


# MARK: - Agent-ready summaries (New Relic)


def test_new_relic_list_alert_policies_summary() -> None:
    connector, transport = _new_relic()
    transport.enqueue(
        json_response(
            {
                "policies": [
                    {
                        "id": 7,
                        "name": "Errors",
                        "incident_preference": "PER_POLICY",
                        "created_at": 1234,
                    }
                ]
            }
        )
    )
    result = connector.list_alert_policies()
    assert result["alerts"][0]["alert_ref"] == "alert_1"
    assert result["alerts"][0]["name"] == "Errors"
    assert "policy_id" not in result["alerts"][0]

    transport.enqueue(json_response({"policies": [{"id": 7, "name": "x"}]}))
    result = connector.list_alert_policies(include_ids=True)
    assert result["alerts"][0]["policy_id"] == 7


def test_new_relic_list_applications_summary() -> None:
    connector, transport = _new_relic()
    transport.enqueue(
        json_response(
            {
                "applications": [
                    {
                        "id": 99,
                        "name": "API",
                        "language": "python",
                        "health_status": "green",
                        "reporting": True,
                    }
                ]
            }
        )
    )
    result = connector.list_applications()
    assert result["applications"][0]["app_ref"] == "app_1"
    assert "application_id" not in result["applications"][0]


def test_new_relic_destructive_marked() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _new_relic()
    opts = get_toolify_options(connector.delete_alert_policy)
    assert opts is not None and opts.destructive is True


def test_new_relic_delete_alert_policy_accepts_dict() -> None:
    connector, transport = _new_relic()
    transport.enqueue(json_response({"deleted": True}))
    connector.delete_alert_policy({"policy_id": 5})
    assert "/v2/alerts_policies/5.json" in transport.requests[0].url


# MARK: - Agent-ready summaries (Splunk)


def test_splunk_list_indexes_summary() -> None:
    connector, transport = _splunk()
    transport.enqueue(
        json_response(
            {
                "entry": [
                    {
                        "name": "main",
                        "content": {
                            "totalEventCount": 1000,
                            "currentDBSizeMB": 100,
                            "disabled": False,
                        },
                    }
                ]
            }
        )
    )
    result = connector.list_indexes()
    assert result["indexes"][0]["index_ref"] == "index_1"
    assert result["indexes"][0]["name"] == "main"
    assert result["indexes"][0]["total_event_count"] == 1000


def test_splunk_list_saved_searches_summary() -> None:
    connector, transport = _splunk()
    transport.enqueue(
        json_response(
            {
                "entry": [
                    {
                        "name": "Errors",
                        "content": {
                            "search": "search index=main level=error",
                            "is_scheduled": True,
                            "cron_schedule": "*/5 * * * *",
                        },
                    }
                ]
            }
        )
    )
    result = connector.list_saved_searches()
    assert result["saved_searches"][0]["search_ref"] == "search_1"
    assert result["saved_searches"][0]["name"] == "Errors"
    assert result["saved_searches"][0]["is_scheduled"] is True


def test_splunk_cancel_search_job_marked_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _splunk()
    opts = get_toolify_options(connector.cancel_search_job)
    assert opts is not None and opts.destructive is True


# MARK: - Agent-ready summaries (Grafana)


def test_grafana_search_dashboards_summary_hides_uids() -> None:
    connector, transport = _grafana()
    transport.enqueue(
        json_response(
            [
                {
                    "uid": "abc",
                    "id": 1,
                    "title": "API Overview",
                    "type": "dash-db",
                    "url": "/d/abc",
                    "folderTitle": "Services",
                    "tags": ["api"],
                }
            ]
        )
    )
    result = connector.search_dashboards()
    assert result["dashboards"][0]["dashboard_ref"] == "dashboard_1"
    assert result["dashboards"][0]["title"] == "API Overview"
    assert "dashboard_uid" not in result["dashboards"][0]


def test_grafana_search_dashboards_include_ids() -> None:
    connector, transport = _grafana()
    transport.enqueue(json_response([{"uid": "abc", "id": 1, "title": "x"}]))
    result = connector.search_dashboards(include_ids=True)
    assert result["dashboards"][0]["dashboard_uid"] == "abc"


def test_grafana_list_folders_summary() -> None:
    connector, transport = _grafana()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 1,
                    "uid": "fldA",
                    "title": "Production",
                    "parentUid": "",
                }
            ]
        )
    )
    result = connector.list_folders()
    assert result["folders"][0]["folder_ref"] == "folder_1"
    assert result["folders"][0]["title"] == "Production"
    assert "folder_uid" not in result["folders"][0]


def test_grafana_list_alert_rules_summary() -> None:
    connector, transport = _grafana()
    transport.enqueue(
        json_response(
            [
                {
                    "uid": "ruleA",
                    "title": "High latency",
                    "folderUID": "fldA",
                    "ruleGroup": "rg",
                    "condition": "B",
                    "noDataState": "NoData",
                    "execErrState": "Alerting",
                }
            ]
        )
    )
    result = connector.list_alert_rules()
    assert result["alerts"][0]["alert_ref"] == "alert_1"
    assert result["alerts"][0]["title"] == "High latency"
    assert "alert_uid" not in result["alerts"][0]


def test_grafana_destructive_marked() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _grafana()
    opts = get_toolify_options(connector.delete_dashboard_by_uid)
    assert opts is not None and opts.destructive is True


def test_grafana_get_dashboard_accepts_dict() -> None:
    connector, transport = _grafana()
    transport.enqueue(json_response({"dashboard": {}}))
    connector.get_dashboard_by_uid({"uid": "abc"})
    assert "/api/dashboards/uid/abc" in transport.requests[0].url


# MARK: - Agent-ready summaries (Statuspage)


def test_statuspage_list_components_summary() -> None:
    connector, transport = _statuspage()
    transport.enqueue(
        json_response(
            [
                {
                    "id": "c1",
                    "name": "API",
                    "status": "operational",
                    "description": "REST API",
                    "group_id": "",
                }
            ]
        )
    )
    result = connector.list_components()
    assert result["components"][0]["component_ref"] == "component_1"
    assert result["components"][0]["name"] == "API"
    assert "component_id" not in result["components"][0]


def test_statuspage_list_incidents_summary() -> None:
    connector, transport = _statuspage()
    transport.enqueue(
        json_response(
            [
                {
                    "id": "i1",
                    "name": "Outage",
                    "status": "investigating",
                    "impact": "major",
                    "created_at": "2026-05-16T00:00:00Z",
                    "shortlink": "http://stspg.io/x",
                }
            ]
        )
    )
    result = connector.list_incidents()
    assert result["incidents"][0]["incident_ref"] == "incident_1"
    assert "incident_id" not in result["incidents"][0]


def test_statuspage_list_subscribers_summary() -> None:
    connector, transport = _statuspage()
    transport.enqueue(
        json_response(
            [
                {
                    "id": "s1",
                    "mode": "email",
                    "email": "alice@x.com",
                    "quarantined_at": None,
                }
            ]
        )
    )
    result = connector.list_subscribers()
    assert result["subscribers"][0]["subscriber_ref"] == "subscriber_1"
    assert result["subscribers"][0]["email"] == "alice@x.com"
    assert "subscriber_id" not in result["subscribers"][0]


def test_statuspage_destructive_marked() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _statuspage()
    opts = get_toolify_options(connector.delete_incident)
    assert opts is not None and opts.destructive is True


def test_statuspage_update_component_accepts_dict() -> None:
    connector, transport = _statuspage()
    transport.enqueue(json_response({"component": {}}))
    connector.update_component({"component_id": "c1"}, status="operational")
    assert "/components/c1" in transport.requests[0].url


# MARK: - Agent-ready summaries (Cloudflare)


def test_cloudflare_list_zones_summary_hides_ids() -> None:
    connector, transport = _cloudflare()
    transport.enqueue(
        json_response(
            {
                "result": [
                    {
                        "id": "zone-xxx",
                        "name": "example.com",
                        "status": "active",
                        "plan": {"name": "Pro"},
                    }
                ],
                "result_info": {"page": 1, "per_page": 25, "total_count": 1},
            }
        )
    )
    result = connector.list_zones()
    assert result["zones"][0]["zone_ref"] == "zone_1"
    assert result["zones"][0]["name"] == "example.com"
    assert result["zones"][0]["plan"] == "Pro"
    assert "zone_id" not in result["zones"][0]


def test_cloudflare_list_zones_include_ids() -> None:
    connector, transport = _cloudflare()
    transport.enqueue(json_response({"result": [{"id": "zone-xxx", "name": "example.com"}]}))
    result = connector.list_zones(include_ids=True)
    assert result["zones"][0]["zone_id"] == "zone-xxx"


def test_cloudflare_list_dns_records_summary() -> None:
    connector, transport = _cloudflare()
    transport.enqueue(
        json_response(
            {
                "result": [
                    {
                        "id": "rec-yyy",
                        "type": "A",
                        "name": "example.com",
                        "content": "1.2.3.4",
                        "ttl": 1,
                        "proxied": True,
                    }
                ],
                "result_info": {"page": 1, "per_page": 25, "total_count": 1},
            }
        )
    )
    result = connector.list_dns_records("zone-xxx")
    assert result["records"][0]["record_ref"] == "record_1"
    assert result["records"][0]["name"] == "example.com"
    assert "record_id" not in result["records"][0]


def test_cloudflare_list_workers_summary() -> None:
    connector, transport = _cloudflare()
    transport.enqueue(
        json_response(
            {
                "result": [
                    {
                        "id": "my-worker",
                        "created_on": "2026-05-16T00:00:00Z",
                        "modified_on": "2026-05-16T00:00:00Z",
                        "etag": "abc",
                    }
                ]
            }
        )
    )
    result = connector.list_workers("acct")
    assert result["workers"][0]["worker_ref"] == "worker_1"
    assert result["workers"][0]["name"] == "my-worker"


def test_cloudflare_list_r2_buckets_summary() -> None:
    connector, transport = _cloudflare()
    transport.enqueue(
        json_response(
            {
                "result": {
                    "buckets": [
                        {
                            "name": "my-bucket",
                            "creation_date": "2026-05-16T00:00:00Z",
                            "location": "WEUR",
                        }
                    ]
                }
            }
        )
    )
    result = connector.list_r2_buckets("acct")
    assert result["buckets"][0]["bucket_ref"] == "bucket_1"
    assert result["buckets"][0]["name"] == "my-bucket"


def test_cloudflare_destructive_marked() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _cloudflare()
    opts = get_toolify_options(connector.delete_dns_record)
    assert opts is not None and opts.destructive is True


def test_cloudflare_update_dns_record_accepts_dicts() -> None:
    connector, transport = _cloudflare()
    transport.enqueue(json_response({"result": {"id": "rec"}}))
    connector.update_dns_record(
        zone_id={"zone_id": "z"},
        record_id={"record_id": "r"},
        ttl=300,
    )
    assert "/zones/z/dns_records/r" in transport.requests[0].url


# MARK: - Agent-ready summaries (Kubernetes)


def test_kubernetes_list_pods_summary_hides_uids() -> None:
    connector, transport = _k8s()
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "metadata": {
                            "name": "web-1",
                            "namespace": "default",
                            "uid": "uuid-xxx",
                            "resourceVersion": "100",
                        },
                        "status": {
                            "phase": "Running",
                            "startTime": "2026-05-16T00:00:00Z",
                            "containerStatuses": [
                                {"ready": True},
                                {"ready": True},
                            ],
                        },
                        "spec": {"nodeName": "node-A"},
                    }
                ]
            }
        )
    )
    result = connector.list_pods(namespace="default")
    assert result["pods"][0]["pod_ref"] == "pod_1"
    assert result["pods"][0]["name"] == "web-1"
    assert result["pods"][0]["namespace"] == "default"
    assert result["pods"][0]["phase"] == "Running"
    assert result["pods"][0]["ready"] == "2/2"
    assert result["pods"][0]["node"] == "node-A"
    assert "uid" not in result["pods"][0]


def test_kubernetes_list_pods_include_ids() -> None:
    connector, transport = _k8s()
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "metadata": {
                            "name": "web-1",
                            "namespace": "default",
                            "uid": "uuid-xxx",
                            "resourceVersion": "100",
                        },
                        "status": {"phase": "Running"},
                    }
                ]
            }
        )
    )
    result = connector.list_pods(namespace="default", include_ids=True)
    assert result["pods"][0]["uid"] == "uuid-xxx"


def test_kubernetes_list_deployments_summary() -> None:
    connector, transport = _k8s()
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "metadata": {"name": "api", "namespace": "default", "uid": "u-1"},
                        "spec": {"replicas": 3},
                        "status": {"readyReplicas": 3, "availableReplicas": 3},
                    }
                ]
            }
        )
    )
    result = connector.list_deployments(namespace="default")
    assert result["deployments"][0]["deployment_ref"] == "deployment_1"
    assert result["deployments"][0]["name"] == "api"
    assert result["deployments"][0]["replicas"] == 3
    assert "uid" not in result["deployments"][0]


def test_kubernetes_list_services_summary() -> None:
    connector, transport = _k8s()
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "metadata": {"name": "api", "namespace": "default", "uid": "u-svc"},
                        "spec": {
                            "type": "ClusterIP",
                            "clusterIP": "10.0.0.1",
                            "ports": [
                                {
                                    "name": "http",
                                    "port": 80,
                                    "targetPort": 8080,
                                    "protocol": "TCP",
                                }
                            ],
                        },
                    }
                ]
            }
        )
    )
    result = connector.list_services(namespace="default")
    assert result["services"][0]["service_ref"] == "service_1"
    assert result["services"][0]["name"] == "api"
    assert result["services"][0]["type"] == "ClusterIP"
    assert result["services"][0]["ports"][0]["port"] == 80


def test_kubernetes_list_namespaces_summary() -> None:
    connector, transport = _k8s()
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "metadata": {
                            "name": "default",
                            "uid": "ns-uid",
                            "creationTimestamp": "2026-05-16T00:00:00Z",
                        },
                        "status": {"phase": "Active"},
                    }
                ]
            }
        )
    )
    result = connector.list_namespaces()
    assert result["namespaces"][0]["namespace_ref"] == "namespace_1"
    assert result["namespaces"][0]["name"] == "default"
    assert result["namespaces"][0]["phase"] == "Active"
    assert "uid" not in result["namespaces"][0]


def test_kubernetes_destructive_marked() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _k8s()
    opts = get_toolify_options(connector.delete_pod)
    assert opts is not None and opts.destructive is True
