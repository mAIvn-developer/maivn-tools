"""Pipedream connector.

Pipedream's API uses bearer authentication. The connector exposes the
documented workflow surface: fetch one workflow by ID and invoke a
workflow's HTTP trigger.

Note: the Pipedream REST API does not provide a list-workflows collection
endpoint (only ``GET /workflows/{workflow_id}`` exists), so workflows are
addressed by ID rather than enumerated. See Pipedream issue #16720.
"""

# pyright: strict
from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: - Constants

PIPEDREAM_API_URL = "https://api.pipedream.com/v1"


# MARK: - Helpers


def _coerce_id(candidate: object, *keys: str) -> str:
    """Pick a string ID from a raw value, dict, or list of dicts."""
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        mapping = cast(dict[object, object], candidate)
        for key in keys:
            value: object = mapping.get(key)
            if isinstance(value, str) and value:
                return value
        for nested in mapping.values():
            if isinstance(nested, dict | list):
                try:
                    return _coerce_id(cast(object, nested), *keys)
                except ValueError:
                    continue
    if isinstance(candidate, list | tuple):
        sequence = cast("list[object] | tuple[object, ...]", candidate)
        for item in sequence:
            try:
                return _coerce_id(item, *keys)
            except ValueError:
                continue
    raise ValueError(f"could not extract an ID from {type(cast(object, candidate)).__name__}")


@toolset(prefix="pipedream")
class PipedreamToolSet:
    """A connector for the Pipedream REST API."""

    metadata = ProviderMetadata(
        name="pipedream",
        display_name="Pipedream",
        version="0.1.0",
        description="Fetch Pipedream workflows by ID and invoke their HTTP triggers.",
        auth_modes=(AuthMode.BEARER,),
        scopes={"workflows": "Read and trigger workflows."},
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://pipedream.com/docs/api/rest/",
        homepage_url="https://pipedream.com",
        tags=("partner", "automation"),
    )

    def __init__(
        self,
        *,
        api_token: str,
        transport: HttpTransport | None = None,
        base_url: str = PIPEDREAM_API_URL,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_token:
            raise ValueError("api_token must be a non-empty string")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url,
            auth=BearerTokenAuth(api_token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )
        self._trigger_client = HttpClient(transport=transport)

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_workflow(self, workflow_id: object, *, org_id: str | None = None) -> dict[str, Any]:
        """Return one workflow by ID.

        Returns the raw Pipedream workflow resource. ``workflow_id`` may be
        a raw ID string or a workflow dict carrying a ``workflow_id``/``id``
        key. Pass ``org_id`` to scope the request to the org/project that
        owns the workflow (sent as the documented ``org_id`` query param).

        The Pipedream REST API has no list-workflows endpoint, so workflow
        IDs must be supplied directly (e.g. copied from the Pipedream UI).
        """
        resolved_id = _coerce_id(workflow_id, "workflow_id", "id")
        if not resolved_id:
            raise ValueError("workflow_id must be a non-empty string")
        params = {"org_id": org_id} if org_id else None
        data: dict[str, Any] = self._client.get(f"/workflows/{resolved_id}", params=params).json()
        return data

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def invoke_http_trigger(
        self,
        trigger_url: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST ``payload`` to a workflow's HTTP trigger URL.

        Returns ``{"status": <http_status>, "delivered": True}``.
        ``trigger_url`` is the full HTTP trigger URL configured on the
        workflow (the trigger's ``endpoint_url``), not a workflow ID.
        """
        if not trigger_url:
            raise ValueError("trigger_url must be a non-empty string")
        response = self._trigger_client.post(trigger_url, json=payload or {})
        return {"status": response.status, "delivered": True}
