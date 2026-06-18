"""Auth0 Management API v2 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast
from urllib.parse import quote

from maivn import tool_output, toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import (
    LIST_CLIENTS_OUTPUT,
    LIST_CONNECTIONS_OUTPUT,
    LIST_ORGANIZATIONS_OUTPUT,
    LIST_ROLES_OUTPUT,
    LIST_USERS_OUTPUT,
)


@toolset(prefix="auth0")
class Auth0ToolSet:
    """A connector for the Auth0 Management API v2.

    Args:
        domain: Tenant domain (e.g. ``"my-tenant.us.auth0.com"``).
        access_token: Management API token.
    """

    metadata = ProviderMetadata(
        name="auth0",
        display_name="Auth0",
        version="0.1.0",
        description="Users, roles, organizations, connections, and tenant config.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://auth0.com/docs/api/management/v2",
        homepage_url="https://auth0.com/",
        tags=("identity", "auth"),
    )

    def __init__(
        self,
        *,
        domain: str,
        access_token: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not domain or not access_token:
            raise ValueError("domain and access_token are required")
        self.connection = connection
        self._client = HttpClient(
            base_url=f"https://{domain.rstrip('/')}",
            auth=BearerTokenAuth(access_token),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Summary helpers

    @staticmethod
    def _user_summary(
        user: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "user_ref": f"user_{index}",
            "email": user.get("email", ""),
            "name": user.get("name", "") or user.get("nickname", ""),
            "blocked": bool(user.get("blocked", False)),
            "email_verified": bool(user.get("email_verified", False)),
            "last_login": user.get("last_login", ""),
            "logins_count": user.get("logins_count", 0),
        }
        if include_ids:
            summary["user_id"] = user.get("user_id", "")
        return summary

    @staticmethod
    def _role_summary(
        role: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "role_ref": f"role_{index}",
            "name": role.get("name", ""),
            "description": role.get("description", ""),
        }
        if include_ids:
            summary["role_id"] = role.get("id", "")
        return summary

    @staticmethod
    def _connection_summary(
        connection: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "connection_ref": f"connection_{index}",
            "name": connection.get("name", ""),
            "strategy": connection.get("strategy", ""),
            "is_domain_connection": bool(connection.get("is_domain_connection", False)),
        }
        if include_ids:
            summary["connection_id"] = connection.get("id", "")
        return summary

    @staticmethod
    def _client_summary(
        client: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "app_ref": f"app_{index}",
            "name": client.get("name", ""),
            "app_type": client.get("app_type", ""),
            "is_first_party": bool(client.get("is_first_party", False)),
        }
        if include_ids:
            summary["client_id"] = client.get("client_id", "")
        return summary

    @staticmethod
    def _org_summary(
        org: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "org_ref": f"org_{index}",
            "name": org.get("name", ""),
            "display_name": org.get("display_name", ""),
        }
        if include_ids:
            summary["org_id"] = org.get("id", "")
        return summary

    @staticmethod
    def _resolve_user_id(user_or_id: Any) -> str:
        """Accept a user_id string, an email, or a user dict from list/get.

        Returns the raw Auth0 ``user_id`` (e.g. ``"auth0|abc"``). Used by
        write tools that need to tolerate the natural output of list_users.
        """
        if isinstance(user_or_id, str) and user_or_id:
            return user_or_id
        if isinstance(user_or_id, dict):
            user_dict = cast("dict[str, Any]", user_or_id)
            for key in ("user_id", "id"):
                value: Any = user_dict.get(key)
                if isinstance(value, str) and value:
                    return value
        raise ValueError("expected a user_id string or a user dict with 'user_id'")

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_USERS_OUTPUT)
    def list_users(
        self,
        *,
        q: str | None = None,
        page: int = 0,
        per_page: int = 25,
        include_totals: bool = False,
        sort: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search Auth0 users (Lucene query syntax for ``q``).

        Best first tool for user lookup or audit. Returns compact summaries
        with a stable ``user_ref`` (``user_1``, ``user_2``, ...) plus email,
        name, blocked, email_verified, last_login, and logins_count. Raw
        Auth0 ``user_id`` values are omitted by default — they are internal
        handles. Set ``include_ids=True`` only when a follow-up tool
        (update_user, delete_user, assign_roles_to_user) needs the raw id.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "include_totals": str(include_totals).lower(),
        }
        if q is not None:
            params["q"] = q
            params["search_engine"] = "v3"
        if sort is not None:
            params["sort"] = sort
        payload: Any = self._client.get("/api/v2/users", params=params).json()
        raw_users: list[dict[str, Any]]
        wrapper: dict[str, Any] = {}
        if isinstance(payload, list):
            payload_list = cast("list[Any]", payload)
            raw_users = [cast("dict[str, Any]", u) for u in payload_list if isinstance(u, dict)]
        elif isinstance(payload, dict):
            payload_dict = cast("dict[str, Any]", payload)
            users_field = cast("list[Any]", payload_dict.get("users", []))
            raw_users = [cast("dict[str, Any]", u) for u in users_field if isinstance(u, dict)]
            wrapper = {k: v for k, v in payload_dict.items() if k != "users"}
        else:
            raw_users = []
        summaries = [
            self._user_summary(user, index=index, include_ids=include_ids)
            for index, user in enumerate(raw_users, start=1)
        ]
        result: dict[str, Any] = {"users": summaries}
        result.update(wrapper)
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self, user_id: str) -> dict[str, Any]:
        """Return one user's full Auth0 profile by ``user_id``.

        Returns the raw Auth0 user resource including ``user_id``, ``email``,
        ``identities``, ``user_metadata``, ``app_metadata``, ``last_login``,
        and login statistics. Use after list_users(include_ids=True) when
        you need the full profile.
        """
        if not user_id:
            raise ValueError("user_id is required")
        return self._client.get(f"/api/v2/users/{quote(user_id, safe='')}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_user(
        self,
        *,
        connection: str,
        email: str | None = None,
        username: str | None = None,
        password: str | None = None,
        user_metadata: dict[str, Any] | None = None,
        app_metadata: dict[str, Any] | None = None,
        email_verified: bool = False,
    ) -> dict[str, Any]:
        """Create a user in a database connection.

        ``connection`` is the connection name (e.g.
        ``"Username-Password-Authentication"``) — get the list from
        list_connections. Returns the new user resource with the assigned
        ``user_id``. Confirm sensitive identity changes with the user first.
        """
        if not connection:
            raise ValueError("connection is required")
        if not email and not username:
            raise ValueError("email or username is required")
        body: dict[str, Any] = {
            "connection": connection,
            "email_verified": email_verified,
        }
        if email is not None:
            body["email"] = email
        if username is not None:
            body["username"] = username
        if password is not None:
            body["password"] = password
        if user_metadata is not None:
            body["user_metadata"] = user_metadata
        if app_metadata is not None:
            body["app_metadata"] = app_metadata
        return self._client.post("/api/v2/users", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_user(
        self,
        user_id: Any,
        *,
        blocked: bool | None = None,
        email: str | None = None,
        email_verified: bool | None = None,
        user_metadata: dict[str, Any] | None = None,
        app_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Patch a user. ``user_id`` accepts the raw id or a user dict.

        Returns the updated user resource. Use ``blocked=True`` to disable
        sign-ins (reversible). Confirm with the user before changing
        identity-sensitive fields such as ``email`` or ``blocked``.
        """
        resolved_id = self._resolve_user_id(user_id)
        body: dict[str, Any] = {}
        if blocked is not None:
            body["blocked"] = blocked
        if email is not None:
            body["email"] = email
        if email_verified is not None:
            body["email_verified"] = email_verified
        if user_metadata is not None:
            body["user_metadata"] = user_metadata
        if app_metadata is not None:
            body["app_metadata"] = app_metadata
        if not body:
            raise ValueError("at least one update field is required")
        return self._client.patch(f"/api/v2/users/{quote(resolved_id, safe='')}", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_user(self, user_id: Any) -> dict[str, Any]:
        """Permanently delete a user. ``user_id`` accepts the raw id or a user dict.

        Destructive — the account, its tokens, and its profile are removed
        and cannot be recovered. Confirm with the user before calling.
        Returns ``{"user_id": ..., "deleted": True, "status": ...}``.
        """
        resolved_id = self._resolve_user_id(user_id)
        response = self._client.delete(f"/api/v2/users/{quote(resolved_id, safe='')}")
        return {"user_id": resolved_id, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_ROLES_OUTPUT)
    def list_roles(
        self,
        *,
        page: int = 0,
        per_page: int = 25,
        include_totals: bool = False,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Auth0 roles.

        Returns ``{"roles": [...]}`` with compact summaries containing
        ``role_ref``, ``name``, and ``description``. Set
        ``include_ids=True`` when assign_roles_to_user needs the raw role
        ids. Use ``page``/``per_page`` (max 100) to page through large
        tenants; ``include_totals=True`` preserves the start/limit/total
        wrapper so callers can detect more pages.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "include_totals": str(include_totals).lower(),
        }
        payload: Any = self._client.get("/api/v2/roles", params=params).json()
        raw_roles: list[dict[str, Any]]
        wrapper: dict[str, Any] = {}
        if isinstance(payload, list):
            payload_list = cast("list[Any]", payload)
            raw_roles = [cast("dict[str, Any]", r) for r in payload_list if isinstance(r, dict)]
        elif isinstance(payload, dict):
            payload_dict = cast("dict[str, Any]", payload)
            roles_field = cast("list[Any]", payload_dict.get("roles", []))
            raw_roles = [cast("dict[str, Any]", r) for r in roles_field if isinstance(r, dict)]
            wrapper = {k: v for k, v in payload_dict.items() if k != "roles"}
        else:
            raw_roles = []
        summaries = [
            self._role_summary(role, index=index, include_ids=include_ids)
            for index, role in enumerate(raw_roles, start=1)
        ]
        result: dict[str, Any] = {"roles": summaries}
        result.update(wrapper)
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def assign_roles_to_user(
        self,
        *,
        user_id: Any,
        role_ids: list[str],
    ) -> dict[str, Any]:
        """Assign one or more roles to a user.

        ``user_id`` accepts the raw id or a user dict from list_users.
        ``role_ids`` must be raw role ids (call list_roles(include_ids=True)
        first). Returns ``{"status": ..., "assigned": True}``.
        """
        resolved_id = self._resolve_user_id(user_id)
        if not role_ids:
            raise ValueError("role_ids is required")
        response = self._client.post(
            f"/api/v2/users/{quote(resolved_id, safe='')}/roles",
            json={"roles": role_ids},
        )
        return {"status": response.status, "assigned": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_CONNECTIONS_OUTPUT)
    def list_connections(
        self,
        *,
        strategy: str | None = None,
        page: int = 0,
        per_page: int = 25,
        include_totals: bool = False,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Auth0 connections (identity sources).

        Returns ``{"connections": [...]}`` with ``connection_ref``, ``name``,
        ``strategy`` (e.g. ``"auth0"``, ``"google-oauth2"``, ``"samlp"``),
        and ``is_domain_connection``. Use the ``name`` (not the id) when
        calling create_user. Use ``page``/``per_page`` (max 100) to page
        through large tenants; ``include_totals=True`` preserves the
        start/limit/total wrapper so callers can detect more pages.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "include_totals": str(include_totals).lower(),
        }
        if strategy is not None:
            params["strategy"] = strategy
        payload: Any = self._client.get("/api/v2/connections", params=params).json()
        raw_connections: list[dict[str, Any]]
        wrapper: dict[str, Any] = {}
        if isinstance(payload, list):
            payload_list = cast("list[Any]", payload)
            raw_connections = [
                cast("dict[str, Any]", c) for c in payload_list if isinstance(c, dict)
            ]
        elif isinstance(payload, dict):
            payload_dict = cast("dict[str, Any]", payload)
            connections_field = cast("list[Any]", payload_dict.get("connections", []))
            raw_connections = [
                cast("dict[str, Any]", c) for c in connections_field if isinstance(c, dict)
            ]
            wrapper = {k: v for k, v in payload_dict.items() if k != "connections"}
        else:
            raw_connections = []
        summaries = [
            self._connection_summary(connection, index=index, include_ids=include_ids)
            for index, connection in enumerate(raw_connections, start=1)
        ]
        result: dict[str, Any] = {"connections": summaries}
        result.update(wrapper)
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_CLIENTS_OUTPUT)
    def list_clients(
        self,
        *,
        page: int = 0,
        per_page: int = 25,
        include_totals: bool = False,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Auth0 applications (clients).

        Returns ``{"apps": [...]}`` with ``app_ref``, ``name``,
        ``app_type``, and ``is_first_party``. Raw ``client_id`` values are
        sensitive and omitted by default. Use ``page``/``per_page`` (max
        100) to page through large tenants; ``include_totals=True``
        preserves the start/limit/total wrapper so callers can detect more
        pages.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "include_totals": str(include_totals).lower(),
        }
        payload: Any = self._client.get("/api/v2/clients", params=params).json()
        raw_clients: list[dict[str, Any]]
        wrapper: dict[str, Any] = {}
        if isinstance(payload, list):
            payload_list = cast("list[Any]", payload)
            raw_clients = [cast("dict[str, Any]", c) for c in payload_list if isinstance(c, dict)]
        elif isinstance(payload, dict):
            payload_dict = cast("dict[str, Any]", payload)
            clients_field = cast("list[Any]", payload_dict.get("clients", []))
            raw_clients = [cast("dict[str, Any]", c) for c in clients_field if isinstance(c, dict)]
            wrapper = {k: v for k, v in payload_dict.items() if k != "clients"}
        else:
            raw_clients = []
        summaries = [
            self._client_summary(client, index=index, include_ids=include_ids)
            for index, client in enumerate(raw_clients, start=1)
        ]
        result: dict[str, Any] = {"apps": summaries}
        result.update(wrapper)
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_ORGANIZATIONS_OUTPUT)
    def list_organizations(
        self,
        *,
        page: int = 0,
        per_page: int = 25,
        include_totals: bool = False,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Auth0 organizations.

        Returns ``{"organizations": [...]}`` with ``org_ref``, ``name``,
        and ``display_name``. Use ``page``/``per_page`` (max 100) to page
        through large tenants; ``include_totals=True`` preserves the
        start/limit/total wrapper so callers can detect more pages.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "include_totals": str(include_totals).lower(),
        }
        payload: Any = self._client.get("/api/v2/organizations", params=params).json()
        raw_orgs: list[dict[str, Any]]
        wrapper: dict[str, Any] = {}
        if isinstance(payload, list):
            payload_list = cast("list[Any]", payload)
            raw_orgs = [cast("dict[str, Any]", o) for o in payload_list if isinstance(o, dict)]
        elif isinstance(payload, dict):
            payload_dict = cast("dict[str, Any]", payload)
            orgs_field = cast("list[Any]", payload_dict.get("organizations", []))
            raw_orgs = [cast("dict[str, Any]", o) for o in orgs_field if isinstance(o, dict)]
            wrapper = {k: v for k, v in payload_dict.items() if k != "organizations"}
        else:
            raw_orgs = []
        summaries = [
            self._org_summary(org, index=index, include_ids=include_ids)
            for index, org in enumerate(raw_orgs, start=1)
        ]
        result: dict[str, Any] = {"organizations": summaries}
        result.update(wrapper)
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_logs(
        self,
        *,
        q: str | None = None,
        page: int = 0,
        per_page: int = 50,
    ) -> dict[str, Any]:
        """Query the tenant audit log stream.

        Returns the raw Auth0 log payload — events include ``type``,
        ``date``, ``user_id``, ``client_id``, and ``ip``. Useful for
        diagnosing login failures or unusual access.
        """
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if q is not None:
            params["q"] = q
        return self._client.get("/api/v2/logs", params=params).json()
