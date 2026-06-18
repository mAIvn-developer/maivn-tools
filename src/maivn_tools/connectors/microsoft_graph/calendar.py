"""Outlook Calendar connector backed by Microsoft Graph v1.0."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpTransport
from ._shared import GRAPH_API_URL, TokenSource, make_graph_client
from .output_schemas import LIST_CALENDARS_OUTPUT, LIST_EVENTS_OUTPUT

# MARK: - Constants

_DEFAULT_EVENT_LIST_TOP = 25


@toolset(prefix="outlook_calendar")
class OutlookCalendarToolSet:
    """A connector for Outlook / Microsoft 365 calendars."""

    metadata = ProviderMetadata(
        name="outlook_calendar",
        display_name="Outlook Calendar",
        version="0.1.0",
        description="Read and write events across Outlook / Microsoft 365 calendars.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "Calendars.Read": "Read calendars and events.",
            "Calendars.ReadWrite": "Manage events.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://learn.microsoft.com/graph/api/resources/calendar",
        homepage_url="https://outlook.live.com",
        tags=("calendar", "microsoft"),
    )

    def __init__(
        self,
        token: TokenSource,
        *,
        user: str = "me",
        transport: HttpTransport | None = None,
        base_url: str = GRAPH_API_URL,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not user:
            raise ValueError("user must be a non-empty string")
        self.connection = connection
        self._user = user
        self._client = make_graph_client(token, transport=transport, base_url=base_url)

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_CALENDARS_OUTPUT)
    def list_calendars(
        self,
        *,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List calendars the user can see.

        Returns compact summaries: each calendar gets a stable
        ``calendar_ref`` (``calendar_1``, ``calendar_2``, ...), ``name``,
        ``color``, ``is_default``, and ``can_edit``. Raw Graph calendar
        IDs are omitted by default; set ``include_ids=True`` only when a
        follow-up tool such as :meth:`list_events` or :meth:`create_event`
        needs the raw ID.
        """
        payload: dict[str, Any] = self._client.get(self._user_path("/calendars")).json()
        calendars: list[dict[str, Any]] = []
        raw: object = payload.get("value", [])
        if isinstance(raw, list):
            raw_calendars = cast(list[Any], raw)
            for index, calendar in enumerate(raw_calendars, start=1):
                if not isinstance(calendar, dict):
                    continue
                calendar_dict = cast(dict[str, Any], calendar)
                summary: dict[str, Any] = {
                    "calendar_ref": f"calendar_{index}",
                    "name": calendar_dict.get("name", ""),
                    "color": calendar_dict.get("color", ""),
                    "is_default": calendar_dict.get("isDefaultCalendar", False),
                    "can_edit": calendar_dict.get("canEdit", False),
                }
                if include_ids:
                    summary["calendar_id"] = calendar_dict.get("id", "")
                calendars.append(summary)
        return {
            "calendars": calendars,
            "nextLink": payload.get("@odata.nextLink"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_EVENTS_OUTPUT)
    def list_events(
        self,
        *,
        calendar_id: Any | None = None,
        start: str | None = None,
        end: str | None = None,
        top: int = _DEFAULT_EVENT_LIST_TOP,
        filter: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List events, optionally as a calendar-view between two times.

        Best first tool for calendar triage. Supplying ``start`` and
        ``end`` switches to ``calendarView`` (which expands recurring
        series into individual occurrences). Returns compact summaries
        (``event_ref``, ``subject``, ``start_time``, ``end_time``,
        ``location``, ``organizer``, ``attendees``, ``is_online_meeting``)
        by default. Raw Graph event IDs are omitted unless
        ``include_ids=True``. Set ``include_metadata=False`` for the raw
        Graph response. ``calendar_id`` accepts a raw ID or a calendar
        dict from :meth:`list_calendars`.
        """
        if top < 1 or top > 1000:
            raise ValueError("top must be between 1 and 1000")
        path_calendar = _extract_calendar_id(calendar_id) if calendar_id is not None else None
        path = "/calendarView" if start and end else "/events"
        if path_calendar is not None:
            path = (
                f"/calendars/{path_calendar}/calendarView"
                if start and end
                else f"/calendars/{path_calendar}/events"
            )
        params: dict[str, Any] = {"$top": top}
        if start is not None:
            params["startDateTime"] = start
        if end is not None:
            params["endDateTime"] = end
        if filter is not None:
            params["$filter"] = filter
        payload: dict[str, Any] = self._client.get(self._user_path(path), params=params).json()
        if not include_metadata:
            return payload
        return _summarize_event_list(payload, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_event(self, event_id: Any) -> dict[str, Any]:
        """Return one event by ID.

        ``event_id`` accepts a raw Graph ID string or an event dict from
        :meth:`list_events` (with ``include_ids=True``).
        """
        resolved = _extract_event_id(event_id)
        return self._client.get(self._user_path(f"/events/{resolved}")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_event(
        self,
        subject: str,
        *,
        start: dict[str, Any],
        end: dict[str, Any],
        body: dict[str, Any] | None = None,
        attendees: list[dict[str, Any]] | None = None,
        location: dict[str, Any] | None = None,
        calendar_id: Any | None = None,
    ) -> dict[str, Any]:
        """Create a calendar event.

        ``start`` and ``end`` must each be Graph dateTimeTimeZone dicts
        ``{"dateTime": "2026-05-14T15:00:00", "timeZone": "UTC"}``.
        ``calendar_id`` accepts a raw ID or a calendar dict from
        :meth:`list_calendars`. Returns the new event resource.
        """
        if not subject:
            raise ValueError("subject must be a non-empty string")
        payload: dict[str, Any] = {
            "subject": subject,
            "start": start,
            "end": end,
        }
        if body is not None:
            payload["body"] = body
        if attendees is not None:
            payload["attendees"] = attendees
        if location is not None:
            payload["location"] = location
        if calendar_id is not None:
            resolved_calendar = _extract_calendar_id(calendar_id)
            path = f"/calendars/{resolved_calendar}/events"
        else:
            path = "/events"
        return self._client.post(self._user_path(path), json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_event(self, event_id: Any, patch: dict[str, Any]) -> dict[str, Any]:
        """Patch an existing event.

        ``event_id`` accepts a raw ID string or an event dict from
        :meth:`list_events`. Returns the updated event resource.
        """
        if not patch:
            raise ValueError("patch must be a non-empty dict")
        resolved = _extract_event_id(event_id)
        return self._client.patch(self._user_path(f"/events/{resolved}"), json=patch).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_event(self, event_id: Any) -> dict[str, Any]:
        """Delete an event.

        Returns ``{"deleted": True, "status": <http status>}``.
        Destructive — confirm with the user first. ``event_id`` accepts a
        raw ID string or an event dict.
        """
        resolved = _extract_event_id(event_id)
        response = self._client.delete(self._user_path(f"/events/{resolved}"))
        return {"deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_calendar(self, calendar_id: Any = "primary") -> dict[str, Any]:
        """Return a calendar by ID (use ``primary`` for default).

        ``calendar_id`` accepts a raw ID, a calendar dict, or the literal
        string ``"primary"``.
        """
        if isinstance(calendar_id, str) and calendar_id == "primary":
            return self._client.get(self._user_path("/calendar")).json()
        resolved = _extract_calendar_id(calendar_id)
        return self._client.get(self._user_path(f"/calendars/{resolved}")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_EVENTS_OUTPUT)
    def list_event_instances(
        self,
        event_id: Any,
        start: str,
        end: str,
        *,
        top: int = _DEFAULT_EVENT_LIST_TOP,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List instances of a recurring event between ``start`` and ``end``.

        Returns compact event summaries by default; ``include_ids=True``
        or ``include_metadata=False`` works the same as
        :meth:`list_events`. ``event_id`` accepts a raw ID or an event
        dict.
        """
        if top < 1 or top > 1000:
            raise ValueError("top must be between 1 and 1000")
        resolved = _extract_event_id(event_id)
        payload: dict[str, Any] = self._client.get(
            self._user_path(f"/events/{resolved}/instances"),
            params={"startDateTime": start, "endDateTime": end, "$top": top},
        ).json()
        if not include_metadata:
            return payload
        return _summarize_event_list(payload, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def respond_to_event(
        self,
        event_id: Any,
        response: str,
        *,
        comment: str | None = None,
        send_response: bool = True,
    ) -> dict[str, Any]:
        """RSVP to an event (``accept`` / ``decline`` / ``tentativelyAccept``).

        ``event_id`` accepts a raw ID or an event dict. Returns
        ``{"responded": True, "response": ..., "status": ...}``.
        """
        if response not in {"accept", "decline", "tentativelyAccept"}:
            raise ValueError("response must be one of: accept, decline, tentativelyAccept")
        resolved = _extract_event_id(event_id)
        payload: dict[str, Any] = {"sendResponse": send_response}
        if comment is not None:
            payload["comment"] = comment
        resp = self._client.post(
            self._user_path(f"/events/{resolved}/{response}"),
            json=payload,
        )
        return {"responded": True, "response": response, "status": resp.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def cancel_event(self, event_id: Any, *, comment: str | None = None) -> dict[str, Any]:
        """Cancel an organized event (sends cancellation notices).

        ``event_id`` accepts a raw ID or an event dict. Destructive in
        effect — confirm with the user first.
        """
        resolved = _extract_event_id(event_id)
        payload: dict[str, Any] = {}
        if comment is not None:
            payload["comment"] = comment
        resp = self._client.post(
            self._user_path(f"/events/{resolved}/cancel"),
            json=payload or None,
        )
        return {"cancelled": True, "status": resp.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def forward_event(
        self,
        event_id: Any,
        to_recipients: list[str],
        *,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """Forward a calendar event to additional recipients.

        ``event_id`` accepts a raw ID or an event dict.
        """
        if not to_recipients:
            raise ValueError("to_recipients must be non-empty")
        resolved = _extract_event_id(event_id)
        payload: dict[str, Any] = {
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to_recipients],
        }
        if comment is not None:
            payload["comment"] = comment
        resp = self._client.post(
            self._user_path(f"/events/{resolved}/forward"),
            json=payload,
        )
        return {"forwarded": True, "status": resp.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def find_meeting_times(
        self,
        *,
        attendees: list[str],
        meeting_duration_minutes: int = 30,
        time_constraint: dict[str, Any] | None = None,
        location_constraint: dict[str, Any] | None = None,
        max_candidates: int = 10,
    ) -> dict[str, Any]:
        """Call ``findMeetingTimes`` to suggest free slots across attendees.

        Returns the raw ``meetingTimeSuggestions`` payload. Useful before
        :meth:`create_event` when picking a time that works for everyone.
        """
        if not attendees:
            raise ValueError("attendees must contain at least one address")
        if meeting_duration_minutes < 5 or meeting_duration_minutes > 1440:
            raise ValueError("meeting_duration_minutes must be between 5 and 1440")
        payload: dict[str, Any] = {
            "attendees": [
                {"emailAddress": {"address": addr}, "type": "required"} for addr in attendees
            ],
            "meetingDuration": f"PT{int(meeting_duration_minutes)}M",
            "maxCandidates": max_candidates,
        }
        if time_constraint is not None:
            payload["timeConstraint"] = time_constraint
        if location_constraint is not None:
            payload["locationConstraint"] = location_constraint
        return self._client.post(
            self._user_path("/findMeetingTimes"),
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_calendar(
        self,
        name: str,
        *,
        color: str | None = None,
    ) -> dict[str, Any]:
        """Create a new calendar in the user's mailbox.

        Returns the new calendar resource (with its server-assigned id).
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        payload: dict[str, Any] = {"name": name}
        if color is not None:
            payload["color"] = color
        return self._client.post(self._user_path("/calendars"), json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_calendar(self, calendar_id: Any, patch: dict[str, Any]) -> dict[str, Any]:
        """Patch a calendar's metadata.

        ``calendar_id`` accepts a raw ID or a calendar dict.
        """
        if not patch:
            raise ValueError("patch must contain at least one field")
        resolved = _extract_calendar_id(calendar_id)
        return self._client.patch(
            self._user_path(f"/calendars/{resolved}"),
            json=patch,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_calendar(self, calendar_id: Any) -> dict[str, Any]:
        """Delete a calendar (does not delete the default calendar).

        ``calendar_id`` accepts a raw ID or a calendar dict. Destructive
        — confirm with the user first.
        """
        resolved = _extract_calendar_id(calendar_id)
        self._client.delete(self._user_path(f"/calendars/{resolved}"))
        return {"id": resolved, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_calendar_groups(self) -> dict[str, Any]:
        """List calendar groups for the user."""
        return self._client.get(self._user_path("/calendarGroups")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def free_busy(
        self,
        start: str,
        end: str,
        schedules: list[str],
        *,
        interval: int = 30,
    ) -> dict[str, Any]:
        """Call ``getSchedule`` to retrieve free/busy intervals.

        ``schedules`` is a list of UPNs / SMTP addresses. ``interval`` is
        the granularity in minutes.
        """
        if not schedules:
            raise ValueError("schedules must contain at least one principal")
        if interval < 5 or interval > 1440:
            raise ValueError("interval must be between 5 and 1440 minutes")
        payload: dict[str, Any] = {
            "schedules": schedules,
            "startTime": {"dateTime": start, "timeZone": "UTC"},
            "endTime": {"dateTime": end, "timeZone": "UTC"},
            "availabilityViewInterval": interval,
        }
        return self._client.post(self._user_path("/calendar/getSchedule"), json=payload).json()

    # MARK: - Internal

    def _user_path(self, suffix: str) -> str:
        prefix = "/me" if self._user == "me" else f"/users/{self._user}"
        return f"{prefix}{suffix}"


def _extract_event_id(candidate: Any) -> str:
    """Extract a Graph event ID from a string or an event dict response."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("event_id must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        candidate_dict = cast(dict[str, Any], candidate)
        for key in ("event_id", "id"):
            value: object = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("event dict must contain a non-empty 'event_id' or 'id'")
    if isinstance(candidate, list):
        candidate_list = cast(list[Any], candidate)
        for entry in candidate_list:
            try:
                return _extract_event_id(entry)
            except ValueError:
                continue
        raise ValueError("no valid event id found in list")
    raise ValueError("event_id must be a string, dict, or list with an id")


def _extract_calendar_id(candidate: Any) -> str:
    """Extract a Graph calendar ID from a string or a calendar dict."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("calendar_id must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        candidate_dict = cast(dict[str, Any], candidate)
        for key in ("calendar_id", "id"):
            value: object = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("calendar dict must contain a non-empty 'calendar_id' or 'id'")
    raise ValueError("calendar_id must be a string or dict with an id")


def _coerce_str(value: object) -> str:
    """Return ``value`` as a string when it is a non-empty str, else ``""``."""
    return value if isinstance(value, str) else ""


def _event_summary(
    event: dict[str, Any],
    *,
    index: int,
    include_ids: bool,
) -> dict[str, Any]:
    start_obj: object = event.get("start") or {}
    end_obj: object = event.get("end") or {}
    start_time: str = ""
    end_time: str = ""
    if isinstance(start_obj, dict):
        start_dict = cast(dict[str, Any], start_obj)
        start_time = _coerce_str(start_dict.get("dateTime"))
    if isinstance(end_obj, dict):
        end_dict = cast(dict[str, Any], end_obj)
        end_time = _coerce_str(end_dict.get("dateTime"))
    location_obj: object = event.get("location") or {}
    location: str = ""
    if isinstance(location_obj, dict):
        location_dict = cast(dict[str, Any], location_obj)
        location = _coerce_str(location_dict.get("displayName"))
    organizer_obj: object = event.get("organizer") or {}
    organizer: str = ""
    if isinstance(organizer_obj, dict):
        organizer_dict = cast(dict[str, Any], organizer_obj)
        email: object = organizer_dict.get("emailAddress") or {}
        if isinstance(email, dict):
            email_dict = cast(dict[str, Any], email)
            name = _coerce_str(email_dict.get("name"))
            address = _coerce_str(email_dict.get("address"))
            if name and address:
                organizer = f"{name} <{address}>"
            else:
                organizer = address or name
    attendees_raw: object = event.get("attendees") or []
    attendees: list[str] = []
    if isinstance(attendees_raw, list):
        attendees_list = cast(list[Any], attendees_raw)
        for entry in attendees_list:
            if isinstance(entry, dict):
                entry_dict = cast(dict[str, Any], entry)
                email_obj: object = entry_dict.get("emailAddress") or {}
                if isinstance(email_obj, dict):
                    email_obj_dict = cast(dict[str, Any], email_obj)
                    addr: object = email_obj_dict.get("address")
                    if isinstance(addr, str):
                        attendees.append(addr)
    summary: dict[str, Any] = {
        "event_ref": f"event_{index}",
        "subject": event.get("subject", ""),
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "organizer": organizer,
        "attendees": attendees,
        "is_online_meeting": event.get("isOnlineMeeting", False),
        "is_all_day": event.get("isAllDay", False),
    }
    if include_ids:
        summary["event_id"] = event.get("id", "")
        ical_uid = event.get("iCalUId")
        if ical_uid:
            summary["i_cal_uid"] = ical_uid
    return summary


def _summarize_event_list(
    payload: dict[str, Any],
    *,
    include_ids: bool,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    raw: object = payload.get("value", [])
    if isinstance(raw, list):
        raw_events = cast(list[Any], raw)
        for index, event in enumerate(raw_events, start=1):
            if not isinstance(event, dict):
                continue
            event_dict = cast(dict[str, Any], event)
            events.append(_event_summary(event_dict, index=index, include_ids=include_ids))
    result: dict[str, Any] = {"events": events}
    next_link: object = payload.get("@odata.nextLink")
    if next_link is not None:
        result["nextLink"] = next_link
    return result
