"""Okta Management API connector."""

# pyright: strict

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterable
from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpResponse, HttpTransport
from .output_schemas import (
    LIST_APPLICATIONS_OUTPUT,
    LIST_GROUPS_OUTPUT,
    LIST_USERS_OUTPUT,
)

# Okta returns pagination links exclusively in the HTTP ``Link`` response
# header, e.g. ``<https://org/api/v1/users?limit=200&after=...>; rel="next"``.
# Each entry is ``<url>; rel="<rel>"``; we extract the ``after`` cursor from
# the URL whose rel is ``next``.
_LINK_HEADER_ENTRY = re.compile(r'<(?P<url>[^>]+)>\s*;\s*rel="(?P<rel>[^"]+)"')


@toolset(prefix="okta")
class OktaToolSet:
    """A connector for the Okta Management API.

    Args:
        org_url: Okta org URL (e.g. ``"https://dev-123.okta.com"``).
        api_token: SSWS API token.
    """

    metadata = ProviderMetadata(
        name="okta",
        display_name="Okta",
        version="0.1.0",
        description="Users, groups, applications, factors, and system logs.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.okta.com/docs/reference/api/",
        homepage_url="https://www.okta.com/",
        tags=("identity", "sso", "auth"),
    )

    def __init__(
        self,
        *,
        org_url: str,
        api_token: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not org_url or not api_token:
            raise ValueError("org_url and api_token are required")
        self.connection = connection
        self._client = HttpClient(
            base_url=org_url.rstrip("/"),
            auth=ApiKeyAuth(api_token, header="Authorization", prefix="SSWS"),
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
        profile_value: Any = user.get("profile")
        profile: dict[str, Any] = (
            cast("dict[str, Any]", profile_value) if isinstance(profile_value, dict) else {}
        )
        summary: dict[str, Any] = {
            "user_ref": f"user_{index}",
            "email": profile.get("email", "") or profile.get("login", ""),
            "name": " ".join(
                part
                for part in (
                    profile.get("firstName", ""),
                    profile.get("lastName", ""),
                )
                if part
            ).strip(),
            "login": profile.get("login", ""),
            "status": user.get("status", ""),
            "last_login": user.get("lastLogin", ""),
        }
        if include_ids:
            summary["user_id"] = user.get("id", "")
        return summary

    @staticmethod
    def _group_summary(
        group: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        profile_value: Any = group.get("profile")
        profile: dict[str, Any] = (
            cast("dict[str, Any]", profile_value) if isinstance(profile_value, dict) else {}
        )
        summary: dict[str, Any] = {
            "group_ref": f"group_{index}",
            "name": profile.get("name", ""),
            "description": profile.get("description", ""),
            "type": group.get("type", ""),
        }
        if include_ids:
            summary["group_id"] = group.get("id", "")
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
            "label": app.get("label", ""),
            "status": app.get("status", ""),
            "sign_on_mode": app.get("signOnMode", ""),
        }
        if include_ids:
            summary["app_id"] = app.get("id", "")
        return summary

    @staticmethod
    def _resolve_user_id(user_or_id: Any) -> str:
        """Accept an Okta user id, login, email, or a user dict from list_users."""
        if isinstance(user_or_id, str) and user_or_id:
            return user_or_id
        if isinstance(user_or_id, dict):
            user_dict: dict[str, Any] = cast("dict[str, Any]", user_or_id)
            for key in ("user_id", "id"):
                value: Any = user_dict.get(key)
                if isinstance(value, str) and value:
                    return value
            profile_value: Any = user_dict.get("profile")
            if isinstance(profile_value, dict):
                profile: dict[str, Any] = cast("dict[str, Any]", profile_value)
                login: Any = profile.get("login")
                if isinstance(login, str) and login:
                    return login
        raise ValueError("expected a user id string or a user dict with 'id'")

    @staticmethod
    def _coerce_user_list(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if isinstance(payload, list):
            payload_list: list[Any] = cast("list[Any]", payload)
            return [u for u in payload_list if isinstance(u, dict)], {}
        if isinstance(payload, dict):
            payload_dict: dict[str, Any] = cast("dict[str, Any]", payload)
            users_field: Iterable[Any] = payload_dict.get("users", [])
            return (
                [u for u in users_field if isinstance(u, dict)],
                {k: v for k, v in payload_dict.items() if k != "users"},
            )
        return [], {}

    @staticmethod
    def _next_after(response: HttpResponse) -> str | None:
        """Extract the ``after`` cursor from Okta's ``Link`` response header.

        Okta surfaces pagination only via the ``Link`` header's
        ``rel="next"`` URL (never in the body). Returns the ``after`` query
        param from that URL, or ``None`` when there is no next page.
        """
        link = response.header("Link")
        if not link:
            return None
        for match in _LINK_HEADER_ENTRY.finditer(link):
            if match.group("rel") != "next":
                continue
            query = urllib.parse.urlparse(match.group("url")).query
            after = urllib.parse.parse_qs(query).get("after")
            if after:
                return after[0]
        return None

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_USERS_OUTPUT)
    def list_users(
        self,
        *,
        q: str | None = None,
        filter: str | None = None,
        search: str | None = None,
        limit: int = 25,
        after: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search Okta users (free text ``q``, SCIM ``filter``, or SCIM ``search``).

        Best first tool for finding a user. Returns compact summaries with a
        stable ``user_ref`` plus email, name, login, status, and last_login.
        Raw Okta ``user_id`` values are omitted by default — they are
        internal handles. Set ``include_ids=True`` only when a follow-up
        tool (update_user, suspend_user, deactivate_user) needs them. Use
        ``after`` for pagination.
        """
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        params: dict[str, Any] = {"limit": limit}
        if q is not None:
            params["q"] = q
        if filter is not None:
            params["filter"] = filter
        if search is not None:
            params["search"] = search
        if after is not None:
            params["after"] = after
        response = self._client.get("/api/v1/users", params=params)
        raw_users, wrapper = self._coerce_user_list(response.json())
        summaries = [
            self._user_summary(user, index=index, include_ids=include_ids)
            for index, user in enumerate(raw_users, start=1)
        ]
        result: dict[str, Any] = {"users": summaries}
        result.update(wrapper)
        result["next_after"] = self._next_after(response)
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self, user_id: str) -> dict[str, Any]:
        """Return one Okta user (full profile) by id, login, or email.

        Returns the raw user resource (``id``, ``status``, ``profile``,
        ``credentials``, ``_links``). Use after list_users when you need
        the full profile.
        """
        if not user_id:
            raise ValueError("user_id is required")
        return self._client.get(f"/api/v1/users/{user_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_user(
        self,
        *,
        profile: dict[str, Any],
        credentials: dict[str, Any] | None = None,
        group_ids: list[str] | None = None,
        activate: bool = True,
    ) -> dict[str, Any]:
        """Create a new Okta user.

        ``profile`` must include at least ``firstName``, ``lastName``,
        ``email``, and ``login``. Returns the new user resource. Confirm
        the email and group assignments with the user before calling.
        """
        if not profile:
            raise ValueError("profile is required")
        body: dict[str, Any] = {"profile": profile}
        if credentials is not None:
            body["credentials"] = credentials
        if group_ids is not None:
            body["groupIds"] = group_ids
        return self._client.post(
            "/api/v1/users",
            params={"activate": str(activate).lower()},
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_user(
        self,
        user_id: Any,
        *,
        profile: dict[str, Any] | None = None,
        credentials: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a user's profile or credentials. ``user_id`` accepts dict or string.

        Returns the updated user resource. Confirm with the user before
        changing identity fields.
        """
        resolved_id = self._resolve_user_id(user_id)
        body: dict[str, Any] = {}
        if profile is not None:
            body["profile"] = profile
        if credentials is not None:
            body["credentials"] = credentials
        if not body:
            raise ValueError("at least one update field is required")
        return self._client.post(f"/api/v1/users/{resolved_id}", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def suspend_user(self, user_id: Any) -> dict[str, Any]:
        """Suspend a user (blocks sign-in; reversible via unsuspend_user).

        ``user_id`` accepts dict or string. Destructive — confirm with the
        user. Returns ``{"status": ..., "suspended": True}``.
        """
        resolved_id = self._resolve_user_id(user_id)
        response = self._client.post(f"/api/v1/users/{resolved_id}/lifecycle/suspend")
        return {"status": response.status, "suspended": True}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def unsuspend_user(self, user_id: Any) -> dict[str, Any]:
        """Reverse a prior suspension. ``user_id`` accepts dict or string.

        Returns ``{"status": ..., "unsuspended": True}``.
        """
        resolved_id = self._resolve_user_id(user_id)
        response = self._client.post(f"/api/v1/users/{resolved_id}/lifecycle/unsuspend")
        return {"status": response.status, "unsuspended": True}

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def deactivate_user(self, user_id: Any) -> dict[str, Any]:
        """Deactivate a user (precondition for delete). ``user_id`` accepts dict or string.

        Destructive — terminates sessions, removes from all groups, and is
        only reversible by reactivation within Okta's retention window.
        Confirm with the user. Returns
        ``{"status": ..., "deactivated": True}``.
        """
        resolved_id = self._resolve_user_id(user_id)
        response = self._client.post(f"/api/v1/users/{resolved_id}/lifecycle/deactivate")
        return {"status": response.status, "deactivated": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_GROUPS_OUTPUT)
    def list_groups(
        self,
        *,
        q: str | None = None,
        filter: str | None = None,
        limit: int = 25,
        after: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Okta groups.

        Returns ``{"groups": [...]}`` with ``group_ref``, ``name``,
        ``description``, and ``type``. Raw ``group_id`` values are omitted
        by default — set ``include_ids=True`` when add_user_to_group needs
        them.
        """
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        params: dict[str, Any] = {"limit": limit}
        if q is not None:
            params["q"] = q
        if filter is not None:
            params["filter"] = filter
        if after is not None:
            params["after"] = after
        response = self._client.get("/api/v1/groups", params=params)
        payload: Any = response.json()
        raw_groups: list[dict[str, Any]] = (
            [g for g in cast("list[Any]", payload) if isinstance(g, dict)]
            if isinstance(payload, list)
            else []
        )
        summaries = [
            self._group_summary(group, index=index, include_ids=include_ids)
            for index, group in enumerate(raw_groups, start=1)
        ]
        return {"groups": summaries, "next_after": self._next_after(response)}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_user_to_group(
        self,
        *,
        group_id: str,
        user_id: Any,
    ) -> dict[str, Any]:
        """Assign a user to a group.

        ``user_id`` accepts dict or string. ``group_id`` must be a raw
        Okta group id — call list_groups(include_ids=True) to get it.
        Returns ``{"status": ..., "assigned": True}``.
        """
        if not group_id:
            raise ValueError("group_id is required")
        resolved_id = self._resolve_user_id(user_id)
        response = self._client.put(f"/api/v1/groups/{group_id}/users/{resolved_id}")
        return {"status": response.status, "assigned": True}

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def remove_user_from_group(
        self,
        *,
        group_id: str,
        user_id: Any,
    ) -> dict[str, Any]:
        """Remove a user from a group. ``user_id`` accepts dict or string.

        Destructive — the user loses any access derived from that group.
        Returns ``{"status": ..., "removed": True}``.
        """
        if not group_id:
            raise ValueError("group_id is required")
        resolved_id = self._resolve_user_id(user_id)
        response = self._client.delete(f"/api/v1/groups/{group_id}/users/{resolved_id}")
        return {"status": response.status, "removed": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_APPLICATIONS_OUTPUT)
    def list_applications(
        self,
        *,
        q: str | None = None,
        limit: int = 25,
        after: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Okta applications (OIDC + SAML clients).

        Returns ``{"apps": [...]}`` with ``app_ref``, ``name``, ``label``,
        ``status``, and ``sign_on_mode``. Raw ``app_id`` values are
        omitted by default. Use ``after`` for pagination.
        """
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        params: dict[str, Any] = {"limit": limit}
        if q is not None:
            params["q"] = q
        if after is not None:
            params["after"] = after
        response = self._client.get("/api/v1/apps", params=params)
        payload: Any = response.json()
        raw_apps: list[dict[str, Any]] = (
            [a for a in cast("list[Any]", payload) if isinstance(a, dict)]
            if isinstance(payload, list)
            else []
        )
        summaries = [
            self._app_summary(app, index=index, include_ids=include_ids)
            for index, app in enumerate(raw_apps, start=1)
        ]
        return {"apps": summaries, "next_after": self._next_after(response)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_factors(self, user_id: str) -> dict[str, Any]:
        """List MFA factors enrolled for a user.

        Returns the raw Okta factor list (each entry includes
        ``factorType``, ``provider``, ``status``).
        """
        if not user_id:
            raise ValueError("user_id is required")
        return self._client.get(f"/api/v1/users/{user_id}/factors").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_system_logs(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        filter: str | None = None,
        limit: int = 100,
        after: str | None = None,
    ) -> dict[str, Any]:
        """Query the Okta system log.

        Returns ``{"events": [...], "next_after": ...}`` where ``events`` is
        the raw Okta system log payload. Useful for investigating suspicious
        sign-ins, MFA failures, and admin changes. Pass ``since`` / ``until``
        as ISO-8601 timestamps and ``after`` for pagination.
        """
        params: dict[str, Any] = {"limit": limit}
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        if filter is not None:
            params["filter"] = filter
        if after is not None:
            params["after"] = after
        response = self._client.get("/api/v1/logs", params=params)
        return {"events": response.json(), "next_after": self._next_after(response)}
