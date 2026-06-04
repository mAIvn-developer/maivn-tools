"""Composio connector.

Composio's hosted API exposes a catalog of cross-app actions. The connector
authenticates with an API key (issued from the Composio dashboard) and
exposes the most useful endpoints: list apps, list actions, list
connections, and execute an action.
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

COMPOSIO_API_URL = "https://backend.composio.dev/api"


# MARK: - Helpers


def _coerce_id(candidate: Any, *keys: str) -> str:
    """Pick a string ID from a raw value, dict, or list of dicts."""
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        mapping = cast(dict[Any, Any], candidate)
        for key in keys:
            value: Any = mapping.get(key)
            if isinstance(value, str) and value:
                return value
        for nested in mapping.values():
            nested_value: Any = nested
            if isinstance(nested_value, dict | list):
                try:
                    return _coerce_id(nested_value, *keys)
                except ValueError:
                    continue
    if isinstance(candidate, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in sequence:
            item_value: Any = item
            try:
                return _coerce_id(item_value, *keys)
            except ValueError:
                continue
    raise ValueError(f"could not extract an ID from {type(cast(object, candidate)).__name__}")


def _summarize_app(app: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "app_ref": f"app_{index}",
        "name": app.get("name") or app.get("key", ""),
        "description": app.get("description", ""),
        "categories": app.get("categories", []),
        "no_auth": app.get("no_auth"),
    }
    if include_ids:
        summary["app_id"] = app.get("appId") or app.get("id", "")
        summary["key"] = app.get("key", "")
    return summary


def _summarize_action(action: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "action_ref": f"action_{index}",
        "name": action.get("displayName") or action.get("name", ""),
        "app": action.get("appName") or action.get("app", ""),
        "description": action.get("description", ""),
    }
    if include_ids:
        summary["action_name"] = action.get("name", "")
        summary["action_id"] = action.get("id", "")
    return summary


def _summarize_connection(
    connection: dict[str, Any], *, index: int, include_ids: bool
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "connection_ref": f"connection_{index}",
        "app": connection.get("appName") or connection.get("appUniqueId", ""),
        "status": connection.get("status", ""),
        "created_at": connection.get("createdAt", ""),
    }
    if include_ids:
        summary["connection_id"] = (
            connection.get("connectedAccountId")
            or connection.get("id")
            or connection.get("connectionId", "")
        )
    return summary


# MARK: - Tool set


@toolset(prefix="composio")
class ComposioToolSet:
    """A connector for the Composio toolset bridge."""

    metadata = ProviderMetadata(
        name="composio",
        display_name="Composio",
        version="0.1.0",
        description="Browse and execute Composio's catalog of cross-app actions.",
        auth_modes=(AuthMode.API_KEY,),
        scopes={"actions:execute": "Execute Composio actions on behalf of the account."},
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.composio.dev",
        homepage_url="https://composio.dev",
        tags=("partner", "automation", "tools"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        transport: HttpTransport | None = None,
        base_url: str = COMPOSIO_API_URL,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key must be a non-empty string")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="x-api-key"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_apps(
        self,
        *,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List apps available in the Composio catalog.

        Best first tool for app discovery. Returns compact summaries with a
        stable ``app_ref``, name, description, categories, and a
        ``no_auth`` flag. Raw app/key IDs are omitted by default — set
        ``include_ids=True`` only when a follow-up tool like
        :meth:`list_actions` (filtered by app key) needs the raw ``key``.
        Pass ``raw=True`` for the unfiltered API response.
        """
        payload: dict[str, Any] = self._client.get("/v1/apps").json()
        if raw:
            return payload
        items: list[Any] = payload.get("items") or payload.get("apps") or payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, app in enumerate(items, start=1):
            if isinstance(app, dict):
                app_dict = cast(dict[str, Any], app)
                summaries.append(_summarize_app(app_dict, index=index, include_ids=include_ids))
        return {"apps": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_actions(
        self,
        *,
        app: str | None = None,
        use_case: str | None = None,
        limit: int = 25,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List actions, optionally filtered by app or use case.

        Returns compact summaries with a stable ``action_ref``, name, app,
        and description. Raw action names/IDs are omitted by default — set
        ``include_ids=True`` when a follow-up tool like
        :meth:`execute_action` needs the raw ``action_name``. Pass
        ``raw=True`` for the unfiltered API response.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit}
        if app is not None:
            params["app"] = app
        if use_case is not None:
            params["useCase"] = use_case
        payload: dict[str, Any] = self._client.get("/v1/actions", params=params).json()
        if raw:
            return payload
        items: list[Any] = (
            payload.get("items") or payload.get("actions") or payload.get("data") or []
        )
        summaries: list[dict[str, Any]] = []
        for index, action in enumerate(items, start=1):
            if isinstance(action, dict):
                action_dict = cast(dict[str, Any], action)
                summaries.append(
                    _summarize_action(action_dict, index=index, include_ids=include_ids)
                )
        return {"actions": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_connections(
        self,
        *,
        app: str | None = None,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List connected accounts the API key can act through.

        Returns compact summaries with a stable ``connection_ref``, app
        name, status, and created date. Raw connection IDs are omitted by
        default — set ``include_ids=True`` when a follow-up tool like
        :meth:`execute_action` needs the raw ``connected_account_id``.
        Pass ``raw=True`` for the unfiltered API response.
        """
        params = {"app": app} if app else None
        payload: dict[str, Any] = self._client.get("/v1/connectedAccounts", params=params).json()
        if raw:
            return payload
        items: list[Any] = payload.get("items") or payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, connection in enumerate(items, start=1):
            if isinstance(connection, dict):
                connection_dict = cast(dict[str, Any], connection)
                summaries.append(
                    _summarize_connection(connection_dict, index=index, include_ids=include_ids)
                )
        return {"connections": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def execute_action(
        self,
        action_name: Any,
        connected_account_id: Any,
        *,
        input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a single Composio action.

        Returns the raw execution result payload. ``action_name`` may be a
        raw action name string or an action dict from :meth:`list_actions`
        (``include_ids=True``). ``connected_account_id`` may be a raw
        connection ID or a connection dict from :meth:`list_connections`
        (``include_ids=True``). ``input`` carries action-specific
        arguments.
        """
        resolved_action_name = _coerce_id(action_name, "action_name", "name", "id")
        resolved_connection_id = _coerce_id(
            connected_account_id, "connection_id", "connectedAccountId", "id"
        )
        if not resolved_action_name:
            raise ValueError("action_name must be a non-empty string")
        if not resolved_connection_id:
            raise ValueError("connected_account_id must be a non-empty string")
        payload: dict[str, Any] = {
            "connectedAccountId": resolved_connection_id,
            "input": input or {},
        }
        result: dict[str, Any] = self._client.post(
            f"/v1/actions/{resolved_action_name}/execute",
            json=payload,
        ).json()
        return result
