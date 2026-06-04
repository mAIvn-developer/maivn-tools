"""n8n connector.

Exposes the n8n REST API (list / get / activate workflows, fetch executions)
plus a helper to invoke a workflow's webhook trigger. n8n is typically
self-hosted; the caller supplies the instance ``base_url`` and an API key
created in n8n's Settings -> API.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: - Constants

# n8n's executions `status` filter accepts only these enum values; `running`
# and other out-of-enum values are rejected by the API with a 400.
# https://github.com/n8n-io/n8n/issues/19664
_EXECUTION_STATUSES: frozenset[str] = frozenset({"canceled", "error", "success", "waiting"})

# MARK: - Helpers


def _coerce_id(candidate: Any, *keys: str) -> str:
    """Pick a string ID from a raw value, dict, or list of dicts."""
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, int):
        return str(candidate)
    if isinstance(candidate, dict):
        mapping = cast("dict[Any, Any]", candidate)
        for key in keys:
            value: Any = mapping.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, int):
                return str(value)
        for nested in mapping.values():
            if isinstance(nested, dict | list):
                try:
                    return _coerce_id(nested, *keys)
                except ValueError:
                    continue
    if isinstance(candidate, list | tuple):
        for item in cast("tuple[Any, ...]", candidate):
            try:
                return _coerce_id(item, *keys)
            except ValueError:
                continue
    type_name = type(cast("object", candidate)).__name__
    raise ValueError(f"could not extract an ID from {type_name}")


def _summarize_workflow(
    workflow: dict[str, Any], *, index: int, include_ids: bool
) -> dict[str, Any]:
    raw_tags: Any = workflow.get("tags", [])
    tags: list[Any] = []
    if isinstance(raw_tags, list | tuple):
        for tag in cast("tuple[Any, ...]", raw_tags):
            if isinstance(tag, dict):
                tag_dict = cast("dict[str, Any]", tag)
                tags.append(tag_dict.get("name", ""))
    summary: dict[str, Any] = {
        "workflow_ref": f"workflow_{index}",
        "name": workflow.get("name", ""),
        "active": workflow.get("active"),
        "tags": tags,
        "updated_at": workflow.get("updatedAt", ""),
    }
    if include_ids:
        summary["workflow_id"] = workflow.get("id", "")
    return summary


def _summarize_execution(
    execution: dict[str, Any], *, index: int, include_ids: bool
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "execution_ref": f"execution_{index}",
        "status": execution.get("status") or ("error" if execution.get("stoppedAt") else ""),
        "mode": execution.get("mode", ""),
        "started_at": execution.get("startedAt", ""),
        "stopped_at": execution.get("stoppedAt", ""),
        "finished": execution.get("finished"),
    }
    if include_ids:
        summary["execution_id"] = execution.get("id", "")
        summary["workflow_id"] = execution.get("workflowId", "")
    return summary


@toolset(prefix="n8n")
class N8nToolSet:
    """A connector for self-hosted or cloud n8n instances."""

    metadata = ProviderMetadata(
        name="n8n",
        display_name="n8n",
        version="0.1.0",
        description="List n8n workflows, inspect executions, and trigger webhook workflows.",
        auth_modes=(AuthMode.API_KEY,),
        scopes={
            "workflow:read": "Read workflows and executions.",
            "workflow:write": "Activate, deactivate, and edit workflows.",
        },
        capabilities=frozenset(
            {ProviderCapability.READ, ProviderCapability.WRITE, ProviderCapability.PAGINATION}
        ),
        documentation_url="https://docs.n8n.io/api/",
        homepage_url="https://n8n.io",
        tags=("partner", "automation"),
    )

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url must be a non-empty string")
        if not api_key:
            raise ValueError("api_key must be a non-empty string")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="X-N8N-API-KEY"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )
        self._webhook_client = HttpClient(transport=transport)

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_workflows(
        self,
        *,
        active: bool | None = None,
        limit: int = 25,
        cursor: str | None = None,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List workflows on the n8n instance.

        Best first tool for workflow discovery. Returns compact summaries
        with a stable ``workflow_ref``, name, active flag, tag names, and
        last-updated timestamp. Raw workflow IDs are omitted by default —
        set ``include_ids=True`` only when a follow-up tool like
        :meth:`activate_workflow` needs the raw ``workflow_id``. Pass
        ``raw=True`` for the unfiltered API response. Use ``cursor`` to
        page forward.
        """
        if limit < 1 or limit > 250:
            raise ValueError("limit must be between 1 and 250")
        params: dict[str, Any] = {"limit": limit}
        if active is not None:
            params["active"] = str(active).lower()
        if cursor is not None:
            params["cursor"] = cursor
        payload: dict[str, Any] = self._client.get("/api/v1/workflows", params=params).json()
        if raw:
            return payload
        raw_items: Any = payload.get("data") or []
        items: tuple[Any, ...] = (
            tuple(cast("tuple[Any, ...]", raw_items)) if isinstance(raw_items, list | tuple) else ()
        )
        summaries: list[dict[str, Any]] = []
        for index, workflow in enumerate(items, start=1):
            if isinstance(workflow, dict):
                workflow_dict = cast("dict[str, Any]", workflow)
                summaries.append(
                    _summarize_workflow(workflow_dict, index=index, include_ids=include_ids)
                )
        return {
            "workflows": summaries,
            "next_cursor": payload.get("nextCursor"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_workflow(self, workflow_id: Any) -> dict[str, Any]:
        """Return one workflow by ID.

        Returns the raw n8n workflow resource. ``workflow_id`` may be a raw
        ID string or a workflow dict from :meth:`list_workflows`
        (``include_ids=True``).
        """
        resolved_id = _coerce_id(workflow_id, "workflow_id", "id")
        if not resolved_id:
            raise ValueError("workflow_id must be a non-empty string")
        return self._client.get(f"/api/v1/workflows/{resolved_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def activate_workflow(self, workflow_id: Any, *, active: bool = True) -> dict[str, Any]:
        """Activate or deactivate a workflow.

        Returns the updated workflow resource. ``workflow_id`` may be a raw
        ID or a workflow dict from :meth:`list_workflows`
        (``include_ids=True``). Pass ``active=False`` to deactivate.
        """
        resolved_id = _coerce_id(workflow_id, "workflow_id", "id")
        if not resolved_id:
            raise ValueError("workflow_id must be a non-empty string")
        suffix = "activate" if active else "deactivate"
        return self._client.post(f"/api/v1/workflows/{resolved_id}/{suffix}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_executions(
        self,
        *,
        workflow_id: str | None = None,
        status: str | None = None,
        limit: int = 25,
        cursor: str | None = None,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List workflow executions.

        Returns compact summaries with ``execution_ref``, status, mode,
        start/stop timestamps, and finished flag. Raw execution IDs are
        omitted by default — set ``include_ids=True`` when a follow-up
        tool needs the raw ``execution_id``. Pass ``raw=True`` for the
        unfiltered API response. ``status`` filters by execution state and
        must be one of ``canceled``, ``error``, ``success``, or ``waiting``
        (n8n rejects other values, including ``running``).
        """
        if limit < 1 or limit > 250:
            raise ValueError("limit must be between 1 and 250")
        if status is not None and status not in _EXECUTION_STATUSES:
            allowed = ", ".join(sorted(_EXECUTION_STATUSES))
            raise ValueError(f"status must be one of: {allowed}")
        params: dict[str, Any] = {"limit": limit}
        if workflow_id is not None:
            params["workflowId"] = workflow_id
        if status is not None:
            params["status"] = status
        if cursor is not None:
            params["cursor"] = cursor
        payload: dict[str, Any] = self._client.get("/api/v1/executions", params=params).json()
        if raw:
            return payload
        raw_items: Any = payload.get("data") or []
        items: tuple[Any, ...] = (
            tuple(cast("tuple[Any, ...]", raw_items)) if isinstance(raw_items, list | tuple) else ()
        )
        summaries: list[dict[str, Any]] = []
        for index, execution in enumerate(items, start=1):
            if isinstance(execution, dict):
                execution_dict = cast("dict[str, Any]", execution)
                summaries.append(
                    _summarize_execution(execution_dict, index=index, include_ids=include_ids)
                )
        return {
            "executions": summaries,
            "next_cursor": payload.get("nextCursor"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def trigger_webhook(
        self,
        webhook_url: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST ``payload`` to a workflow webhook URL.

        Returns ``{"status": <http_status>, "delivered": True}``.
        ``webhook_url`` is the full webhook URL configured on the workflow
        — it is the entire URL, not a workflow ID.
        """
        if not webhook_url:
            raise ValueError("webhook_url must be a non-empty string")
        response = self._webhook_client.post(webhook_url, json=payload or {})
        return {"status": response.status, "delivered": True}
