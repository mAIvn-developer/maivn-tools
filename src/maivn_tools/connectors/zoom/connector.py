"""Zoom Meetings API v2 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

_DEFAULT_LIST_LIMIT = 25


@toolset(prefix="zoom")
class ZoomToolSet:
    """A connector for the Zoom REST API v2.

    Args:
        token: OAuth bearer or server-to-server OAuth access token.
        base_url: API root.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="zoom",
        display_name="Zoom",
        version="0.1.0",
        description="Manage Zoom meetings, webinars, users, and recordings.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE, AuthMode.OAUTH2_CLIENT_CREDENTIALS),
        scopes={
            "user:read": "Read users.",
            "meeting:read": "Read meetings.",
            "meeting:write": "Create and update meetings.",
            "recording:read": "Read recordings.",
            "webinar:read": "Read webinars.",
            "webinar:write": "Manage webinars.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developers.zoom.us/docs/api/",
        homepage_url="https://zoom.us/",
        tags=("video", "meetings"),
    )

    def __init__(
        self,
        *,
        token: str,
        base_url: str = "https://api.zoom.us",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not token:
            raise ValueError("token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Users

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_users(
        self,
        *,
        status: str | None = None,
        page_size: int = _DEFAULT_LIST_LIMIT,
        page_number: int | None = None,
        next_page_token: str | None = None,
    ) -> dict[str, Any]:
        """List Zoom users in the account.

        Returns the raw Zoom ``users`` payload. ``status`` filters to
        ``active`` / ``inactive`` / ``pending`` accounts when supplied.
        """
        if status is not None and status not in {"active", "inactive", "pending"}:
            raise ValueError("status must be active/inactive/pending")
        params: dict[str, Any] = {"page_size": page_size}
        if status is not None:
            params["status"] = status
        if page_number is not None:
            params["page_number"] = page_number
        if next_page_token is not None:
            params["next_page_token"] = next_page_token
        return self._client.get("/v2/users", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self, user_id: str = "me") -> dict[str, Any]:
        """Return a Zoom user. ``"me"`` returns the current user."""
        if not user_id:
            raise ValueError("user_id must be a non-empty string")
        return self._client.get(f"/v2/users/{user_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_user(
        self,
        *,
        action: str,
        email: str,
        first_name: str | None = None,
        last_name: str | None = None,
        user_type: int = 1,
    ) -> dict[str, Any]:
        """Create a Zoom user."""
        if action not in {"create", "autoCreate", "custCreate", "ssoCreate"}:
            raise ValueError("invalid action")
        if not email:
            raise ValueError("email must be a non-empty string")
        user_info: dict[str, Any] = {"email": email, "type": user_type}
        if first_name is not None:
            user_info["first_name"] = first_name
        if last_name is not None:
            user_info["last_name"] = last_name
        return self._client.post(
            "/v2/users",
            json={"action": action, "user_info": user_info},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_user(self, user_id: str, *, action: str = "disassociate") -> dict[str, Any]:
        """Delete or disassociate a user.

        Destructive: ``action="delete"`` permanently removes the user;
        ``action="disassociate"`` (default) keeps the user but removes them
        from the account.
        """
        if not user_id:
            raise ValueError("user_id must be a non-empty string")
        if action not in {"disassociate", "delete"}:
            raise ValueError("action must be disassociate or delete")
        self._client.delete(f"/v2/users/{user_id}", params={"action": action})
        return {"id": user_id, "deleted": True, "action": action}

    # MARK: - Meetings

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_meetings(
        self,
        user_id: str = "me",
        *,
        type: str = "scheduled",
        page_size: int = _DEFAULT_LIST_LIMIT,
        next_page_token: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List meetings owned by a user.

        Best first tool to find scheduled or recent meetings. By default
        returns compact summaries with ``meeting_ref`` (stable
        ``meeting_1``, ``meeting_2``), ``topic``, ``start_time``,
        ``duration``, and ``join_url``. Raw Zoom meeting IDs are omitted by
        default; pass ``include_ids=True`` when a follow-up tool needs
        ``meeting_id`` (e.g. :meth:`get_meeting`, :meth:`update_meeting`,
        :meth:`delete_meeting`). ``include_metadata=False`` returns the raw
        Zoom response.
        """
        if not user_id:
            raise ValueError("user_id must be a non-empty string")
        if type not in {"scheduled", "live", "upcoming", "upcoming_meetings", "previous_meetings"}:
            raise ValueError("invalid type")
        params: dict[str, Any] = {"type": type, "page_size": page_size}
        if next_page_token is not None:
            params["next_page_token"] = next_page_token
        payload: dict[str, Any] = self._client.get(
            f"/v2/users/{user_id}/meetings", params=params
        ).json()
        if not include_metadata:
            return payload

        summaries: list[dict[str, Any]] = []
        meetings_raw: object = payload.get("meetings", []) or []
        meetings_list: list[Any] = (
            cast("list[Any]", meetings_raw) if isinstance(meetings_raw, list) else []
        )
        for index, meeting in enumerate(meetings_list, start=1):
            if not isinstance(meeting, dict):
                continue
            meeting_dict = cast("dict[str, Any]", meeting)
            summary: dict[str, Any] = {
                "meeting_ref": f"meeting_{index}",
                "topic": meeting_dict.get("topic", ""),
                "start_time": meeting_dict.get("start_time", ""),
                "duration": meeting_dict.get("duration", 0),
                "join_url": meeting_dict.get("join_url", ""),
            }
            if include_ids:
                summary["meeting_id"] = meeting_dict.get("id", "")
            summaries.append(summary)
        return {
            "meetings": summaries,
            "next_page_token": payload.get("next_page_token"),
            "page_size": payload.get("page_size"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_meeting(self, meeting_id: Any) -> dict[str, Any]:
        """Return one meeting by ID.

        ``meeting_id`` accepts a Zoom meeting ID or a meeting-summary dict
        from :meth:`list_meetings` (with ``include_ids=True``).
        """
        resolved = self._resolve_meeting_id(meeting_id)
        return self._client.get(f"/v2/meetings/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_meeting(
        self,
        *,
        user_id: str = "me",
        topic: str,
        type: int = 2,
        start_time: str | None = None,
        duration: int | None = None,
        timezone: str | None = None,
        agenda: str | None = None,
        password: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Schedule a meeting under a user.

        Returns the new meeting resource. ``type`` is the Zoom meeting type
        code (1=instant, 2=scheduled, 3=recurring no fixed time, 8=recurring
        fixed time).
        """
        if not topic:
            raise ValueError("topic must be a non-empty string")
        body: dict[str, Any] = {"topic": topic, "type": type}
        if start_time is not None:
            body["start_time"] = start_time
        if duration is not None:
            body["duration"] = duration
        if timezone is not None:
            body["timezone"] = timezone
        if agenda is not None:
            body["agenda"] = agenda
        if password is not None:
            body["password"] = password
        if settings is not None:
            body["settings"] = settings
        return self._client.post(f"/v2/users/{user_id}/meetings", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_meeting(self, meeting_id: Any, fields: dict[str, Any]) -> dict[str, Any]:
        """Patch a meeting.

        ``meeting_id`` tolerates the dict returned by :meth:`list_meetings`.
        """
        resolved = self._resolve_meeting_id(meeting_id)
        if not fields:
            raise ValueError("fields must be a non-empty dict")
        response = self._client.patch(f"/v2/meetings/{resolved}", json=fields)
        return {"id": resolved, "updated": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_meeting(
        self,
        meeting_id: Any,
        *,
        schedule_for_reminder: bool = False,
        cancel_meeting_reminder: bool = False,
    ) -> dict[str, Any]:
        """Delete a meeting.

        Destructive: the meeting is removed and registrants notified per the
        reminder flags. Confirm with the user first.
        """
        resolved = self._resolve_meeting_id(meeting_id)
        self._client.delete(
            f"/v2/meetings/{resolved}",
            params={
                "schedule_for_reminder": str(schedule_for_reminder).lower(),
                "cancel_meeting_reminder": str(cancel_meeting_reminder).lower(),
            },
        )
        return {"id": resolved, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_meeting_participants(
        self,
        meeting_id: Any,
        *,
        page_size: int = _DEFAULT_LIST_LIMIT,
        next_page_token: str | None = None,
    ) -> dict[str, Any]:
        """List participants of a meeting (reporting endpoint)."""
        resolved = self._resolve_meeting_id(meeting_id)
        params: dict[str, Any] = {"page_size": page_size}
        if next_page_token is not None:
            params["next_page_token"] = next_page_token
        return self._client.get(
            f"/v2/report/meetings/{resolved}/participants",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_meeting_registrants(
        self,
        meeting_id: Any,
        *,
        status: str | None = None,
        page_size: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List registrants for a meeting."""
        resolved = self._resolve_meeting_id(meeting_id)
        params: dict[str, Any] = {"page_size": page_size}
        if status is not None:
            params["status"] = status
        return self._client.get(
            f"/v2/meetings/{resolved}/registrants",
            params=params,
        ).json()

    # MARK: - Webinars

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_webinars(
        self,
        user_id: str = "me",
        *,
        page_size: int = _DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List webinars owned by a user."""
        return self._client.get(
            f"/v2/users/{user_id}/webinars",
            params={"page_size": page_size},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_webinar(self, webinar_id: str | int) -> dict[str, Any]:
        """Return one webinar by ID."""
        return self._client.get(f"/v2/webinars/{webinar_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_webinar(
        self,
        *,
        user_id: str = "me",
        topic: str,
        type: int = 5,
        start_time: str | None = None,
        duration: int | None = None,
        timezone: str | None = None,
        agenda: str | None = None,
    ) -> dict[str, Any]:
        """Create a webinar."""
        if not topic:
            raise ValueError("topic must be a non-empty string")
        body: dict[str, Any] = {"topic": topic, "type": type}
        if start_time is not None:
            body["start_time"] = start_time
        if duration is not None:
            body["duration"] = duration
        if timezone is not None:
            body["timezone"] = timezone
        if agenda is not None:
            body["agenda"] = agenda
        return self._client.post(f"/v2/users/{user_id}/webinars", json=body).json()

    # MARK: - Recordings

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_recordings(
        self,
        user_id: str = "me",
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        page_size: int = _DEFAULT_LIST_LIMIT,
        next_page_token: str | None = None,
    ) -> dict[str, Any]:
        """List cloud recordings for a user."""
        params: dict[str, Any] = {"page_size": page_size}
        if from_date is not None:
            params["from"] = from_date
        if to_date is not None:
            params["to"] = to_date
        if next_page_token is not None:
            params["next_page_token"] = next_page_token
        return self._client.get(f"/v2/users/{user_id}/recordings", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_meeting_recordings(self, meeting_id: Any) -> dict[str, Any]:
        """Return recordings for a single meeting."""
        resolved = self._resolve_meeting_id(meeting_id)
        return self._client.get(f"/v2/meetings/{resolved}/recordings").json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_meeting_recordings(
        self,
        meeting_id: Any,
        *,
        action: str = "trash",
    ) -> dict[str, Any]:
        """Trash or permanently delete recordings.

        Destructive: ``action="trash"`` (default) is reversible until purged
        by Zoom retention; ``action="delete"`` is irreversible. Confirm with
        the user first.
        """
        resolved = self._resolve_meeting_id(meeting_id)
        if action not in {"trash", "delete"}:
            raise ValueError("action must be trash or delete")
        self._client.delete(
            f"/v2/meetings/{resolved}/recordings",
            params={"action": action},
        )
        return {"id": resolved, "deleted": True, "action": action}

    # MARK: - Internal

    @staticmethod
    def _resolve_meeting_id(meeting: Any) -> str | int:
        if isinstance(meeting, dict):
            meeting_dict = cast("dict[str, Any]", meeting)
            for key in ("meeting_id", "id"):
                value: object = meeting_dict.get(key)
                if isinstance(value, str | int) and value != "":
                    return value
            raise ValueError("meeting dict must contain meeting_id or id")
        if isinstance(meeting, str):
            if not meeting:
                raise ValueError("meeting_id is required")
            return meeting
        if isinstance(meeting, int):
            if not meeting:
                raise ValueError("meeting_id is required")
            return meeting
        raise ValueError("meeting_id must be a string, int, or dict")
