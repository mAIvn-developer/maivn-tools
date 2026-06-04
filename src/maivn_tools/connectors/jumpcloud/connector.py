"""JumpCloud REST API v1 + v2 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="jumpcloud")
class JumpCloudToolSet:
    """A connector for the JumpCloud REST API.

    Args:
        api_key: JumpCloud API key (``x-api-key``).
    """

    metadata = ProviderMetadata(
        name="jumpcloud",
        display_name="JumpCloud",
        version="0.1.0",
        description="Users, user groups, systems, system groups, and SSO apps.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.jumpcloud.com/api/",
        homepage_url="https://jumpcloud.com/",
        tags=("identity", "directory"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://console.jumpcloud.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="x-api-key"),
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
            "username": user.get("username", ""),
            "name": " ".join(
                part for part in (user.get("firstname", ""), user.get("lastname", "")) if part
            ).strip(),
            "suspended": bool(user.get("suspended", False)),
            "activated": bool(user.get("activated", False)),
            "last_login": user.get("lastLogin", ""),
        }
        if include_ids:
            summary["user_id"] = user.get("_id", "") or user.get("id", "")
        return summary

    @staticmethod
    def _group_summary(
        group: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "group_ref": f"group_{index}",
            "name": group.get("name", ""),
            "description": group.get("description", ""),
            "type": group.get("type", ""),
        }
        if include_ids:
            summary["group_id"] = group.get("id", "") or group.get("_id", "")
        return summary

    @staticmethod
    def _system_summary(
        system: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "system_ref": f"system_{index}",
            "hostname": system.get("hostname", "") or system.get("displayName", ""),
            "os": system.get("os", ""),
            "version": system.get("version", ""),
            "active": bool(system.get("active", False)),
            "last_contact": system.get("lastContact", ""),
        }
        if include_ids:
            summary["system_id"] = system.get("_id", "") or system.get("id", "")
        return summary

    @staticmethod
    def _app_summary(
        app: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "app_ref": f"app_{index}",
            "name": app.get("name", "") or app.get("displayLabel", ""),
            "sso_type": app.get("ssoType", ""),
            "active": bool(app.get("active", False)),
        }
        if include_ids:
            summary["app_id"] = app.get("id", "") or app.get("_id", "")
        return summary

    @staticmethod
    def _resolve_user_id(user_or_id: Any) -> str:
        if isinstance(user_or_id, str) and user_or_id:
            return user_or_id
        if isinstance(user_or_id, dict):
            mapping: dict[str, Any] = cast("dict[str, Any]", user_or_id)
            for key in ("user_id", "_id", "id"):
                value: Any = mapping.get(key)
                if isinstance(value, str) and value:
                    return value
        raise ValueError("expected a user id string or a user dict with '_id'")

    @staticmethod
    def _coerce_results(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            items: list[Any] = cast("list[Any]", payload)
            return [cast("dict[str, Any]", r) for r in items if isinstance(r, dict)]
        if isinstance(payload, dict):
            mapping: dict[str, Any] = cast("dict[str, Any]", payload)
            for key in ("results", "data", "users", "groups", "systems"):
                field: Any = mapping.get(key)
                if isinstance(field, list):
                    entries: list[Any] = cast("list[Any]", field)
                    return [cast("dict[str, Any]", r) for r in entries if isinstance(r, dict)]
        return []

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_users(
        self,
        *,
        skip: int = 0,
        limit: int = 25,
        filter: str | None = None,
        search: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List JumpCloud users.

        Returns ``{"users": [...]}`` with ``user_ref``, ``email``,
        ``username``, ``name``, ``suspended``, ``activated``,
        ``last_login``. Raw ``user_id`` is omitted by default.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"skip": skip, "limit": limit}
        if filter is not None:
            params["filter"] = filter
        if search is not None:
            params["search"] = search
        payload = self._client.get("/api/systemusers", params=params).json()
        raw_users = self._coerce_results(payload)
        summaries = [
            self._user_summary(user, index=index, include_ids=include_ids)
            for index, user in enumerate(raw_users, start=1)
        ]
        result: dict[str, Any] = {"users": summaries}
        if isinstance(payload, dict) and "totalCount" in payload:
            result["totalCount"] = payload["totalCount"]
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self, user_id: str) -> dict[str, Any]:
        """Return one JumpCloud user (full record).

        Returns the raw user resource — includes attributes, MFA settings,
        and last sign-in details.
        """
        if not user_id:
            raise ValueError("user_id is required")
        return self._client.get(f"/api/systemusers/{user_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_user(
        self,
        *,
        username: str,
        email: str,
        firstname: str | None = None,
        lastname: str | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        """Create a JumpCloud user.

        Returns the new user resource. Confirm the email and group
        membership plans with the user before calling.
        """
        if not username or not email:
            raise ValueError("username and email are required")
        body: dict[str, Any] = {"username": username, "email": email}
        if firstname is not None:
            body["firstname"] = firstname
        if lastname is not None:
            body["lastname"] = lastname
        if password is not None:
            body["password"] = password
        return self._client.post("/api/systemusers", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_user(
        self,
        user_id: Any,
        *,
        firstname: str | None = None,
        lastname: str | None = None,
        suspended: bool | None = None,
        attributes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Patch a JumpCloud user. ``user_id`` accepts dict or string.

        Returns the updated user resource. Confirm with the user before
        suspending or modifying identity attributes.
        """
        resolved_id = self._resolve_user_id(user_id)
        body: dict[str, Any] = {}
        if firstname is not None:
            body["firstname"] = firstname
        if lastname is not None:
            body["lastname"] = lastname
        if suspended is not None:
            body["suspended"] = suspended
        if attributes is not None:
            body["attributes"] = attributes
        if not body:
            raise ValueError("at least one update field is required")
        return self._client.put(f"/api/systemusers/{resolved_id}", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_user(self, user_id: Any) -> dict[str, Any]:
        """Permanently delete a JumpCloud user. ``user_id`` accepts dict or string.

        Destructive — terminates sessions, removes from groups, and the
        account cannot be recovered. Confirm with the user before
        calling. Returns ``{"user_id": ..., "deleted": True, "status": ...}``.
        """
        resolved_id = self._resolve_user_id(user_id)
        response = self._client.delete(f"/api/systemusers/{resolved_id}")
        return {"user_id": resolved_id, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_user_groups(
        self,
        *,
        skip: int = 0,
        limit: int = 25,
        filter: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List JumpCloud user groups (v2).

        Returns ``{"groups": [...]}`` with ``group_ref``, ``name``,
        ``description``, ``type``.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"skip": skip, "limit": limit}
        if filter is not None:
            params["filter"] = filter
        payload = self._client.get("/api/v2/usergroups", params=params).json()
        raw_groups = self._coerce_results(payload)
        summaries = [
            self._group_summary(group, index=index, include_ids=include_ids)
            for index, group in enumerate(raw_groups, start=1)
        ]
        return {"groups": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def manage_user_group_member(
        self,
        *,
        group_id: str,
        user_id: Any,
        op: str,
    ) -> dict[str, Any]:
        """Add or remove a user from a user group.

        ``user_id`` accepts dict or string. ``op`` is ``add`` or
        ``remove``. Removing a user from a group revokes any group-based
        access.
        """
        if not group_id:
            raise ValueError("group_id is required")
        resolved_id = self._resolve_user_id(user_id)
        if op not in {"add", "remove"}:
            raise ValueError("op must be add or remove")
        return self._client.post(
            f"/api/v2/usergroups/{group_id}/members",
            json={"op": op, "type": "user", "id": resolved_id},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_systems(
        self,
        *,
        skip: int = 0,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List JumpCloud-managed systems (endpoints).

        Returns ``{"systems": [...]}`` with ``system_ref``, ``hostname``,
        ``os``, ``version``, ``active``, ``last_contact``. Raw
        ``system_id`` is omitted by default.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        payload = self._client.get("/api/systems", params={"skip": skip, "limit": limit}).json()
        raw_systems = self._coerce_results(payload)
        summaries = [
            self._system_summary(system, index=index, include_ids=include_ids)
            for index, system in enumerate(raw_systems, start=1)
        ]
        return {"systems": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_applications(
        self,
        *,
        skip: int = 0,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List JumpCloud SSO applications (v1).

        Returns ``{"apps": [...]}`` with ``app_ref``, ``name``,
        ``sso_type``, ``active``.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        payload = self._client.get(
            "/api/applications",
            params={"skip": skip, "limit": limit},
        ).json()
        raw_apps = self._coerce_results(payload)
        summaries = [
            self._app_summary(app, index=index, include_ids=include_ids)
            for index, app in enumerate(raw_apps, start=1)
        ]
        return {"apps": summaries}
