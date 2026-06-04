"""OneLogin v2 REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="onelogin")
class OneLoginToolSet:
    """A connector for the OneLogin v2 REST API.

    Args:
        access_token: Bearer token issued via the OAuth client-credentials
            flow against ``/auth/oauth2/v2/token``.
        subdomain: OneLogin subdomain (e.g. ``"my-tenant"``).
        region: ``"us"`` (default) or ``"eu"``.
    """

    metadata = ProviderMetadata(
        name="onelogin",
        display_name="OneLogin",
        version="0.1.0",
        description="Users, roles, groups, apps, MFA, and events.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developers.onelogin.com/api-docs/",
        homepage_url="https://www.onelogin.com/",
        tags=("identity", "sso"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        subdomain: str,
        region: str = "us",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token or not subdomain:
            raise ValueError("access_token and subdomain are required")
        if region not in {"us", "eu"}:
            raise ValueError("region must be us or eu")
        self.connection = connection
        host = f"{subdomain}.onelogin.com" if region == "us" else f"{subdomain}.onelogin.eu"
        self._client = HttpClient(
            base_url=f"https://{host}",
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
            "username": user.get("username", ""),
            "name": " ".join(
                part for part in (user.get("firstname", ""), user.get("lastname", "")) if part
            ).strip(),
            "status": user.get("status", ""),
            "last_login": user.get("last_login", ""),
            "locked_until": user.get("locked_until", ""),
        }
        if include_ids:
            summary["user_id"] = user.get("id", 0)
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
        }
        if include_ids:
            summary["role_id"] = role.get("id", 0)
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
            "name": app.get("name", ""),
            "auth_method": app.get("auth_method", ""),
            "connector_id": app.get("connector_id", 0),
            "visible": bool(app.get("visible", False)),
        }
        if include_ids:
            summary["app_id"] = app.get("id", 0)
        return summary

    @staticmethod
    def _resolve_user_id(user_or_id: Any) -> int:
        if isinstance(user_or_id, int) and user_or_id:
            return user_or_id
        if isinstance(user_or_id, dict):
            user_dict = cast(dict[str, Any], user_or_id)
            for key in ("user_id", "id"):
                value: Any = user_dict.get(key)
                if isinstance(value, int) and value:
                    return value
        raise ValueError("expected a user id int or a user dict with 'id'")

    @staticmethod
    def _coerce_results(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            items = cast(list[Any], payload)
            return [r for r in items if isinstance(r, dict)]
        if isinstance(payload, dict):
            payload_dict = cast(dict[str, Any], payload)
            for key in ("data", "users", "roles", "apps"):
                field: Any = payload_dict.get(key)
                if isinstance(field, list):
                    field_items = cast(list[Any], field)
                    return [r for r in field_items if isinstance(r, dict)]
        return []

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_users(
        self,
        *,
        fields: list[str] | None = None,
        email: str | None = None,
        cursor: str | None = None,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List OneLogin users.

        Returns ``{"users": [...]}`` with ``user_ref``, ``email``,
        ``username``, ``name``, ``status``, ``last_login``,
        ``locked_until``. Raw integer ``user_id`` is omitted by default.
        Pass the returned ``after_cursor`` back as ``cursor`` to page.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        params: dict[str, Any] = {"limit": limit}
        if fields is not None:
            params["fields"] = ",".join(fields)
        if email is not None:
            params["email"] = email
        if cursor is not None:
            params["cursor"] = cursor
        response = self._client.get("/api/2/users", params=params)
        raw_users = self._coerce_results(response.json())
        summaries = [
            self._user_summary(user, index=index, include_ids=include_ids)
            for index, user in enumerate(raw_users, start=1)
        ]
        result: dict[str, Any] = {"users": summaries}
        # v2 list endpoints return cursors as response headers, not body keys.
        after_cursor = response.header("After-Cursor")
        before_cursor = response.header("Before-Cursor")
        total_count = response.header("Total-Count")
        if after_cursor is not None:
            result["after_cursor"] = after_cursor
        if before_cursor is not None:
            result["before_cursor"] = before_cursor
        if total_count is not None:
            result["total_count"] = total_count
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self, user_id: int) -> dict[str, Any]:
        """Return one OneLogin user (full record).

        Returns the raw user resource — includes custom attributes,
        role ids, group id, and all profile fields.
        """
        if not user_id:
            raise ValueError("user_id is required")
        return self._client.get(f"/api/2/users/{user_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_user(
        self,
        *,
        email: str,
        username: str | None = None,
        firstname: str | None = None,
        lastname: str | None = None,
        password: str | None = None,
        password_confirmation: str | None = None,
    ) -> dict[str, Any]:
        """Create a OneLogin user.

        Returns the new user resource. Confirm the email with the user
        before calling.
        """
        if not email:
            raise ValueError("email is required")
        body: dict[str, Any] = {"email": email}
        if username is not None:
            body["username"] = username
        if firstname is not None:
            body["firstname"] = firstname
        if lastname is not None:
            body["lastname"] = lastname
        if password is not None:
            body["password"] = password
        if password_confirmation is not None:
            body["password_confirmation"] = password_confirmation
        return self._client.post("/api/2/users", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_user(
        self,
        user_id: Any,
        *,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a OneLogin user. ``user_id`` accepts dict or int.

        Returns the updated user resource. Confirm identity changes with
        the user first.
        """
        resolved_id = self._resolve_user_id(user_id)
        if not body:
            raise ValueError("body is required")
        return self._client.put(f"/api/2/users/{resolved_id}", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_user(self, user_id: Any) -> dict[str, Any]:
        """Permanently delete a OneLogin user. ``user_id`` accepts dict or int.

        Destructive — terminates sessions and removes profile data.
        Confirm with the user before calling. Returns
        ``{"user_id": ..., "deleted": True, "status": ...}``.
        """
        resolved_id = self._resolve_user_id(user_id)
        response = self._client.delete(f"/api/2/users/{resolved_id}")
        return {"user_id": resolved_id, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def lock_user(self, user_id: Any, *, locked_until: int = 0) -> dict[str, Any]:
        """Lock a OneLogin user (blocks sign-in until unlocked).

        ``user_id`` accepts dict or int. ``locked_until`` is the number
        of MINUTES to lock the account (0 = defer to the user's lock
        policy). Served on v1 (``/api/1/users/{id}/lock_user``).
        Destructive — confirm with the user. Reversible via the
        OneLogin admin UI.
        """
        resolved_id = self._resolve_user_id(user_id)
        return self._client.put(
            f"/api/1/users/{resolved_id}/lock_user",
            json={"locked_until": locked_until},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_roles(
        self,
        *,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List OneLogin roles.

        Returns ``{"roles": [...]}`` with ``role_ref``, ``name``. Set
        ``include_ids=True`` when assign_role_to_user needs the integer
        role ids.
        """
        payload = self._client.get("/api/2/roles").json()
        raw_roles = self._coerce_results(payload)
        summaries = [
            self._role_summary(role, index=index, include_ids=include_ids)
            for index, role in enumerate(raw_roles, start=1)
        ]
        return {"roles": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def assign_role_to_user(
        self,
        *,
        user_id: Any,
        role_ids: list[int],
    ) -> dict[str, Any]:
        """Assign one or more roles to a OneLogin user.

        ``user_id`` accepts dict or int. ``role_ids`` must be integer
        ids — call list_roles(include_ids=True) to get them.

        Assignment is role-centric in v2: each role id is added via
        ``POST /api/2/roles/{role_id}/users`` with a bare array body
        ``[user_id]`` (there is no v2 user-centric roles endpoint).
        Returns ``{"user_id": ..., "assigned_role_ids": [...]}``.
        """
        resolved_id = self._resolve_user_id(user_id)
        if not role_ids:
            raise ValueError("role_ids is required")
        for role_id in role_ids:
            self._client.post(
                f"/api/2/roles/{role_id}/users",
                json=[resolved_id],
            )
        return {"user_id": resolved_id, "assigned_role_ids": list(role_ids)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_apps(
        self,
        *,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List OneLogin apps.

        Returns ``{"apps": [...]}`` with ``app_ref``, ``name``,
        ``auth_method``, ``connector_id``, ``visible``.
        """
        payload = self._client.get("/api/2/apps").json()
        raw_apps = self._coerce_results(payload)
        summaries = [
            self._app_summary(app, index=index, include_ids=include_ids)
            for index, app in enumerate(raw_apps, start=1)
        ]
        return {"apps": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_events(
        self,
        *,
        from_timestamp: int | None = None,
        event_type_id: int | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        """Query the OneLogin event log.

        The Events API is served only on v1 (``/api/1/events``).
        ``from_timestamp`` is an epoch-seconds lower bound; ``page`` /
        ``per_page`` drive pagination. Returns the raw event payload.
        Useful for investigating sign-in failures and admin actions.
        """
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if from_timestamp is not None:
            params["from_timestamp"] = from_timestamp
        if event_type_id is not None:
            params["event_type_id"] = event_type_id
        return self._client.get("/api/1/events", params=params).json()
