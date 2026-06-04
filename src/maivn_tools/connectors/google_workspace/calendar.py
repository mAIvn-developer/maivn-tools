"""Google Calendar API connector."""
# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from ._shared import TokenSource, make_bearer_auth

CALENDAR_API_URL = "https://www.googleapis.com/calendar/v3"
_DEFAULT_EVENT_LIST_MAX = 25
_DEFAULT_CALENDAR_LIST_MAX = 25


@toolset(prefix="google_calendar")
class GoogleCalendarToolSet:
    """A connector for Google Calendar.

    Args:
        token: OAuth bearer credential. Accepts an :class:`OAuth2Token`, a
            callable returning one, or a raw access-token string.
        transport: Optional :class:`HttpTransport` override.
        base_url: Override for tests or for self-hosted mirrors.
    """

    metadata = ProviderMetadata(
        name="google_calendar",
        display_name="Google Calendar",
        version="0.1.0",
        description="Read and write events across Google Calendar.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "https://www.googleapis.com/auth/calendar.readonly": "Read calendars and events.",
            "https://www.googleapis.com/auth/calendar.events": "Manage events.",
            "https://www.googleapis.com/auth/calendar": "Full calendar access.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developers.google.com/calendar/api",
        homepage_url="https://calendar.google.com",
        tags=("calendar", "google"),
    )

    def __init__(
        self,
        token: TokenSource,
        *,
        transport: HttpTransport | None = None,
        base_url: str = CALENDAR_API_URL,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url,
            auth=make_bearer_auth(token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_calendars(
        self,
        *,
        max_results: int = _DEFAULT_CALENDAR_LIST_MAX,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List calendars the authenticated user can see.

        Returns compact summaries: each calendar gets a stable
        ``calendar_ref`` (``calendar_1``, ``calendar_2``, ...),
        ``summary`` (display name), ``time_zone``, ``access_role``, and
        ``primary`` flag. Raw Google calendar IDs are omitted by default
        because they are internal handles. Set ``include_ids=True`` only
        when a follow-up tool such as :meth:`list_events` or
        :meth:`create_event` needs the raw ``calendar_id`` (Google uses
        email-like IDs but the agent should not surface them as final
        answers).
        """
        if max_results < 1 or max_results > 250:
            raise ValueError("max_results must be between 1 and 250")
        payload: dict[str, Any] = self._client.get(
            "/users/me/calendarList",
            params={"maxResults": max_results},
        ).json()
        calendars: list[dict[str, Any]] = []
        items: Any = payload.get("items", [])
        if isinstance(items, list):
            calendar_items = cast("list[Any]", items)
            for index, calendar in enumerate(calendar_items, start=1):
                if not isinstance(calendar, dict):
                    continue
                calendar_dict = cast("dict[str, Any]", calendar)
                summary: dict[str, Any] = {
                    "calendar_ref": f"calendar_{index}",
                    "summary": calendar_dict.get("summary", ""),
                    "description": calendar_dict.get("description", ""),
                    "time_zone": calendar_dict.get("timeZone", ""),
                    "access_role": calendar_dict.get("accessRole", ""),
                    "primary": calendar_dict.get("primary", False),
                }
                if include_ids:
                    summary["calendar_id"] = calendar_dict.get("id", "")
                calendars.append(summary)
        return {
            "calendars": calendars,
            "nextPageToken": payload.get("nextPageToken"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_calendar(self, calendar_id: Any = "primary") -> dict[str, Any]:
        """Return a single calendar by ID.

        ``calendar_id`` accepts a raw ID string, a calendar dict from
        :meth:`list_calendars` (with ``include_ids=True``), or the
        literal ``"primary"``.
        """
        resolved = _extract_calendar_id(calendar_id)
        return self._client.get(f"/calendars/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_events(
        self,
        calendar_id: Any = "primary",
        *,
        time_min: str | None = None,
        time_max: str | None = None,
        q: str | None = None,
        max_results: int = _DEFAULT_EVENT_LIST_MAX,
        page_token: str | None = None,
        single_events: bool = True,
        order_by: str | None = "startTime",
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List events in a calendar with the standard filters.

        Best first tool for calendar exploration. Returns compact
        summaries (``event_ref``, ``summary``, ``start_time``,
        ``end_time``, ``location``, ``organizer``, ``attendees``,
        ``status``, ``html_link``) by default. Raw Google event IDs are
        omitted unless ``include_ids=True``. Set
        ``include_metadata=False`` for the raw Google response with
        every field present. ``calendar_id`` accepts a raw ID, a
        calendar dict, or ``"primary"``.
        """
        if max_results < 1 or max_results > 2500:
            raise ValueError("max_results must be between 1 and 2500")
        resolved = _extract_calendar_id(calendar_id)
        params: dict[str, Any] = {
            "maxResults": max_results,
            "singleEvents": str(single_events).lower(),
        }
        if order_by is not None:
            params["orderBy"] = order_by
        if time_min is not None:
            params["timeMin"] = time_min
        if time_max is not None:
            params["timeMax"] = time_max
        if q is not None:
            params["q"] = q
        if page_token is not None:
            params["pageToken"] = page_token
        payload: dict[str, Any] = self._client.get(
            f"/calendars/{resolved}/events", params=params
        ).json()
        if not include_metadata:
            return payload
        return _summarize_event_list(payload, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_event(self, event_id: Any, calendar_id: Any = "primary") -> dict[str, Any]:
        """Return a single event.

        ``event_id`` accepts a raw ID or an event dict from
        :meth:`list_events` (with ``include_ids=True``). ``calendar_id``
        accepts a raw ID, calendar dict, or ``"primary"``.
        """
        resolved_event = _extract_event_id(event_id)
        resolved_calendar = _extract_calendar_id(calendar_id)
        return self._client.get(f"/calendars/{resolved_calendar}/events/{resolved_event}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_event(
        self,
        summary: str,
        *,
        start: dict[str, Any],
        end: dict[str, Any],
        calendar_id: Any = "primary",
        description: str | None = None,
        location: str | None = None,
        attendees: list[dict[str, Any]] | None = None,
        send_updates: str | None = None,
    ) -> dict[str, Any]:
        """Create a calendar event.

        ``start`` and ``end`` are Google event time dicts (e.g.
        ``{"dateTime": "2026-05-14T15:00:00-05:00"}`` or ``{"date":
        "2026-05-14"}``). ``calendar_id`` accepts a raw ID, calendar
        dict, or ``"primary"``. Returns the new event resource.
        """
        if not summary:
            raise ValueError("summary must be a non-empty string")
        resolved_calendar = _extract_calendar_id(calendar_id)
        payload: dict[str, Any] = {
            "summary": summary,
            "start": start,
            "end": end,
        }
        if description is not None:
            payload["description"] = description
        if location is not None:
            payload["location"] = location
        if attendees is not None:
            payload["attendees"] = attendees
        params: dict[str, Any] | None = None
        if send_updates is not None:
            params = {"sendUpdates": send_updates}
        return self._client.post(
            f"/calendars/{resolved_calendar}/events",
            params=params,
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_event(
        self,
        event_id: Any,
        patch: dict[str, Any],
        calendar_id: Any = "primary",
        *,
        send_updates: str | None = None,
    ) -> dict[str, Any]:
        """Patch an existing event with the supplied partial body.

        ``event_id`` accepts a raw ID or an event dict. ``calendar_id``
        accepts a raw ID, calendar dict, or ``"primary"``.
        """
        if not patch:
            raise ValueError("patch must be a non-empty dict")
        resolved_event = _extract_event_id(event_id)
        resolved_calendar = _extract_calendar_id(calendar_id)
        params: dict[str, Any] | None = None
        if send_updates is not None:
            params = {"sendUpdates": send_updates}
        return self._client.patch(
            f"/calendars/{resolved_calendar}/events/{resolved_event}",
            params=params,
            json=patch,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_event(
        self,
        event_id: Any,
        calendar_id: Any = "primary",
        *,
        send_updates: str | None = None,
    ) -> dict[str, Any]:
        """Delete an event. Recoverable via Google Workspace admin.

        ``event_id`` accepts a raw ID or an event dict. Destructive —
        confirm with the user first.
        """
        resolved_event = _extract_event_id(event_id)
        resolved_calendar = _extract_calendar_id(calendar_id)
        params: dict[str, Any] | None = None
        if send_updates is not None:
            params = {"sendUpdates": send_updates}
        response = self._client.delete(
            f"/calendars/{resolved_calendar}/events/{resolved_event}",
            params=params,
        )
        return {"deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_event_instances(
        self,
        event_id: Any,
        calendar_id: Any = "primary",
        *,
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = _DEFAULT_EVENT_LIST_MAX,
        page_token: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Return instances of a recurring event.

        ``event_id`` accepts a raw ID or an event dict. Returns compact
        summaries by default; ``include_ids=True`` /
        ``include_metadata=False`` works the same as :meth:`list_events`.
        """
        if max_results < 1 or max_results > 2500:
            raise ValueError("max_results must be between 1 and 2500")
        resolved_event = _extract_event_id(event_id)
        resolved_calendar = _extract_calendar_id(calendar_id)
        params: dict[str, Any] = {"maxResults": max_results}
        if time_min is not None:
            params["timeMin"] = time_min
        if time_max is not None:
            params["timeMax"] = time_max
        if page_token is not None:
            params["pageToken"] = page_token
        payload: dict[str, Any] = self._client.get(
            f"/calendars/{resolved_calendar}/events/{resolved_event}/instances",
            params=params,
        ).json()
        if not include_metadata:
            return payload
        return _summarize_event_list(payload, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def quick_add_event(
        self,
        text: str,
        calendar_id: Any = "primary",
        *,
        send_updates: str | None = None,
    ) -> dict[str, Any]:
        """Create an event from natural-language text via ``quickAdd``.

        E.g. ``"Lunch with Bob tomorrow noon"``. Useful for one-shot
        event creation when start/end fields would be awkward to derive.
        """
        if not text:
            raise ValueError("text must be a non-empty string")
        resolved_calendar = _extract_calendar_id(calendar_id)
        params: dict[str, Any] = {"text": text}
        if send_updates is not None:
            params["sendUpdates"] = send_updates
        return self._client.post(
            f"/calendars/{resolved_calendar}/events/quickAdd",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def move_event(
        self,
        event_id: Any,
        destination_calendar_id: Any,
        calendar_id: Any = "primary",
        *,
        send_updates: str | None = None,
    ) -> dict[str, Any]:
        """Move an event from ``calendar_id`` to ``destination_calendar_id``.

        Both calendar arguments accept raw IDs, calendar dicts, or
        ``"primary"``. ``event_id`` accepts a raw ID or an event dict.
        """
        resolved_event = _extract_event_id(event_id)
        resolved_calendar = _extract_calendar_id(calendar_id)
        resolved_destination = _extract_calendar_id(destination_calendar_id)
        params: dict[str, Any] = {"destination": resolved_destination}
        if send_updates is not None:
            params["sendUpdates"] = send_updates
        return self._client.post(
            f"/calendars/{resolved_calendar}/events/{resolved_event}/move",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def respond_to_event(
        self,
        event_id: Any,
        response_status: str,
        attendee_email: str,
        calendar_id: Any = "primary",
        *,
        send_updates: str | None = None,
    ) -> dict[str, Any]:
        """RSVP to an event by patching the attendee's response status.

        ``response_status`` must be one of ``accepted``, ``declined``,
        ``tentative``, or ``needsAction``. ``event_id`` accepts a raw ID
        or an event dict.
        """
        if response_status not in {"accepted", "declined", "tentative", "needsAction"}:
            raise ValueError(
                "response_status must be one of: accepted, declined, tentative, needsAction"
            )
        if not attendee_email:
            raise ValueError("attendee_email must be non-empty")
        resolved_event = _extract_event_id(event_id)
        resolved_calendar = _extract_calendar_id(calendar_id)
        existing: dict[str, Any] = self._client.get(
            f"/calendars/{resolved_calendar}/events/{resolved_event}"
        ).json()
        attendees: list[Any] = list(existing.get("attendees") or [])
        updated = False
        for attendee in attendees:
            if isinstance(attendee, dict):
                attendee_dict = cast("dict[str, Any]", attendee)
                email_value: Any = attendee_dict.get("email", "")
                if isinstance(email_value, str) and email_value.lower() == attendee_email.lower():
                    attendee_dict["responseStatus"] = response_status
                    updated = True
                    break
        if not updated:
            attendees.append({"email": attendee_email, "responseStatus": response_status})
        return self.update_event(
            resolved_event,
            {"attendees": attendees},
            calendar_id=resolved_calendar,
            send_updates=send_updates,
        )

    # MARK: - Calendar CRUD

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_calendar(
        self,
        summary: str,
        *,
        description: str | None = None,
        time_zone: str | None = None,
        location: str | None = None,
    ) -> dict[str, Any]:
        """Create a new secondary calendar in the user's calendar list.

        Returns the new calendar resource (with its server-assigned id).
        """
        if not summary:
            raise ValueError("summary must be a non-empty string")
        payload: dict[str, Any] = {"summary": summary}
        if description is not None:
            payload["description"] = description
        if time_zone is not None:
            payload["timeZone"] = time_zone
        if location is not None:
            payload["location"] = location
        return self._client.post("/calendars", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_calendar(
        self,
        calendar_id: Any,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch a calendar's metadata (summary/description/time zone).

        ``calendar_id`` accepts a raw ID or a calendar dict.
        """
        if not patch:
            raise ValueError("patch must contain at least one field")
        resolved = _extract_calendar_id(calendar_id)
        return self._client.patch(f"/calendars/{resolved}", json=patch).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_calendar(self, calendar_id: Any) -> dict[str, Any]:
        """Permanently delete a secondary calendar.

        Destructive — confirm with the user first. Refuses to delete the
        primary calendar.
        """
        resolved = _extract_calendar_id(calendar_id)
        if resolved == "primary":
            raise ValueError("Refusing to delete the primary calendar")
        self._client.delete(f"/calendars/{resolved}")
        return {"id": resolved, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def clear_calendar(self, calendar_id: Any = "primary") -> dict[str, Any]:
        """Clear all events from the primary calendar (irreversible).

        Destructive in effect — confirm with the user first.
        """
        resolved = _extract_calendar_id(calendar_id)
        self._client.post(f"/calendars/{resolved}/clear")
        return {"id": resolved, "cleared": True}

    # MARK: - ACL

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_acl(self, calendar_id: Any = "primary") -> dict[str, Any]:
        """List access-control rules for a calendar."""
        resolved = _extract_calendar_id(calendar_id)
        return self._client.get(f"/calendars/{resolved}/acl").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_acl_rule(
        self,
        calendar_id: Any,
        scope_type: str,
        role: str,
        *,
        scope_value: str | None = None,
        send_notifications: bool | None = None,
    ) -> dict[str, Any]:
        """Add an ACL rule (e.g. grant ``writer`` to a user/group/domain)."""
        if scope_type not in {"default", "user", "group", "domain"}:
            raise ValueError("scope_type must be one of: default, user, group, domain")
        if role not in {"none", "freeBusyReader", "reader", "writer", "owner"}:
            raise ValueError("role must be one of: none, freeBusyReader, reader, writer, owner")
        resolved = _extract_calendar_id(calendar_id)
        scope: dict[str, Any] = {"type": scope_type}
        if scope_value is not None:
            scope["value"] = scope_value
        payload: dict[str, Any] = {"role": role, "scope": scope}
        params: dict[str, Any] | None = None
        if send_notifications is not None:
            params = {"sendNotifications": str(send_notifications).lower()}
        return self._client.post(
            f"/calendars/{resolved}/acl",
            params=params,
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_acl_rule(self, calendar_id: Any, rule_id: str) -> dict[str, Any]:
        """Remove an ACL rule.

        Destructive — confirm with the user first.
        """
        if not rule_id:
            raise ValueError("rule_id must be a non-empty string")
        resolved = _extract_calendar_id(calendar_id)
        self._client.delete(f"/calendars/{resolved}/acl/{rule_id}")
        return {"id": rule_id, "deleted": True}

    # MARK: - Settings & colors

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_settings(self) -> dict[str, Any]:
        """Return user-level Calendar settings."""
        return self._client.get("/users/me/settings").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_colors(self) -> dict[str, Any]:
        """Return event/calendar color palette."""
        return self._client.get("/colors").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def free_busy(
        self,
        time_min: str,
        time_max: str,
        calendars: list[Any],
        *,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        """Return free/busy intervals across one or more calendars.

        Each entry in ``calendars`` may be a raw ID, calendar dict, or
        the literal ``"primary"``.
        """
        if not calendars:
            raise ValueError("calendars must contain at least one calendar id")
        resolved_calendars = [_extract_calendar_id(c) for c in calendars]
        payload: dict[str, Any] = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": calendar_id} for calendar_id in resolved_calendars],
        }
        if timezone is not None:
            payload["timeZone"] = timezone
        return self._client.post("/freeBusy", json=payload).json()


def _extract_event_id(candidate: Any) -> str:
    """Extract a Google event ID from a string or an event dict response."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("event_id must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        event_dict = cast("dict[str, Any]", candidate)
        for key in ("event_id", "id"):
            value: Any = event_dict.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("event dict must contain a non-empty 'event_id' or 'id'")
    if isinstance(candidate, list):
        entries = cast("list[Any]", candidate)
        for entry in entries:
            try:
                return _extract_event_id(entry)
            except ValueError:
                continue
        raise ValueError("no valid event id found in list")
    raise ValueError("event_id must be a string, dict, or list with an id")


def _extract_calendar_id(candidate: Any) -> str:
    """Extract a Google calendar ID from a string or a calendar dict."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("calendar_id must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        calendar_dict = cast("dict[str, Any]", candidate)
        for key in ("calendar_id", "id"):
            value: Any = calendar_dict.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("calendar dict must contain a non-empty 'calendar_id' or 'id'")
    raise ValueError("calendar_id must be a string or dict with an id")


def _event_summary(
    event: dict[str, Any],
    *,
    index: int,
    include_ids: bool,
) -> dict[str, Any]:
    start_obj: Any = event.get("start") or {}
    end_obj: Any = event.get("end") or {}
    start_time: Any = ""
    end_time: Any = ""
    if isinstance(start_obj, dict):
        start_dict = cast("dict[str, Any]", start_obj)
        start_time = start_dict.get("dateTime") or start_dict.get("date") or ""
    if isinstance(end_obj, dict):
        end_dict = cast("dict[str, Any]", end_obj)
        end_time = end_dict.get("dateTime") or end_dict.get("date") or ""
    organizer_obj: Any = event.get("organizer") or {}
    organizer: Any = ""
    if isinstance(organizer_obj, dict):
        organizer_dict = cast("dict[str, Any]", organizer_obj)
        display_name: Any = organizer_dict.get("displayName") or ""
        email: Any = organizer_dict.get("email") or ""
        if display_name and email:
            organizer = f"{display_name} <{email}>"
        else:
            organizer = email or display_name
    attendees_raw: Any = event.get("attendees") or []
    attendees: list[str] = []
    if isinstance(attendees_raw, list):
        attendee_entries = cast("list[Any]", attendees_raw)
        for entry in attendee_entries:
            if isinstance(entry, dict):
                entry_dict = cast("dict[str, Any]", entry)
                attendee_email: Any = entry_dict.get("email")
                if isinstance(attendee_email, str):
                    attendees.append(attendee_email)
    summary: dict[str, Any] = {
        "event_ref": f"event_{index}",
        "summary": event.get("summary", ""),
        "start_time": start_time,
        "end_time": end_time,
        "location": event.get("location", ""),
        "organizer": organizer,
        "attendees": attendees,
        "status": event.get("status", ""),
        "html_link": event.get("htmlLink", ""),
    }
    if include_ids:
        summary["event_id"] = event.get("id", "")
        ical_uid = event.get("iCalUID")
        if ical_uid:
            summary["i_cal_uid"] = ical_uid
        recurring_id = event.get("recurringEventId")
        if recurring_id:
            summary["recurring_event_id"] = recurring_id
    return summary


def _summarize_event_list(
    payload: dict[str, Any],
    *,
    include_ids: bool,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    items: Any = payload.get("items", [])
    if isinstance(items, list):
        event_items = cast("list[Any]", items)
        for index, event in enumerate(event_items, start=1):
            if not isinstance(event, dict):
                continue
            event_dict = cast("dict[str, Any]", event)
            events.append(_event_summary(event_dict, index=index, include_ids=include_ids))
    result: dict[str, Any] = {"events": events}
    if "nextPageToken" in payload:
        result["nextPageToken"] = payload["nextPageToken"]
    if "nextSyncToken" in payload:
        result["nextSyncToken"] = payload["nextSyncToken"]
    if "timeZone" in payload:
        result["timeZone"] = payload["timeZone"]
    return result
