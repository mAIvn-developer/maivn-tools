"""Duo Security Admin API connector.

The Duo Admin API uses a per-request HMAC signature derived from the
integration key, secret, and request canonicalization. This toolset
computes the signature in-process so the caller only provides
``ikey`` / ``skey`` / ``api_host``.
"""

# pyright: strict

from __future__ import annotations

import base64
import email.utils
import hashlib
import hmac
import time
import urllib.parse
from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.base import AuthStrategy
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_GROUPS_OUTPUT, LIST_PHONES_OUTPUT, LIST_USERS_OUTPUT

# Default authentication-log lookback window: 24 hours, expressed in
# milliseconds. The v2 logs endpoint requires both mintime and maxtime as
# 13-digit Unix millisecond timestamps.
_AUTH_LOG_WINDOW_MS = 24 * 60 * 60 * 1000


class _DuoAuth(AuthStrategy):
    """Compute the per-request Duo Admin API signature."""

    mode = AuthMode.API_KEY

    def __init__(self, ikey: str, skey: str, host: str) -> None:
        self._ikey = ikey
        self._skey = skey
        self._host = host

    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        method = str(request.get("method", "GET")).upper()
        url = str(request.get("url", ""))
        parsed = urllib.parse.urlparse(url)
        path: str = parsed.path
        params: dict[str, Any] = dict(request.get("params") or {})
        flat_params: list[tuple[str, str]] = []
        for key, value in params.items():
            if isinstance(value, (list, tuple)):
                sequence = cast("list[Any] | tuple[Any, ...]", value)
                for v in sequence:
                    flat_params.append((key, str(v)))
            else:
                flat_params.append((key, str(value)))
        flat_params.sort()
        encoded = urllib.parse.urlencode(flat_params)
        date = email.utils.formatdate(usegmt=True)
        canonical = "\n".join([date, method, self._host, path, encoded])
        signature = hmac.new(
            self._skey.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()
        token = base64.b64encode(f"{self._ikey}:{signature}".encode()).decode("ascii")
        headers = dict(request.get("headers") or {})
        headers["Authorization"] = f"Basic {token}"
        headers["Date"] = date
        request["headers"] = headers
        return request

    def describe(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "scheme": "duo-hmac-sha512"}


@toolset(prefix="duo")
class DuoToolSet:
    """A connector for the Duo Security Admin API.

    Args:
        ikey: Integration key.
        skey: Secret key.
        api_host: API hostname (e.g. ``"api-abc123.duosecurity.com"``).
    """

    metadata = ProviderMetadata(
        name="duo",
        display_name="Duo Security",
        version="0.1.0",
        description="Users, phones, tokens, groups, integrations, and logs.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://duo.com/docs/adminapi",
        homepage_url="https://duo.com/",
        tags=("security", "mfa"),
    )

    def __init__(
        self,
        *,
        ikey: str,
        skey: str,
        api_host: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not ikey or not skey or not api_host:
            raise ValueError("ikey, skey, and api_host are required")
        self.connection = connection
        self._client = HttpClient(
            base_url=f"https://{api_host}",
            auth=_DuoAuth(ikey, skey, api_host),
            transport=transport,
            default_headers={"Accept": "application/json"},
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
            "username": user.get("username", ""),
            "email": user.get("email", ""),
            "realname": user.get("realname", ""),
            "status": user.get("status", ""),
            "last_login": user.get("last_login", ""),
        }
        if include_ids:
            summary["user_id"] = user.get("user_id", "")
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
            "description": group.get("desc", ""),
            "status": group.get("status", ""),
            "mobile_otp_enabled": bool(group.get("mobile_otp_enabled", False)),
            "push_enabled": bool(group.get("push_enabled", False)),
        }
        if include_ids:
            summary["group_id"] = group.get("group_id", "")
        return summary

    @staticmethod
    def _phone_summary(
        phone: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "phone_ref": f"phone_{index}",
            "number": phone.get("number", ""),
            "name": phone.get("name", ""),
            "platform": phone.get("platform", ""),
            "type": phone.get("type", ""),
            "activated": bool(phone.get("activated", False)),
        }
        if include_ids:
            summary["phone_id"] = phone.get("phone_id", "")
        return summary

    @staticmethod
    def _resolve_user_id(user_or_id: Any) -> str:
        if isinstance(user_or_id, str) and user_or_id:
            return user_or_id
        if isinstance(user_or_id, dict):
            mapping = cast("dict[str, Any]", user_or_id)
            for key in ("user_id", "id"):
                value: Any = mapping.get(key)
                if isinstance(value, str) and value:
                    return value
        raise ValueError("expected a user id string or a user dict with 'user_id'")

    @staticmethod
    def _coerce_response(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            mapping = cast("dict[str, Any]", payload)
            response_field: Any = mapping.get("response")
            if isinstance(response_field, list):
                items = cast("list[Any]", response_field)
                return [r for r in items if isinstance(r, dict)]
        return []

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_USERS_OUTPUT)
    def list_users(
        self,
        *,
        username: str | None = None,
        offset: int = 0,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Duo users.

        Returns ``{"users": [...]}`` with ``user_ref``, ``username``,
        ``email``, ``realname``, ``status``, ``last_login``. Raw
        ``user_id`` is omitted by default.
        """
        if limit < 1 or limit > 300:
            raise ValueError("limit must be between 1 and 300")
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if username is not None:
            params["username"] = username
        payload = self._client.get("/admin/v1/users", params=params).json()
        raw_users = self._coerce_response(payload)
        summaries = [
            self._user_summary(user, index=index, include_ids=include_ids)
            for index, user in enumerate(raw_users, start=1)
        ]
        result: dict[str, Any] = {"users": summaries}
        if isinstance(payload, dict) and "metadata" in payload:
            result["metadata"] = payload["metadata"]
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self, user_id: str) -> dict[str, Any]:
        """Return one Duo user (full record).

        Returns the raw Duo user resource including enrolled phones,
        tokens, groups, and bypass codes.
        """
        if not user_id:
            raise ValueError("user_id is required")
        return self._client.get(f"/admin/v1/users/{user_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_user(
        self,
        *,
        username: str,
        email: str | None = None,
        realname: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        """Create a Duo user.

        Returns the new user resource. Status must be one of: active,
        bypass, disabled, or ``"locked out"`` (a space, not a hyphen).
        ``"pending deletion"`` is a read-only status the API returns and
        cannot be set as input.
        """
        if not username:
            raise ValueError("username is required")
        if status not in {
            "active",
            "bypass",
            "disabled",
            "locked out",
        }:
            raise ValueError("invalid status")
        params: dict[str, Any] = {"username": username, "status": status}
        if email is not None:
            params["email"] = email
        if realname is not None:
            params["realname"] = realname
        return self._client.post("/admin/v1/users", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def disable_user(self, user_id: Any) -> dict[str, Any]:
        """Disable a user (sets status to ``disabled``). ``user_id`` accepts dict or string.

        Destructive — the user can no longer authenticate via Duo. Confirm
        with the user before calling. Reversible by setting status back
        to ``active`` via the admin UI.
        """
        resolved_id = self._resolve_user_id(user_id)
        return self._client.post(
            f"/admin/v1/users/{resolved_id}",
            params={"status": "disabled"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_user(self, user_id: Any) -> dict[str, Any]:
        """Permanently delete a Duo user. ``user_id`` accepts dict or string.

        Destructive — removes enrollment, paired devices, and bypass
        codes. Confirm with the user before calling.
        """
        resolved_id = self._resolve_user_id(user_id)
        return self._client.delete(f"/admin/v1/users/{resolved_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_PHONES_OUTPUT)
    def list_phones(
        self,
        *,
        number: str | None = None,
        offset: int = 0,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Duo phones.

        Returns ``{"phones": [...]}`` with ``phone_ref``, ``number``,
        ``name``, ``platform``, ``type``, ``activated``.
        """
        if limit < 1 or limit > 300:
            raise ValueError("limit must be between 1 and 300")
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if number is not None:
            params["number"] = number
        payload = self._client.get("/admin/v1/phones", params=params).json()
        raw_phones = self._coerce_response(payload)
        summaries = [
            self._phone_summary(phone, index=index, include_ids=include_ids)
            for index, phone in enumerate(raw_phones, start=1)
        ]
        return {"phones": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_GROUPS_OUTPUT)
    def list_groups(
        self,
        *,
        offset: int = 0,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Duo groups.

        Returns ``{"groups": [...]}`` with ``group_ref``, ``name``,
        ``description``, ``status``, ``mobile_otp_enabled``,
        ``push_enabled``.
        """
        if limit < 1 or limit > 300:
            raise ValueError("limit must be between 1 and 300")
        payload = self._client.get(
            "/admin/v1/groups",
            params={"offset": offset, "limit": limit},
        ).json()
        raw_groups = self._coerce_response(payload)
        summaries = [
            self._group_summary(group, index=index, include_ids=include_ids)
            for index, group in enumerate(raw_groups, start=1)
        ]
        return {"groups": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def associate_group_with_user(
        self,
        *,
        user_id: Any,
        group_id: str,
    ) -> dict[str, Any]:
        """Add a group to a user. ``user_id`` accepts dict or string.

        Returns the Duo response.
        """
        if not group_id:
            raise ValueError("group_id is required")
        resolved_id = self._resolve_user_id(user_id)
        return self._client.post(
            f"/admin/v1/users/{resolved_id}/groups",
            params={"group_id": group_id},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_integrations(self) -> dict[str, Any]:
        """List Duo integrations.

        Returns the raw Duo integrations payload. Each integration has
        a name, type, and enrollment policy. Uses the current ``/admin/v3``
        endpoint (the legacy ``/admin/v1`` route is deprecated, exposes
        secret keys in plaintext, and omits Duo SSO applications).
        """
        return self._client.get("/admin/v3/integrations").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_authentication_logs(
        self,
        *,
        mintime: int | None = None,
        maxtime: int | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return Duo authentication-log records.

        Returns the raw Duo v2 auth log payload. Useful for investigating
        MFA failures and unusual access. ``mintime`` and ``maxtime`` are
        Unix timestamps in MILLISECONDS (13-digit) and are both required by
        the v2 endpoint. When either is omitted it defaults to a 24-hour
        window ending now (``maxtime = now``, ``mintime = now - 24h``).
        """
        now_ms = int(time.time() * 1000)
        if maxtime is None:
            maxtime = now_ms
        if mintime is None:
            mintime = maxtime - _AUTH_LOG_WINDOW_MS
        params: dict[str, Any] = {
            "limit": limit,
            "mintime": int(mintime),
            "maxtime": int(maxtime),
        }
        return self._client.get("/admin/v2/logs/authentication", params=params).json()
