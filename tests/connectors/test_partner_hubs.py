# pyright: strict
from __future__ import annotations

import pytest
from maivn._internal.utils.toolset import get_toolify_options

from maivn_tools.connectors.partner_hubs import (
    ComposioToolSet,
    MakeToolSet,
    N8nToolSet,
    PipedreamToolSet,
    WorkatoToolSet,
    ZapierConnector,
)
from maivn_tools.core import PermissionFlag
from maivn_tools.testing import MockTransport, json_response

# MARK: - Zapier (builder-style, stays on tools())


def test_zapier_webhook_only_no_tools_without_urls() -> None:
    connector = ZapierConnector()
    assert connector.tools() == []


def test_zapier_webhook_trigger_posts_payload() -> None:
    transport = MockTransport()
    transport.enqueue(json_response({}))
    connector = ZapierConnector(
        webhook_urls={"new_lead": "https://hooks.zapier.com/new-lead"},
        transport=transport,
    )
    tools = connector.tools()
    assert len(tools) == 1
    trigger = tools[0]
    assert trigger.__name__ == "trigger_new_lead"
    assert trigger.permissions.includes(PermissionFlag.WRITE)
    result = trigger({"name": "Alice"})
    assert result["delivered"] is True
    assert transport.requests[0].json_body == {"name": "Alice"}


def test_zapier_webhook_trigger_has_descriptive_docstring() -> None:
    connector = ZapierConnector(
        webhook_urls={"new_lead": "https://hooks.zapier.com/new-lead"},
    )
    trigger = connector.tools()[0]
    assert trigger.__doc__ is not None
    assert "new_lead" in trigger.__doc__
    assert "Zapier" in trigger.__doc__
    assert "payload" in trigger.__doc__.lower()


# MARK: - Workato


def _workato() -> tuple[WorkatoToolSet, MockTransport]:
    transport = MockTransport()
    return WorkatoToolSet(api_token="wo-token", transport=transport), transport


def test_workato_validates_inputs() -> None:
    with pytest.raises(ValueError):
        WorkatoToolSet(api_token="")


def test_workato_list_recipes_sends_token_header() -> None:
    connector, transport = _workato()
    transport.enqueue(json_response([]))
    connector.list_recipes(page=2, per_page=10)
    request = transport.requests[0]
    assert request.headers["Authorization"] == "Bearer wo-token"
    assert request.params == {"page": 2, "per_page": 10}


def test_workato_list_recipes_returns_compact_summaries() -> None:
    connector, transport = _workato()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 11,
                    "name": "Slack notifier",
                    "running": True,
                    "stopped_cause": None,
                    "last_run_at": "2026-05-16T01:00:00Z",
                    "created_at": "2026-01-01",
                }
            ]
        )
    )
    result = connector.list_recipes()
    item = result["recipes"][0]
    assert item["recipe_ref"] == "recipe_1"
    assert item["name"] == "Slack notifier"
    assert item["running"] is True
    assert "recipe_id" not in item


def test_workato_list_recipes_include_ids() -> None:
    connector, transport = _workato()
    transport.enqueue(json_response([{"id": 11, "name": "X"}]))
    result = connector.list_recipes(include_ids=True)
    assert result["recipes"][0]["recipe_id"] == 11


def test_workato_list_jobs_accepts_recipe_dict() -> None:
    connector, transport = _workato()
    transport.enqueue(json_response([]))
    connector.list_jobs({"recipe_ref": "recipe_1", "recipe_id": 11})
    assert transport.requests[0].url.endswith("/recipes/11/jobs")


def test_workato_list_jobs_validates_status() -> None:
    connector, _ = _workato()
    with pytest.raises(ValueError):
        connector.list_jobs(recipe_id=1, status="bogus")


def test_workato_trigger_validates_url() -> None:
    connector, _ = _workato()
    with pytest.raises(ValueError):
        connector.run_recipe_trigger(trigger_url="")


# MARK: - Pipedream


def _pipedream() -> tuple[PipedreamToolSet, MockTransport]:
    transport = MockTransport()
    return PipedreamToolSet(api_token="pd-token", transport=transport), transport


def test_pipedream_validates_token() -> None:
    with pytest.raises(ValueError):
        PipedreamToolSet(api_token="")


def test_pipedream_get_workflow_attaches_bearer() -> None:
    connector, transport = _pipedream()
    transport.enqueue(json_response({"id": "wf_abc"}))
    connector.get_workflow(workflow_id="wf_abc", org_id="o-1")
    request = transport.requests[0]
    assert request.headers["Authorization"] == "Bearer pd-token"
    assert request.params == {"org_id": "o-1"}


def test_pipedream_get_workflow_accepts_workflow_dict() -> None:
    connector, transport = _pipedream()
    transport.enqueue(json_response({"id": "wf_abc"}))
    connector.get_workflow({"workflow_ref": "workflow_1", "workflow_id": "wf_abc"})
    assert transport.requests[0].url.endswith("/workflows/wf_abc")


def test_pipedream_get_workflow_requires_id() -> None:
    connector, _ = _pipedream()
    with pytest.raises(ValueError):
        connector.get_workflow(workflow_id="")


def test_pipedream_invoke_http_trigger_validates_url() -> None:
    connector, _ = _pipedream()
    with pytest.raises(ValueError):
        connector.invoke_http_trigger(trigger_url="")


# MARK: - Make


def _make() -> tuple[MakeToolSet, MockTransport]:
    transport = MockTransport()
    return (
        MakeToolSet(
            api_token="mk-token",
            base_url="https://us1.make.com/api/v2",
            transport=transport,
        ),
        transport,
    )


def test_make_validates_inputs() -> None:
    with pytest.raises(ValueError):
        MakeToolSet(api_token="", base_url="https://x")
    with pytest.raises(ValueError):
        MakeToolSet(api_token="t", base_url="")


def test_make_list_scenarios_attaches_token_header() -> None:
    connector, transport = _make()
    transport.enqueue(json_response({"scenarios": []}))
    connector.list_scenarios(team_id=42, limit=5)
    request = transport.requests[0]
    assert request.headers["Authorization"] == "Token mk-token"
    assert request.params == {"pg[limit]": 5, "pg[offset]": 0, "teamId": 42}


def test_make_list_scenarios_returns_compact_summaries() -> None:
    connector, transport = _make()
    transport.enqueue(
        json_response(
            {
                "scenarios": [
                    {
                        "id": 7,
                        "name": "Daily sales digest",
                        "isActive": True,
                        "scheduling": {"type": "cron"},
                        "lastEdit": "2026-05-16T00:00:00Z",
                        "teamId": 42,
                    }
                ]
            }
        )
    )
    result = connector.list_scenarios(team_id=42)
    item = result["scenarios"][0]
    assert item["scenario_ref"] == "scenario_1"
    assert item["name"] == "Daily sales digest"
    assert item["is_active"] is True
    assert item["scheduling"] == "cron"
    assert "scenario_id" not in item


def test_make_list_scenarios_include_ids() -> None:
    connector, transport = _make()
    transport.enqueue(json_response({"scenarios": [{"id": 7, "name": "x"}]}))
    result = connector.list_scenarios(team_id=42, include_ids=True)
    assert result["scenarios"][0]["scenario_id"] == 7


def test_make_get_scenario_accepts_scenario_dict() -> None:
    connector, transport = _make()
    transport.enqueue(json_response({"id": 7}))
    connector.get_scenario({"scenario_ref": "scenario_1", "scenario_id": 7})
    assert transport.requests[0].url.endswith("/scenarios/7")


def test_make_trigger_webhook_validates_url() -> None:
    connector, _ = _make()
    with pytest.raises(ValueError):
        connector.trigger_webhook(webhook_url="")


# MARK: - n8n


def _n8n() -> tuple[N8nToolSet, MockTransport]:
    transport = MockTransport()
    return (
        N8nToolSet(
            base_url="https://n8n.example.test",
            api_key="n8n-key",
            transport=transport,
        ),
        transport,
    )


def test_n8n_validates_inputs() -> None:
    with pytest.raises(ValueError):
        N8nToolSet(base_url="", api_key="k")
    with pytest.raises(ValueError):
        N8nToolSet(base_url="https://x", api_key="")


def test_n8n_list_workflows_serializes_filters() -> None:
    connector, transport = _n8n()
    transport.enqueue(json_response({"data": []}))
    connector.list_workflows(active=True, limit=10, cursor="c-1")
    request = transport.requests[0]
    assert request.headers["X-N8N-API-KEY"] == "n8n-key"
    assert request.params["active"] == "true"
    assert request.params["limit"] == 10
    assert request.params["cursor"] == "c-1"


def test_n8n_list_workflows_returns_compact_summaries() -> None:
    connector, transport = _n8n()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "wf_abc",
                        "name": "Daily backup",
                        "active": True,
                        "tags": [{"id": "t1", "name": "ops"}, {"id": "t2", "name": "backup"}],
                        "updatedAt": "2026-05-16T00:00:00Z",
                    }
                ],
                "nextCursor": "c-2",
            }
        )
    )
    result = connector.list_workflows()
    item = result["workflows"][0]
    assert item["workflow_ref"] == "workflow_1"
    assert item["name"] == "Daily backup"
    assert item["tags"] == ["ops", "backup"]
    assert "workflow_id" not in item
    assert result["next_cursor"] == "c-2"


def test_n8n_list_workflows_include_ids() -> None:
    connector, transport = _n8n()
    transport.enqueue(json_response({"data": [{"id": "wf_abc", "name": "x"}]}))
    result = connector.list_workflows(include_ids=True)
    assert result["workflows"][0]["workflow_id"] == "wf_abc"


def test_n8n_activate_workflow_accepts_workflow_dict() -> None:
    connector, transport = _n8n()
    transport.enqueue(json_response({}))
    connector.activate_workflow({"workflow_ref": "workflow_1", "workflow_id": "wf_abc"})
    assert transport.requests[0].url.endswith("/workflows/wf_abc/activate")


def test_n8n_activate_workflow_uses_correct_suffix() -> None:
    connector, transport = _n8n()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.activate_workflow(workflow_id="w-1", active=True)
    connector.activate_workflow(workflow_id="w-1", active=False)
    assert transport.requests[0].url.endswith("/workflows/w-1/activate")
    assert transport.requests[1].url.endswith("/workflows/w-1/deactivate")


def test_n8n_trigger_webhook_validates_url() -> None:
    connector, _ = _n8n()
    with pytest.raises(ValueError):
        connector.trigger_webhook(webhook_url="")


# MARK: - Composio


def _composio() -> tuple[ComposioToolSet, MockTransport]:
    transport = MockTransport()
    return ComposioToolSet(api_key="composio-key", transport=transport), transport


def test_composio_validates_api_key() -> None:
    with pytest.raises(ValueError):
        ComposioToolSet(api_key="")


def test_composio_list_apps_sends_api_key_header() -> None:
    connector, transport = _composio()
    transport.enqueue(json_response({"items": []}))
    connector.list_apps()
    assert transport.requests[0].headers["x-api-key"] == "composio-key"
    assert transport.requests[0].url.endswith("/v1/apps")


def test_composio_list_apps_returns_compact_summaries() -> None:
    connector, transport = _composio()
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "appId": "github-1",
                        "key": "github",
                        "name": "GitHub",
                        "description": "GitHub repo automation",
                        "categories": ["dev"],
                        "no_auth": False,
                    }
                ]
            }
        )
    )
    result = connector.list_apps()
    item = result["apps"][0]
    assert item["app_ref"] == "app_1"
    assert item["name"] == "GitHub"
    assert "app_id" not in item


def test_composio_list_apps_include_ids() -> None:
    connector, transport = _composio()
    transport.enqueue(
        json_response({"items": [{"appId": "github-1", "key": "github", "name": "GitHub"}]})
    )
    result = connector.list_apps(include_ids=True)
    item = result["apps"][0]
    assert item["app_id"] == "github-1"
    assert item["key"] == "github"


def test_composio_list_actions_returns_compact_summaries() -> None:
    connector, transport = _composio()
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "name": "github_create_issue",
                        "displayName": "Create issue",
                        "appName": "GitHub",
                        "description": "Open an issue in a repo.",
                    }
                ]
            }
        )
    )
    result = connector.list_actions()
    item = result["actions"][0]
    assert item["action_ref"] == "action_1"
    assert item["name"] == "Create issue"
    assert item["app"] == "GitHub"
    assert "action_name" not in item


def test_composio_list_actions_filters() -> None:
    connector, transport = _composio()
    transport.enqueue(json_response({"items": []}))
    connector.list_actions(app="github", use_case="bug-triage", limit=10)
    request = transport.requests[0]
    assert request.params == {"limit": 10, "app": "github", "useCase": "bug-triage"}


def test_composio_execute_action_accepts_dicts() -> None:
    connector, transport = _composio()
    transport.enqueue(json_response({"id": "exec-1"}))
    connector.execute_action(
        action_name={"action_ref": "action_1", "action_name": "github_create_issue"},
        connected_account_id={"connection_ref": "connection_1", "connection_id": "conn-1"},
        input={"title": "x"},
    )
    payload = transport.requests[0].json_body
    assert payload["connectedAccountId"] == "conn-1"
    assert payload["input"] == {"title": "x"}
    assert transport.requests[0].url.endswith("/actions/github_create_issue/execute")


def test_composio_execute_action_validates_inputs() -> None:
    connector, transport = _composio()
    with pytest.raises(ValueError):
        connector.execute_action(action_name="", connected_account_id="x")
    with pytest.raises(ValueError):
        connector.execute_action(action_name="x", connected_account_id="")
    transport.enqueue(json_response({"id": "exec-1"}))
    connector.execute_action(
        action_name="github_create_issue",
        connected_account_id="conn-1",
        input={"title": "x"},
    )
    payload = transport.requests[0].json_body
    assert payload["connectedAccountId"] == "conn-1"
    assert payload["input"] == {"title": "x"}


# MARK: - Permission coverage across partner-hub toolsets


def test_partner_hub_toolsets_have_permissions_on_every_tool() -> None:
    for connector in (
        WorkatoToolSet(api_token="t"),
        PipedreamToolSet(api_token="t"),
        MakeToolSet(api_token="t", base_url="https://us1.make.com/api/v2"),
        N8nToolSet(base_url="https://n8n.example.test", api_key="k"),
        ComposioToolSet(api_key="k"),
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
