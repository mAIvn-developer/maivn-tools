"""Tests for ETL / data-movement connectors.

Fivetran, Airbyte, dbt Cloud, Hightouch, Census, Stitch.
"""
# pyright: strict

from __future__ import annotations

import pytest
from maivn._internal.utils.toolset import get_toolify_options

from maivn_tools.connectors.airbyte import AirbyteToolSet
from maivn_tools.connectors.census import CensusToolSet
from maivn_tools.connectors.dbt_cloud import DbtCloudToolSet
from maivn_tools.connectors.fivetran import FivetranToolSet
from maivn_tools.connectors.hightouch import HightouchToolSet
from maivn_tools.connectors.stitch import StitchToolSet
from maivn_tools.testing import MockTransport, json_response

# MARK: - Fivetran


def _fivetran() -> tuple[FivetranToolSet, MockTransport]:
    transport = MockTransport()
    return (
        FivetranToolSet(api_key="k", api_secret="s", transport=transport),
        transport,
    )


def test_fivetran_requires_args() -> None:
    with pytest.raises(ValueError):
        FivetranToolSet(api_key="", api_secret="s")
    with pytest.raises(ValueError):
        FivetranToolSet(api_key="k", api_secret="")


def test_fivetran_endpoints() -> None:
    connector, transport = _fivetran()
    for _ in range(11):
        transport.enqueue(json_response({"data": {}}))
    connector.list_groups(limit=10, cursor="cur")
    connector.list_connectors("g1", limit=10, cursor="cur")
    connector.get_connector("c1")
    connector.update_connector(
        "c1",
        paused=True,
        sync_frequency=60,
        schedule_type="auto",
        config={"k": "v"},
    )
    connector.trigger_sync("c1", force=True)
    connector.resync_connector("c1", scope={"s": ["t"]})
    connector.delete_connector("c1")
    connector.get_connector_schemas("c1")
    connector.list_destinations(limit=10, cursor="cur")
    connector.get_destination("d1")
    connector.list_users(limit=10, cursor="cur")
    assert transport.requests[3].method == "PATCH"
    assert transport.requests[6].method == "DELETE"
    with pytest.raises(ValueError):
        connector.list_connectors("")
    with pytest.raises(ValueError):
        connector.get_connector("")
    with pytest.raises(ValueError):
        connector.update_connector("")
    with pytest.raises(ValueError):
        connector.update_connector("c1")
    with pytest.raises(ValueError):
        connector.trigger_sync("")
    with pytest.raises(ValueError):
        connector.resync_connector("")
    with pytest.raises(ValueError):
        connector.delete_connector("")
    with pytest.raises(ValueError):
        connector.get_connector_schemas("")
    with pytest.raises(ValueError):
        connector.get_destination("")


def test_fivetran_list_groups_returns_compact_summaries() -> None:
    connector, transport = _fivetran()
    transport.enqueue(
        json_response(
            {
                "data": {
                    "items": [
                        {"id": "grp_alpha", "name": "Alpha", "created_at": "2026-01-01"},
                        {"id": "grp_beta", "name": "Beta", "created_at": "2026-02-01"},
                    ],
                    "next_cursor": "cur-2",
                }
            }
        )
    )
    result = connector.list_groups()
    assert result["groups"][0] == {
        "group_ref": "group_1",
        "name": "Alpha",
        "created_at": "2026-01-01",
    }
    assert "group_id" not in result["groups"][0]
    assert result["next_cursor"] == "cur-2"


def test_fivetran_list_groups_include_ids_opts_in() -> None:
    connector, transport = _fivetran()
    transport.enqueue(
        json_response(
            {
                "data": {
                    "items": [{"id": "grp_alpha", "name": "Alpha"}],
                }
            }
        )
    )
    result = connector.list_groups(include_ids=True)
    assert result["groups"][0]["group_id"] == "grp_alpha"


def test_fivetran_list_connectors_returns_compact_summaries() -> None:
    connector, transport = _fivetran()
    transport.enqueue(
        json_response(
            {
                "data": {
                    "items": [
                        {
                            "id": "conn_x",
                            "schema": "stripe",
                            "service": "stripe",
                            "group_id": "grp_alpha",
                            "paused": False,
                            "schedule_type": "auto",
                            "sync_frequency": 60,
                            "status": {"setup_state": "connected", "sync_state": "scheduled"},
                            "succeeded_at": "2026-05-16T00:00:00Z",
                            "failed_at": None,
                        }
                    ]
                }
            }
        )
    )
    result = connector.list_connectors("grp_alpha")
    item = result["connectors"][0]
    assert item["connector_ref"] == "connector_1"
    assert item["name"] == "stripe"
    assert item["service"] == "stripe"
    assert item["setup_state"] == "connected"
    assert item["sync_state"] == "scheduled"
    assert "connector_id" not in item


def test_fivetran_list_connectors_accepts_group_dict() -> None:
    connector, transport = _fivetran()
    transport.enqueue(json_response({"data": {"items": []}}))
    connector.list_connectors({"group_ref": "group_1", "group_id": "grp_alpha"})
    assert transport.requests[0].url.endswith("/groups/grp_alpha/connectors")


def test_fivetran_update_connector_accepts_dict() -> None:
    connector, transport = _fivetran()
    transport.enqueue(json_response({"id": "conn_x"}))
    connector.update_connector(
        {"connector_ref": "connector_1", "connector_id": "conn_x"},
        paused=True,
    )
    assert transport.requests[0].url.endswith("/connectors/conn_x")
    assert transport.requests[0].method == "PATCH"


def test_fivetran_delete_connector_is_destructive() -> None:
    connector = FivetranToolSet(api_key="k", api_secret="s")
    delete_opts = get_toolify_options(connector.delete_connector)
    assert delete_opts is not None and delete_opts.destructive is True
    trigger_opts = get_toolify_options(connector.trigger_sync)
    assert trigger_opts is not None and trigger_opts.destructive is False


def test_fivetran_raw_mode_returns_unfiltered_payload() -> None:
    connector, transport = _fivetran()
    payload = {"data": {"items": [{"id": "grp_alpha", "name": "Alpha"}]}, "code": "OK"}
    transport.enqueue(json_response(payload))
    result = connector.list_groups(raw=True)
    assert result == payload


# MARK: - Airbyte


def _airbyte() -> tuple[AirbyteToolSet, MockTransport]:
    transport = MockTransport()
    return AirbyteToolSet(access_token="t", transport=transport), transport


def test_airbyte_requires_token() -> None:
    with pytest.raises(ValueError):
        AirbyteToolSet(access_token="")


def test_airbyte_endpoints() -> None:
    connector, transport = _airbyte()
    for _ in range(13):
        transport.enqueue(json_response({"data": []}))
    connector.list_workspaces(limit=10, offset=0)
    connector.list_sources(workspace_ids=["w1"], limit=10, offset=0)
    connector.get_source("s1")
    connector.create_source(
        workspace_id="w1",
        name="S",
        source_type="postgres",
        configuration={"host": "x"},
    )
    connector.delete_source("s1")
    connector.list_destinations(workspace_ids=["w1"])
    connector.list_connections(workspace_ids=["w1"])
    connector.get_connection("conn1")
    connector.create_connection(
        source_id="s1",
        destination_id="d1",
        name="C",
        configurations={"sync": {}},
        schedule={"scheduleType": "manual"},
    )
    connector.trigger_sync("conn1")
    connector.trigger_reset("conn1")
    connector.list_jobs(connection_id="conn1", status="running", limit=10, offset=0)
    connector.get_job(123)
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_source("")
    with pytest.raises(ValueError):
        connector.create_source(workspace_id="", name="x", source_type="t", configuration={})
    with pytest.raises(ValueError):
        connector.delete_source("")
    with pytest.raises(ValueError):
        connector.get_connection("")
    with pytest.raises(ValueError):
        connector.create_connection(source_id="", destination_id="d", name="x")
    with pytest.raises(ValueError):
        connector.trigger_sync("")
    with pytest.raises(ValueError):
        connector.trigger_reset("")
    with pytest.raises(ValueError):
        connector.get_job(0)


def test_airbyte_cancel_job() -> None:
    connector, transport = _airbyte()
    transport.enqueue(json_response({"id": 1}))
    connector.cancel_job(1)
    assert transport.requests[0].method == "DELETE"
    with pytest.raises(ValueError):
        connector.cancel_job(0)


def test_airbyte_list_connections_returns_compact_summaries() -> None:
    connector, transport = _airbyte()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "connectionId": "conn_1",
                        "name": "Stripe -> Snowflake",
                        "sourceName": "Stripe",
                        "destinationName": "Snowflake",
                        "scheduleType": "cron",
                        "status": "active",
                    }
                ]
            }
        )
    )
    result = connector.list_connections()
    item = result["connections"][0]
    assert item["connection_ref"] == "connection_1"
    assert item["source"] == "Stripe"
    assert item["destination"] == "Snowflake"
    assert item["schedule"] == "cron"
    assert "connection_id" not in item


def test_airbyte_list_connections_include_ids() -> None:
    connector, transport = _airbyte()
    transport.enqueue(json_response({"data": [{"connectionId": "conn_1", "name": "x"}]}))
    result = connector.list_connections(include_ids=True)
    assert result["connections"][0]["connection_id"] == "conn_1"


def test_airbyte_trigger_sync_accepts_connection_dict() -> None:
    connector, transport = _airbyte()
    transport.enqueue(json_response({"jobId": 7}))
    connector.trigger_sync({"connection_ref": "connection_1", "connection_id": "conn_1"})
    assert transport.requests[0].json_body == {"connectionId": "conn_1", "jobType": "sync"}


def test_airbyte_destructive_flags() -> None:
    connector = AirbyteToolSet(access_token="t")
    delete_opts = get_toolify_options(connector.delete_source)
    assert delete_opts is not None and delete_opts.destructive is True
    cancel_opts = get_toolify_options(connector.cancel_job)
    assert cancel_opts is not None and cancel_opts.destructive is True
    trigger_opts = get_toolify_options(connector.trigger_sync)
    assert trigger_opts is not None and trigger_opts.destructive is False


# MARK: - dbt Cloud


def _dbt() -> tuple[DbtCloudToolSet, MockTransport]:
    transport = MockTransport()
    return (
        DbtCloudToolSet(
            account_id=1,
            api_token="t",
            transport=transport,
        ),
        transport,
    )


def test_dbt_requires_args() -> None:
    with pytest.raises(ValueError):
        DbtCloudToolSet(account_id=0, api_token="t")
    with pytest.raises(ValueError):
        DbtCloudToolSet(account_id=1, api_token="")


def test_dbt_endpoints() -> None:
    connector, transport = _dbt()
    for _ in range(11):
        transport.enqueue(json_response({"data": []}))
    connector.list_projects(limit=10, offset=0)
    connector.get_project(1)
    connector.list_environments(project_id=1)
    connector.list_jobs(project_id=1)
    connector.get_job(2)
    connector.trigger_job_run(
        2,
        cause="api",
        git_branch="main",
        git_sha="abc",
        schema_override="test",
        steps_override=["dbt build"],
    )
    connector.list_runs(job_definition_id=2, status=10)
    connector.get_run(3, include_related=["job"])
    connector.cancel_run(3)
    connector.list_run_artifacts(3)
    connector.get_run_artifact(run_id=3, path="manifest.json")
    assert transport.requests[0].headers["Authorization"] == "Token t"
    with pytest.raises(ValueError):
        connector.get_project(0)
    with pytest.raises(ValueError):
        connector.get_job(0)
    with pytest.raises(ValueError):
        connector.trigger_job_run(0, cause="x")
    with pytest.raises(ValueError):
        connector.trigger_job_run(1, cause="")
    with pytest.raises(ValueError):
        connector.get_run(0)
    with pytest.raises(ValueError):
        connector.cancel_run(0)
    with pytest.raises(ValueError):
        connector.list_run_artifacts(0)
    with pytest.raises(ValueError):
        connector.get_run_artifact(run_id=0, path="x")


def test_dbt_list_runs_returns_human_status() -> None:
    connector, transport = _dbt()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": 99,
                        "status": 10,
                        "started_at": "2026-05-16T00:00:00Z",
                        "finished_at": "2026-05-16T00:05:00Z",
                        "duration_humanized": "5 minutes",
                        "trigger": {"cause": "scheduled"},
                    }
                ]
            }
        )
    )
    result = connector.list_runs()
    item = result["runs"][0]
    assert item["run_ref"] == "run_1"
    assert item["status"] == "success"
    assert item["trigger_cause"] == "scheduled"
    assert "run_id" not in item


def test_dbt_list_runs_include_ids() -> None:
    connector, transport = _dbt()
    transport.enqueue(json_response({"data": [{"id": 99, "status": 10}]}))
    result = connector.list_runs(include_ids=True)
    assert result["runs"][0]["run_id"] == 99


def test_dbt_trigger_job_run_accepts_job_dict() -> None:
    connector, transport = _dbt()
    transport.enqueue(json_response({"data": {"id": 100}}))
    connector.trigger_job_run({"job_ref": "job_1", "job_id": 42}, cause="manual")
    assert transport.requests[0].url.endswith("/jobs/42/run/")


def test_dbt_cancel_run_is_destructive() -> None:
    connector = DbtCloudToolSet(account_id=1, api_token="t")
    cancel_opts = get_toolify_options(connector.cancel_run)
    assert cancel_opts is not None and cancel_opts.destructive is True
    trigger_opts = get_toolify_options(connector.trigger_job_run)
    assert trigger_opts is not None and trigger_opts.destructive is False


# MARK: - Hightouch


def _hightouch() -> tuple[HightouchToolSet, MockTransport]:
    transport = MockTransport()
    return HightouchToolSet(api_key="k", transport=transport), transport


def test_hightouch_requires_key() -> None:
    with pytest.raises(ValueError):
        HightouchToolSet(api_key="")


def test_hightouch_endpoints() -> None:
    connector, transport = _hightouch()
    for _ in range(9):
        transport.enqueue(json_response({"data": []}))
    connector.list_sources(page=0, per_page=10)
    connector.get_source("s1")
    connector.list_destinations(page=0, per_page=10)
    connector.list_models(page=0, per_page=10)
    connector.get_model("m1")
    connector.list_syncs(page=0, per_page=10)
    connector.get_sync("sync1")
    connector.trigger_sync("sync1", full_resync=True)
    connector.list_sync_runs("sync1", page=0, per_page=10)
    with pytest.raises(ValueError):
        connector.get_source("")
    with pytest.raises(ValueError):
        connector.get_model("")
    with pytest.raises(ValueError):
        connector.get_sync("")
    with pytest.raises(ValueError):
        connector.trigger_sync("")
    with pytest.raises(ValueError):
        connector.list_sync_runs("")


def test_hightouch_get_sync_run() -> None:
    connector, transport = _hightouch()
    transport.enqueue(json_response({"data": [{"id": "r1"}]}))
    connector.get_sync_run(sync_id="s1", run_id="r1")
    with pytest.raises(ValueError):
        connector.get_sync_run(sync_id="", run_id="r")


def test_hightouch_list_syncs_returns_compact_summaries() -> None:
    connector, transport = _hightouch()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "sync_1",
                        "slug": "users-to-segment",
                        "name": "Users to Segment",
                        "destinationName": "Segment",
                        "modelName": "Active users",
                        "schedule": {"type": "cron"},
                        "disabled": False,
                        "lastRunStatus": "success",
                    }
                ]
            }
        )
    )
    result = connector.list_syncs()
    item = result["syncs"][0]
    assert item["sync_ref"] == "sync_1"
    assert item["name"] == "Users to Segment"
    assert item["destination"] == "Segment"
    assert item["schedule"] == "cron"
    assert "sync_id" not in item


def test_hightouch_list_syncs_include_ids() -> None:
    connector, transport = _hightouch()
    transport.enqueue(json_response({"data": [{"id": "sync_1", "slug": "x"}]}))
    result = connector.list_syncs(include_ids=True)
    assert result["syncs"][0]["sync_id"] == "sync_1"


def test_hightouch_trigger_sync_accepts_sync_dict() -> None:
    connector, transport = _hightouch()
    transport.enqueue(json_response({"id": "run_1"}))
    connector.trigger_sync({"sync_ref": "sync_1", "sync_id": "sync_1"})
    assert transport.requests[0].url.endswith("/syncs/sync_1/trigger")


# MARK: - Census


def _census() -> tuple[CensusToolSet, MockTransport]:
    transport = MockTransport()
    return CensusToolSet(secret_token="t", transport=transport), transport


def test_census_requires_token() -> None:
    with pytest.raises(ValueError):
        CensusToolSet(secret_token="")


def test_census_endpoints() -> None:
    connector, transport = _census()
    for _ in range(10):
        transport.enqueue(json_response({"data": []}))
    connector.list_sources()
    connector.get_source(1)
    connector.list_destinations()
    connector.list_models(order="id", page=1, per_page=10)
    connector.get_model(1)
    connector.list_syncs(order="id", page=1, per_page=10)
    connector.get_sync(1)
    connector.trigger_sync(1, force_full_sync=True)
    connector.list_sync_runs(sync_id=1, order="-id", page=1, per_page=10)
    connector.get_sync_run(1)
    with pytest.raises(ValueError):
        connector.get_source(0)
    with pytest.raises(ValueError):
        connector.get_model(0)
    with pytest.raises(ValueError):
        connector.get_sync(0)
    with pytest.raises(ValueError):
        connector.trigger_sync(0)
    with pytest.raises(ValueError):
        connector.get_sync_run(0)


def test_census_list_syncs_returns_compact_summaries() -> None:
    connector, transport = _census()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": 42,
                        "label": "Users to Salesforce",
                        "operation": "upsert",
                        "paused": False,
                        "schedule": {"frequency": "hourly"},
                        "destination_attributes": {"connection_id": "dest-1"},
                        "last_sync_run": {"status": "completed"},
                    }
                ]
            }
        )
    )
    result = connector.list_syncs()
    item = result["syncs"][0]
    assert item["sync_ref"] == "sync_1"
    assert item["name"] == "Users to Salesforce"
    assert item["operation"] == "upsert"
    assert item["last_sync_status"] == "completed"
    assert "sync_id" not in item


def test_census_list_syncs_include_ids() -> None:
    connector, transport = _census()
    transport.enqueue(json_response({"data": [{"id": 42, "label": "x"}]}))
    result = connector.list_syncs(include_ids=True)
    assert result["syncs"][0]["sync_id"] == 42


def test_census_trigger_sync_accepts_sync_dict() -> None:
    connector, transport = _census()
    transport.enqueue(json_response({"data": {"id": 100}}))
    connector.trigger_sync({"sync_ref": "sync_1", "sync_id": 42})
    assert transport.requests[0].url.endswith("/syncs/42/trigger")


# MARK: - Stitch


def _stitch() -> tuple[StitchToolSet, MockTransport]:
    transport = MockTransport()
    return StitchToolSet(access_token="t", transport=transport), transport


def test_stitch_requires_args() -> None:
    with pytest.raises(ValueError):
        StitchToolSet(access_token="")
    with pytest.raises(ValueError):
        StitchToolSet(access_token="t", region="bogus")


def test_stitch_endpoints() -> None:
    connector, transport = _stitch()
    for _ in range(9):
        transport.enqueue(json_response({"id": 1}))
    connector.list_sources()
    connector.get_source(1)
    connector.create_source(
        type="postgres",
        display_name="DB",
        properties={"host": "x"},
    )
    connector.update_source(1, display_name="DB2", properties={"x": 1})
    connector.delete_source(1)
    connector.list_streams(1)
    connector.update_stream(source_id=1, tap_stream_id="public-users", metadata=[{"x": 1}])
    connector.get_destination()
    connector.trigger_extraction(1)
    assert transport.requests[3].method == "PUT"
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_source(0)
    with pytest.raises(ValueError):
        connector.create_source(type="", display_name="x")
    with pytest.raises(ValueError):
        connector.update_source(0, display_name="x")
    with pytest.raises(ValueError):
        connector.update_source(1)
    with pytest.raises(ValueError):
        connector.delete_source(0)
    with pytest.raises(ValueError):
        connector.list_streams(0)
    with pytest.raises(ValueError):
        connector.update_stream(source_id=0, tap_stream_id="public-users", metadata=[{}])
    with pytest.raises(ValueError):
        connector.trigger_extraction(0)


def test_stitch_replication_summary() -> None:
    connector, transport = _stitch()
    transport.enqueue(json_response({"id": 1}))
    connector.get_replication_summary(1)
    with pytest.raises(ValueError):
        connector.get_replication_summary(0)


def test_stitch_list_sources_returns_compact_summaries() -> None:
    connector, transport = _stitch()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 11,
                    "display_name": "Postgres prod",
                    "type": "platform.postgres",
                    "schedule": {"frequency_in_minutes": 30},
                    "paused_at": None,
                    "current_status": {"status": "running"},
                }
            ]
        )
    )
    result = connector.list_sources()
    item = result["sources"][0]
    assert item["source_ref"] == "source_1"
    assert item["name"] == "Postgres prod"
    assert item["schedule"] == 30
    assert item["paused"] is False
    assert "source_id" not in item


def test_stitch_list_sources_include_ids() -> None:
    connector, transport = _stitch()
    transport.enqueue(json_response([{"id": 11, "display_name": "x"}]))
    result = connector.list_sources(include_ids=True)
    assert result["sources"][0]["source_id"] == 11


def test_stitch_trigger_extraction_accepts_source_dict() -> None:
    connector, transport = _stitch()
    transport.enqueue(json_response({"ok": True}))
    connector.trigger_extraction({"source_ref": "source_1", "source_id": 11})
    assert transport.requests[0].url.endswith("/sources/11/sync")


def test_stitch_delete_source_is_destructive() -> None:
    connector = StitchToolSet(access_token="t")
    delete_opts = get_toolify_options(connector.delete_source)
    assert delete_opts is not None and delete_opts.destructive is True


# MARK: - Permission coverage across ETL toolsets


def test_etl_toolsets_have_permissions_on_every_tool() -> None:
    for connector in (
        FivetranToolSet(api_key="k", api_secret="s"),
        AirbyteToolSet(access_token="t"),
        DbtCloudToolSet(account_id=1, api_token="t"),
        HightouchToolSet(api_key="k"),
        CensusToolSet(secret_token="t"),
        StitchToolSet(access_token="t"),
    ):
        cls = type(connector)
        for attr in dir(cls):
            if attr.startswith("_"):
                continue
            method = getattr(cls, attr, None)
            opts = get_toolify_options(method) if callable(method) else None
            if opts is None:
                continue
            assert opts.permissions is not None, f"{cls.__name__}.{attr} missing PermissionSet"
