# pyright: strict
"""Fivetran REST API connector."""

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Summary helpers


def _coerce_id(candidate: Any, *keys: str) -> str:
    """Pick a string ID from a raw value, dict, or list of dicts.

    Accepts a raw string ID, a dict with one of ``keys`` (or a ``_ref``
    paired with one of ``keys``), or a list of such dicts. Returns the first
    non-empty string match. Used by tolerant write tools so the agent can
    pass in the dicts returned from list/get tools directly.
    """
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        mapping = cast("dict[Any, Any]", candidate)
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, str) and value:
                return value
        # try nested data
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
            try:
                return _coerce_id(item, *keys)
            except ValueError:
                continue
    raise ValueError(f"could not extract an ID from {type(cast('object', candidate)).__name__}")


def _summarize_group(group: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "group_ref": f"group_{index}",
        "name": group.get("name", ""),
        "created_at": group.get("created_at", ""),
    }
    if include_ids:
        summary["group_id"] = group.get("id", "")
    return summary


def _summarize_connector(
    connector: dict[str, Any], *, index: int, include_ids: bool
) -> dict[str, Any]:
    status: Any = connector.get("status") or {}
    status_dict = cast("dict[str, Any]", status) if isinstance(status, dict) else None
    setup_state: Any = status_dict.get("setup_state") if status_dict is not None else None
    sync_state: Any = status_dict.get("sync_state") if status_dict is not None else None
    summary: dict[str, Any] = {
        "connector_ref": f"connector_{index}",
        "name": connector.get("schema") or connector.get("name", ""),
        "service": connector.get("service", ""),
        "destination_group": connector.get("group_id", ""),
        "schedule_type": connector.get("schedule_type", ""),
        "sync_frequency": connector.get("sync_frequency"),
        "paused": connector.get("paused"),
        "setup_state": setup_state,
        "sync_state": sync_state,
        "succeeded_at": connector.get("succeeded_at", ""),
        "failed_at": connector.get("failed_at", ""),
    }
    if include_ids:
        summary["connector_id"] = connector.get("id", "")
    return summary


def _summarize_destination(
    destination: dict[str, Any], *, index: int, include_ids: bool
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "destination_ref": f"destination_{index}",
        "name": destination.get("name") or destination.get("group_id", ""),
        "service": destination.get("service", ""),
        "region": destination.get("region", ""),
        "setup_status": destination.get("setup_status", ""),
    }
    if include_ids:
        summary["destination_id"] = destination.get("id", "")
        summary["group_id"] = destination.get("group_id", "")
    return summary


def _summarize_user(user: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "user_ref": f"user_{index}",
        "email": user.get("email", ""),
        "given_name": user.get("given_name", ""),
        "family_name": user.get("family_name", ""),
        "role": user.get("role", ""),
        "verified": user.get("verified"),
    }
    if include_ids:
        summary["user_id"] = user.get("id", "")
    return summary


# MARK: ToolSet


@toolset(prefix="fivetran")
class FivetranToolSet:
    """A connector for the Fivetran v1 REST API.

    Args:
        api_key: Fivetran API key.
        api_secret: Fivetran API secret.
    """

    metadata = ProviderMetadata(
        name="fivetran",
        display_name="Fivetran",
        version="0.1.0",
        description="Connectors, destinations, groups, users, and syncs.",
        auth_modes=(AuthMode.BASIC,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://fivetran.com/docs/rest-api",
        homepage_url="https://www.fivetran.com/",
        tags=("etl", "data-movement"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        base_url: str = "https://api.fivetran.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError("api_key and api_secret are required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BasicAuth(api_key, api_secret),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_groups(
        self,
        *,
        limit: int = 25,
        cursor: str | None = None,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List groups (Fivetran destinations + their connectors).

        Best first tool for discovering destination groups in the Fivetran
        account. Returns compact summaries with a stable ``group_ref``
        (``group_1``, ``group_2``, ...) plus the human-readable ``name``.
        Raw provider IDs are omitted by default because they are internal
        handles. Set ``include_ids=True`` only when a follow-up tool
        (``list_connectors``) needs the raw ``group_id``. Pass ``raw=True``
        to bypass the summary view and receive the unfiltered API response.
        Use ``cursor`` from a prior response to page forward.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        payload: dict[str, Any] = self._client.get("/v1/groups", params=params).json()
        if raw:
            return payload
        data: dict[str, Any] = payload.get("data") or {}
        items: list[Any] = data.get("items") or []
        summaries: list[dict[str, Any]] = []
        for index, group in enumerate(items, start=1):
            if isinstance(group, dict):
                summaries.append(
                    _summarize_group(
                        cast("dict[str, Any]", group), index=index, include_ids=include_ids
                    )
                )
        return {
            "groups": summaries,
            "next_cursor": data.get("next_cursor"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_connectors(
        self,
        group_id: Any,
        *,
        limit: int = 25,
        cursor: str | None = None,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List connectors in a group (the source pipelines feeding it).

        Returns compact summaries with ``connector_ref`` (``connector_1``,
        ``connector_2``, ...), name, source service, schedule, paused state,
        and last sync timestamps. ``group_id`` may be a raw string ID or a
        group dict from :meth:`list_groups` (``include_ids=True``). Raw
        connector IDs are omitted by default; set ``include_ids=True`` when
        a follow-up tool like :meth:`update_connector`, :meth:`trigger_sync`,
        or :meth:`delete_connector` needs the raw ``connector_id``. Pass
        ``raw=True`` for the unfiltered API response.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        resolved_group_id = _coerce_id(group_id, "group_id", "id")
        if not resolved_group_id:
            raise ValueError("group_id is required")
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        payload: dict[str, Any] = self._client.get(
            f"/v1/groups/{resolved_group_id}/connectors", params=params
        ).json()
        if raw:
            return payload
        data: dict[str, Any] = payload.get("data") or {}
        items: list[Any] = data.get("items") or []
        summaries: list[dict[str, Any]] = []
        for index, connector in enumerate(items, start=1):
            if isinstance(connector, dict):
                summaries.append(
                    _summarize_connector(
                        cast("dict[str, Any]", connector), index=index, include_ids=include_ids
                    )
                )
        return {
            "connectors": summaries,
            "next_cursor": data.get("next_cursor"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_connector(self, connector_id: Any) -> dict[str, Any]:
        """Return one connector's full configuration + sync status.

        Returns the raw Fivetran connector resource (``id``, ``service``,
        ``schema``, ``status``, ``config``, ``schedule_type``,
        ``sync_frequency``, ``succeeded_at``, ``failed_at``, ...). Use this
        when you need details a summary from :meth:`list_connectors` omits.
        ``connector_id`` may be a raw ID string or a connector dict from
        :meth:`list_connectors` (``include_ids=True``).
        """
        resolved_id = _coerce_id(connector_id, "connector_id", "id")
        if not resolved_id:
            raise ValueError("connector_id is required")
        return self._client.get(f"/v1/connectors/{resolved_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_connector(
        self,
        connector_id: Any,
        *,
        paused: bool | None = None,
        sync_frequency: int | None = None,
        schedule_type: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Patch a connector's schedule, config, or pause state.

        Returns the updated connector resource. ``connector_id`` may be a
        raw ID or a dict returned by :meth:`list_connectors`
        (``include_ids=True``) or :meth:`get_connector`. ``sync_frequency``
        is the interval in minutes; ``schedule_type`` is typically ``auto``
        or ``manual``. At least one of the keyword args is required.
        """
        resolved_id = _coerce_id(connector_id, "connector_id", "id")
        if not resolved_id:
            raise ValueError("connector_id is required")
        body: dict[str, Any] = {}
        if paused is not None:
            body["paused"] = paused
        if sync_frequency is not None:
            body["sync_frequency"] = sync_frequency
        if schedule_type is not None:
            body["schedule_type"] = schedule_type
        if config is not None:
            body["config"] = config
        if not body:
            raise ValueError("at least one update field is required")
        return self._client.patch(f"/v1/connectors/{resolved_id}", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def trigger_sync(
        self,
        connector_id: Any,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """Trigger a one-off incremental sync on a connector.

        Returns the API ack payload (``code``, ``message``). ``connector_id``
        may be a raw ID or a connector dict from :meth:`list_connectors`
        (``include_ids=True``) / :meth:`get_connector`. ``force=True`` runs
        even if a sync is currently in progress.
        """
        resolved_id = _coerce_id(connector_id, "connector_id", "id")
        if not resolved_id:
            raise ValueError("connector_id is required")
        return self._client.post(
            f"/v1/connectors/{resolved_id}/sync",
            json={"force": force},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def resync_connector(
        self,
        connector_id: Any,
        *,
        scope: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        """Trigger a historical re-sync (optionally scoped to specific tables).

        Returns the API ack payload. ``connector_id`` accepts the same
        formats as :meth:`trigger_sync`. ``scope`` maps a schema name to a
        list of table names to re-sync; omit it to re-sync everything. This
        is heavier than a normal sync — confirm with the user first.
        """
        resolved_id = _coerce_id(connector_id, "connector_id", "id")
        if not resolved_id:
            raise ValueError("connector_id is required")
        body: dict[str, Any] = {}
        if scope is not None:
            body["scope"] = scope
        return self._client.post(
            f"/v1/connectors/{resolved_id}/resync",
            json=body or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_connector(self, connector_id: Any) -> dict[str, Any]:
        """Permanently delete a connector. Destructive and irreversible.

        Returns the API ack payload. ``connector_id`` accepts a raw ID or a
        connector dict. Always confirm with the user before calling — the
        pipeline definition is removed and historical schema state is lost.
        """
        resolved_id = _coerce_id(connector_id, "connector_id", "id")
        if not resolved_id:
            raise ValueError("connector_id is required")
        return self._client.delete(f"/v1/connectors/{resolved_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_connector_schemas(self, connector_id: Any) -> dict[str, Any]:
        """Return the connector's source schemas (tables + columns).

        Returns ``{"data": {"enable_new_by_default": bool, "schemas":
        {<schema_name>: {"name_in_destination": ..., "tables": {...}}}}}``.
        Use this to understand which tables a connector replicates and
        their per-column enabled state.
        """
        resolved_id = _coerce_id(connector_id, "connector_id", "id")
        if not resolved_id:
            raise ValueError("connector_id is required")
        return self._client.get(f"/v1/connectors/{resolved_id}/schemas").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_destinations(
        self,
        *,
        limit: int = 25,
        cursor: str | None = None,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List destinations (warehouses Fivetran writes to).

        Returns compact summaries with ``destination_ref``, name, service,
        region, and setup status. Raw provider IDs are omitted by default —
        set ``include_ids=True`` only when a follow-up tool needs the raw
        ``destination_id``. Pass ``raw=True`` for the unfiltered API
        response. Use ``cursor`` to page forward.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        payload: dict[str, Any] = self._client.get("/v1/destinations", params=params).json()
        if raw:
            return payload
        data: dict[str, Any] = payload.get("data") or {}
        items: list[Any] = data.get("items") or []
        summaries: list[dict[str, Any]] = []
        for index, destination in enumerate(items, start=1):
            if isinstance(destination, dict):
                summaries.append(
                    _summarize_destination(
                        cast("dict[str, Any]", destination), index=index, include_ids=include_ids
                    )
                )
        return {
            "destinations": summaries,
            "next_cursor": data.get("next_cursor"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_destination(self, destination_id: Any) -> dict[str, Any]:
        """Return one destination's full configuration.

        Returns the raw Fivetran destination resource. ``destination_id``
        accepts a raw ID or a destination dict from :meth:`list_destinations`
        (``include_ids=True``).
        """
        resolved_id = _coerce_id(destination_id, "destination_id", "id")
        if not resolved_id:
            raise ValueError("destination_id is required")
        return self._client.get(f"/v1/destinations/{resolved_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_users(
        self,
        *,
        limit: int = 25,
        cursor: str | None = None,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List Fivetran users in the account.

        Returns compact summaries with ``user_ref``, email, given/family
        name, role, and verification state. Raw user IDs are omitted by
        default — set ``include_ids=True`` only when a follow-up tool needs
        the raw ``user_id``. Pass ``raw=True`` for the unfiltered API
        response.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        payload: dict[str, Any] = self._client.get("/v1/users", params=params).json()
        if raw:
            return payload
        data: dict[str, Any] = payload.get("data") or {}
        items: list[Any] = data.get("items") or []
        summaries: list[dict[str, Any]] = []
        for index, user in enumerate(items, start=1):
            if isinstance(user, dict):
                summaries.append(
                    _summarize_user(
                        cast("dict[str, Any]", user), index=index, include_ids=include_ids
                    )
                )
        return {
            "users": summaries,
            "next_cursor": data.get("next_cursor"),
        }
