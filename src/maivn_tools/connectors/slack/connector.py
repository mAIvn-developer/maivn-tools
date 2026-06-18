"""Slack Web API connector.

The connector authenticates with a Slack bot token (``xoxb-``) or user token
(``xoxp-``) and exposes the lookup, search, and posting endpoints used most
often by agents. Every Slack response is checked for ``ok=false`` and turned
into a :class:`SlackApiError` so callers can write portable error handling.

See https://api.slack.com/web for the underlying API and required token
scopes. Scope enforcement happens server-side; the connector advertises the
common scopes via :attr:`metadata.scopes` for documentation purposes.
"""

# pyright: strict

from __future__ import annotations

from typing import Annotated, Any, TypeAlias, cast

from maivn import tool_output, toolify, toolset
from pydantic import JsonValue, WithJsonSchema

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.errors import ProviderError
from ...runtime.http import HttpClient, HttpTransport

# MARK: - Constants

SLACK_API_URL = "https://slack.com/api"
_DEFAULT_LIST_LIMIT = 25
_DEFAULT_HISTORY_LIMIT = 20
_DEFAULT_SEARCH_COUNT = 20

_SLACK_CHANNEL_STRING_SCHEMA: dict[str, object] = {
    "type": "string",
    "minLength": 1,
    "description": "Friendly channel name such as 'incidents' or raw Slack channel ID.",
}
_SLACK_CHANNEL_OBJECT_SCHEMA: dict[str, object] = {
    "type": "object",
    "description": "Channel-summary object returned by list_channels.",
    "properties": {
        "channel_id": {"type": "string", "minLength": 1},
        "id": {"type": "string", "minLength": 1},
        "channel": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
    },
    "anyOf": [
        {"type": "object", "required": ["channel_id"]},
        {"type": "object", "required": ["id"]},
        {"type": "object", "required": ["channel"]},
        {"type": "object", "required": ["name"]},
    ],
    "additionalProperties": True,
}
_SLACK_CHANNEL_INPUT_SCHEMA: dict[str, object] = {
    "description": (
        "A Slack channel reference: friendly channel name, raw channel ID, "
        "channel-summary dict from list_channels, or single-item list containing one."
    ),
    "anyOf": [
        _SLACK_CHANNEL_STRING_SCHEMA,
        _SLACK_CHANNEL_OBJECT_SCHEMA,
        {
            "type": "array",
            "minItems": 1,
            "maxItems": 1,
            "items": {
                "anyOf": [
                    _SLACK_CHANNEL_STRING_SCHEMA,
                    _SLACK_CHANNEL_OBJECT_SCHEMA,
                ]
            },
        },
    ],
}
_SLACK_MESSAGE_TS_STRING_SCHEMA: dict[str, object] = {
    "type": "string",
    "minLength": 1,
    "description": "Raw Slack message timestamp string.",
}
_SLACK_MESSAGE_TS_OBJECT_SCHEMA: dict[str, object] = {
    "type": "object",
    "description": "Message-summary object returned by channel_history or post_message.",
    "properties": {
        "ts": {"type": "string", "minLength": 1},
        "timestamp": {"type": "string", "minLength": 1},
        "message_ts": {"type": "string", "minLength": 1},
    },
    "anyOf": [
        {"type": "object", "required": ["ts"]},
        {"type": "object", "required": ["timestamp"]},
        {"type": "object", "required": ["message_ts"]},
    ],
    "additionalProperties": True,
}
_SLACK_MESSAGE_TS_INPUT_SCHEMA: dict[str, object] = {
    "description": "A Slack message timestamp string or message-summary dict containing ts.",
    "anyOf": [
        _SLACK_MESSAGE_TS_STRING_SCHEMA,
        _SLACK_MESSAGE_TS_OBJECT_SCHEMA,
    ],
}
_SLACK_CHANNEL_SUMMARY_OUTPUT_SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "channel_ref": {"type": "string"},
        "name": {"type": "string"},
        "topic": {"type": "string"},
        "num_members": {"type": "integer"},
        "is_member": {"type": "boolean"},
        "is_private": {"type": "boolean"},
    },
    "required": ["channel_ref", "name"],
}
_SLACK_MESSAGE_SUMMARY_OUTPUT_SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "message_ref": {"type": "string"},
        "channel_name": {"type": "string"},
        "username": {"type": "string"},
        "text": {"type": "string"},
        "ts": {"type": "string"},
        "permalink": {"type": "string"},
    },
    "required": ["message_ref", "text"],
}
_SLACK_LIST_CHANNELS_OUTPUT_SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "channels": {"type": "array", "items": _SLACK_CHANNEL_SUMMARY_OUTPUT_SCHEMA},
        "next_cursor": {"type": "string"},
    },
    "required": ["channels"],
}
_SLACK_CHANNEL_HISTORY_OUTPUT_SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "channel": {"type": "string"},
        "messages": {"type": "array", "items": _SLACK_MESSAGE_SUMMARY_OUTPUT_SCHEMA},
        "has_more": {"type": "boolean"},
        "next_cursor": {"type": "string"},
    },
    "required": ["messages"],
}
_SLACK_SEARCH_MESSAGES_OUTPUT_SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "messages": {"type": "array", "items": _SLACK_MESSAGE_SUMMARY_OUTPUT_SCHEMA},
        "total": {"type": "integer"},
        "page": {"type": "integer"},
    },
    "required": ["messages"],
}

SlackChannelInput: TypeAlias = Annotated[
    str | dict[str, Any] | list[Any],
    WithJsonSchema(_SLACK_CHANNEL_INPUT_SCHEMA),
]
SlackMessageTsInput: TypeAlias = Annotated[
    str | dict[str, Any],
    WithJsonSchema(_SLACK_MESSAGE_TS_INPUT_SCHEMA),
]


# MARK: - Helpers


def _as_dict(value: object) -> dict[str, Any] | None:
    """Return ``value`` as a ``dict[str, Any]`` if it is a mapping, else ``None``."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else None


def _as_list(value: object) -> list[Any]:
    """Return ``value`` as a ``list[Any]`` if it is a list, else an empty list."""
    return cast("list[Any]", value) if isinstance(value, list) else []


# MARK: - Errors


class SlackApiError(ProviderError):
    """Raised when Slack returns ``ok=false`` in the response body."""


@toolset(prefix="slack")
class SlackToolSet:
    """A connector for the Slack Web API.

    Args:
        token: Slack bot or user token. Never logged or surfaced through
            :meth:`describe`.
        base_url: Override for tests or for Slack Enterprise Grid mirrors.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="slack",
        display_name="Slack",
        version="0.1.0",
        description="Search channels, post messages, and look up users in Slack workspaces.",
        auth_modes=(AuthMode.BEARER,),
        scopes={
            "channels:read": "List public channels.",
            "channels:history": "Read messages in public channels.",
            "chat:write": "Post messages as the bot or user.",
            "search:read": "Search messages.",
            "users:read": "Look up users by ID or email.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://api.slack.com/web",
        homepage_url="https://slack.com",
        tags=("messaging", "collaboration"),
    )

    def __init__(
        self,
        token: str,
        *,
        base_url: str = SLACK_API_URL,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not token:
            raise ValueError("token must be a non-empty string")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url,
            auth=BearerTokenAuth(token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )
        # Local name->id channel cache populated by ``list_channels``. Used to
        # let write tools accept a friendly channel name in place of ``C123``.
        self._channel_name_cache: dict[str, str] = {}

    @property
    def client(self) -> HttpClient:
        """Return the underlying :class:`HttpClient`."""
        return self._client

    # MARK: - Auth and users

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def auth_test(self) -> dict[str, Any]:
        """Verify the configured token and return identity info.

        Best first call at startup to confirm the token works and to discover
        the bot's user ID and team. Returns the Slack ``auth.test`` payload
        (``user``, ``user_id``, ``team``, ``team_id``, ``url``).
        """
        return self._call("POST", "/auth.test")

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def user_lookup(
        self,
        *,
        user_id: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        """Look up a Slack user by ID or email.

        Pass exactly one of ``user_id`` (``U...``) or ``email``. Returns the
        Slack ``user`` resource. Useful before calling DM/invite tools that
        need a Slack user ID.
        """
        if (user_id is None) == (email is None):
            raise ValueError("Specify exactly one of 'user_id' or 'email'")
        if user_id is not None:
            return self._call("GET", "/users.info", params={"user": user_id})
        return self._call("GET", "/users.lookupByEmail", params={"email": email})

    # MARK: - Channels and messages

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(_SLACK_LIST_CHANNELS_OUTPUT_SCHEMA)
    def list_channels(
        self,
        *,
        types: str = "public_channel",
        exclude_archived: bool = True,
        limit: int = _DEFAULT_LIST_LIMIT,
        cursor: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List conversations the token can see.

        Best first tool to discover which channels you can post to. By default
        returns compact summaries: ``channel_ref`` (stable ``channel_1``,
        ``channel_2`` index), ``name``, ``is_private``, ``is_member``, and
        ``topic``. Raw Slack IDs (``C0123``) are internal handles and are
        omitted by default. Set ``include_ids=True`` only when a follow-up tool
        needs the raw ``channel_id``. Set ``include_metadata=False`` to get the
        raw Slack response with every field.
        """
        params: dict[str, Any] = {
            "types": types,
            "exclude_archived": str(exclude_archived).lower(),
            "limit": limit,
        }
        if cursor is not None:
            params["cursor"] = cursor
        payload = self._call("GET", "/conversations.list", params=params)
        if not include_metadata:
            return payload

        channels: list[dict[str, Any]] = []
        raw_channels = _as_list(payload.get("channels", []) or [])
        for index, channel in enumerate(raw_channels, start=1):
            channel_obj = _as_dict(channel)
            if channel_obj is None:
                continue
            name = channel_obj.get("name") or channel_obj.get("name_normalized") or ""
            channel_id = channel_obj.get("id", "")
            if isinstance(name, str) and name and isinstance(channel_id, str) and channel_id:
                self._channel_name_cache[name] = channel_id
            topic = _as_dict(channel_obj.get("topic"))
            topic_value = topic.get("value", "") if topic is not None else ""
            summary: dict[str, Any] = {
                "channel_ref": f"channel_{index}",
                "name": name,
                "is_private": bool(channel_obj.get("is_private")),
                "is_member": bool(channel_obj.get("is_member")),
                "topic": topic_value,
                "num_members": channel_obj.get("num_members"),
            }
            if include_ids:
                summary["channel_id"] = channel_id
            channels.append(summary)
        metadata = _as_dict(payload.get("response_metadata"))
        next_cursor = metadata.get("next_cursor") if metadata is not None else None
        result: dict[str, Any] = {
            "channels": channels,
            "next_cursor": next_cursor,
        }
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(_SLACK_CHANNEL_HISTORY_OUTPUT_SCHEMA)
    def channel_history(
        self,
        channel: SlackChannelInput,
        *,
        limit: int = _DEFAULT_HISTORY_LIMIT,
        cursor: str | None = None,
        oldest: str | None = None,
        latest: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Return recent messages from a conversation.

        Accepts a friendly channel name (e.g. ``"general"``, resolved against
        the cache populated by :meth:`list_channels`), a raw channel ID
        (``C0123``), or a channel-summary dict from :meth:`list_channels`. By
        default returns compact summaries: ``message_ref`` (stable
        ``message_1``, ``message_2``), ``user_id``, ``text``, ``ts``,
        ``thread_ts``, ``reply_count``. The ``ts`` value doubles as the
        message timestamp string Slack uses to reference messages in followups
        (update_message, delete_message, add_reaction). Set
        ``include_metadata=False`` to get the raw Slack response.
        """
        resolved = self._resolve_channel(channel)
        params: dict[str, Any] = {"channel": resolved, "limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        if oldest is not None:
            params["oldest"] = oldest
        if latest is not None:
            params["latest"] = latest
        payload = self._call("GET", "/conversations.history", params=params)
        if not include_metadata:
            return payload

        summaries: list[dict[str, Any]] = []
        raw_messages = _as_list(payload.get("messages", []) or [])
        for index, message in enumerate(raw_messages, start=1):
            message_obj = _as_dict(message)
            if message_obj is None:
                continue
            summary: dict[str, Any] = {
                "message_ref": f"message_{index}",
                "user_id": message_obj.get("user", ""),
                "text": message_obj.get("text", ""),
                "ts": message_obj.get("ts", ""),
                "thread_ts": message_obj.get("thread_ts"),
                "reply_count": message_obj.get("reply_count", 0),
            }
            if include_ids:
                summary["channel_id"] = resolved
            summaries.append(summary)
        metadata = _as_dict(payload.get("response_metadata"))
        next_cursor = metadata.get("next_cursor") if metadata is not None else None
        return {
            "channel": resolved if include_ids else None,
            "messages": summaries,
            "has_more": payload.get("has_more", False),
            "next_cursor": next_cursor,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def post_message(
        self,
        channel: SlackChannelInput,
        text: str | None = None,
        *,
        blocks: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        """Post a message to a channel or thread.

        Accepts a friendly channel name (auto-resolved against the
        :meth:`list_channels` cache), a raw channel ID (``C0123``), or a
        channel-summary dict from :meth:`list_channels`. Returns the Slack
        ``chat.postMessage`` payload (``ok``, ``channel``, ``ts``, ``message``).
        The ``ts`` is the message handle to feed back into
        :meth:`update_message`, :meth:`delete_message`, or
        :meth:`add_reaction`.
        """
        resolved = self._resolve_channel(channel)
        if not text and not blocks:
            raise ValueError("text or blocks must be supplied")
        payload: dict[str, Any] = {"channel": resolved}
        if text is not None:
            payload["text"] = text
        if blocks is not None:
            payload["blocks"] = blocks
        if thread_ts is not None:
            payload["thread_ts"] = thread_ts
        return self._call("POST", "/chat.postMessage", json=payload)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(_SLACK_SEARCH_MESSAGES_OUTPUT_SCHEMA)
    def search_messages(
        self,
        query: str,
        *,
        sort: str = "timestamp",
        sort_dir: str = "desc",
        count: int = _DEFAULT_SEARCH_COUNT,
        page: int = 1,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search messages with Slack's standard search grammar.

        Best first tool for fuzzy lookups (``"from:alice db migration"``).
        By default returns compact summaries: ``message_ref``, ``username``,
        ``channel_name``, ``text``, ``ts``, ``permalink``. Slack channel and
        user IDs are omitted by default; pass ``include_ids=True`` if a
        follow-up tool needs them. ``include_metadata=False`` returns the raw
        Slack ``search.messages`` payload.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        payload = self._call(
            "GET",
            "/search.messages",
            params={
                "query": query,
                "sort": sort,
                "sort_dir": sort_dir,
                "count": count,
                "page": page,
            },
        )
        if not include_metadata:
            return payload

        messages_obj = _as_dict(payload.get("messages")) or {}
        matches = _as_list(messages_obj.get("matches", []))
        summaries: list[dict[str, Any]] = []
        for index, match in enumerate(matches, start=1):
            match_obj = _as_dict(match)
            if match_obj is None:
                continue
            channel_dict = _as_dict(match_obj.get("channel"))
            summary: dict[str, Any] = {
                "message_ref": f"message_{index}",
                "username": match_obj.get("username", ""),
                "channel_name": channel_dict.get("name", "") if channel_dict is not None else "",
                "text": match_obj.get("text", ""),
                "ts": match_obj.get("ts", ""),
                "permalink": match_obj.get("permalink"),
            }
            if include_ids:
                summary["user_id"] = match_obj.get("user", "")
                channel_id = channel_dict.get("id", "") if channel_dict is not None else ""
                summary["channel_id"] = channel_id
            summaries.append(summary)
        pagination = messages_obj.get("pagination")
        return {
            "messages": summaries,
            "total": messages_obj.get("total", len(summaries)),
            "page": page,
            "pagination": pagination,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_files(
        self,
        query: str,
        *,
        count: int = 20,
        page: int = 1,
    ) -> dict[str, Any]:
        """Search Slack files visible to the token.

        Returns the raw Slack ``search.files`` payload. Useful for locating an
        uploaded file before passing it to :meth:`file_info` or
        :meth:`delete_file`.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        return self._call(
            "GET",
            "/search.files",
            params={"query": query, "count": count, "page": page},
        )

    # MARK: - Users

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_users(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
        include_locale: bool = False,
    ) -> dict[str, Any]:
        """List users in the workspace.

        Returns the raw Slack ``users.list`` payload. Use this to discover
        user IDs for tools that take a Slack ``U...`` ID directly.
        """
        params: dict[str, Any] = {
            "limit": limit,
            "include_locale": str(include_locale).lower(),
        }
        if cursor is not None:
            params["cursor"] = cursor
        return self._call("GET", "/users.list", params=params)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user_profile(
        self,
        user_id: str,
        *,
        include_labels: bool = False,
    ) -> dict[str, Any]:
        """Return a user's profile (custom fields, status, image).

        Returns the Slack ``users.profile.get`` payload.
        """
        if not user_id:
            raise ValueError("user_id must be a non-empty string")
        return self._call(
            "GET",
            "/users.profile.get",
            params={"user": user_id, "include_labels": str(include_labels).lower()},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def set_user_status(
        self,
        status_text: str,
        status_emoji: str = "",
        *,
        status_expiration: int = 0,
    ) -> dict[str, Any]:
        """Update the authenticated user's status text/emoji.

        ``status_expiration`` is a Unix epoch second (0 = no expiry).
        """
        profile = {
            "status_text": status_text,
            "status_emoji": status_emoji,
            "status_expiration": status_expiration,
        }
        return self._call("POST", "/users.profile.set", json={"profile": profile})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user_presence(self, user_id: str) -> dict[str, Any]:
        """Return a user's presence status (``active`` / ``away``)."""
        if not user_id:
            raise ValueError("user_id must be a non-empty string")
        return self._call("GET", "/users.getPresence", params={"user": user_id})

    # MARK: - Channels / conversations

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def channel_info(
        self,
        channel: SlackChannelInput,
        *,
        include_locale: bool = False,
        include_num_members: bool = False,
    ) -> dict[str, Any]:
        """Return metadata for a single conversation.

        Accepts a channel name, raw ID, or channel-summary dict. Returns the
        Slack ``conversations.info`` payload.
        """
        resolved = self._resolve_channel(channel)
        return self._call(
            "GET",
            "/conversations.info",
            params={
                "channel": resolved,
                "include_locale": str(include_locale).lower(),
                "include_num_members": str(include_num_members).lower(),
            },
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def channel_members(
        self,
        channel: SlackChannelInput,
        *,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List members of a channel.

        Accepts a channel name, raw ID, or channel-summary dict. Returns the
        Slack ``conversations.members`` payload (``members``: list of user
        IDs).
        """
        resolved = self._resolve_channel(channel)
        params: dict[str, Any] = {"channel": resolved, "limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        return self._call("GET", "/conversations.members", params=params)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def thread_replies(
        self,
        channel: SlackChannelInput,
        thread_ts: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Return replies in a thread.

        ``thread_ts`` is the parent message's ``ts`` (the timestamp string
        Slack returns from :meth:`channel_history` or :meth:`post_message`).
        """
        resolved = self._resolve_channel(channel)
        if not thread_ts:
            raise ValueError("thread_ts must be non-empty")
        params: dict[str, Any] = {"channel": resolved, "ts": thread_ts, "limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        return self._call("GET", "/conversations.replies", params=params)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_channel(
        self,
        name: str,
        *,
        is_private: bool = False,
    ) -> dict[str, Any]:
        """Create a channel (public by default).

        Returns the new ``channel`` resource (id, name). The new ID is cached
        for friendly-name resolution in subsequent calls.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        result = self._call(
            "POST",
            "/conversations.create",
            json={"name": name, "is_private": is_private},
        )
        channel: object = result.get("channel") or {}
        if isinstance(channel, dict):
            channel_obj = cast("dict[str, Any]", channel)
            channel_id: object = channel_obj.get("id")
            channel_name: object = channel_obj.get("name") or name
            if (
                isinstance(channel_id, str)
                and channel_id
                and isinstance(channel_name, str)
                and channel_name
            ):
                self._channel_name_cache[channel_name] = channel_id
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def rename_channel(self, channel: SlackChannelInput, name: str) -> dict[str, Any]:
        """Rename a channel.

        Accepts a channel name, raw ID, or channel-summary dict.
        """
        resolved = self._resolve_channel(channel)
        if not name:
            raise ValueError("name must be non-empty")
        return self._call(
            "POST",
            "/conversations.rename",
            json={"channel": resolved, "name": name},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def set_channel_topic(self, channel: SlackChannelInput, topic: str) -> dict[str, Any]:
        """Set the topic on a channel."""
        resolved = self._resolve_channel(channel)
        return self._call(
            "POST",
            "/conversations.setTopic",
            json={"channel": resolved, "topic": topic},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def set_channel_purpose(self, channel: SlackChannelInput, purpose: str) -> dict[str, Any]:
        """Set the purpose/description on a channel."""
        resolved = self._resolve_channel(channel)
        return self._call(
            "POST",
            "/conversations.setPurpose",
            json={"channel": resolved, "purpose": purpose},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def join_channel(self, channel: SlackChannelInput) -> dict[str, Any]:
        """Join a public channel."""
        resolved = self._resolve_channel(channel)
        return self._call("POST", "/conversations.join", json={"channel": resolved})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def leave_channel(self, channel: SlackChannelInput) -> dict[str, Any]:
        """Leave a channel."""
        resolved = self._resolve_channel(channel)
        return self._call("POST", "/conversations.leave", json={"channel": resolved})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def invite_to_channel(self, channel: SlackChannelInput, users: list[str]) -> dict[str, Any]:
        """Invite one or more users (Slack user IDs) to a channel."""
        resolved = self._resolve_channel(channel)
        if not users:
            raise ValueError("users must be non-empty")
        return self._call(
            "POST",
            "/conversations.invite",
            json={"channel": resolved, "users": ",".join(users)},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def kick_from_channel(self, channel: SlackChannelInput, user: str) -> dict[str, Any]:
        """Kick a user from a channel."""
        resolved = self._resolve_channel(channel)
        if not user:
            raise ValueError("user must be non-empty")
        return self._call(
            "POST",
            "/conversations.kick",
            json={"channel": resolved, "user": user},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def archive_channel(self, channel: SlackChannelInput) -> dict[str, Any]:
        """Archive a channel (recoverable)."""
        resolved = self._resolve_channel(channel)
        return self._call("POST", "/conversations.archive", json={"channel": resolved})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def unarchive_channel(self, channel: SlackChannelInput) -> dict[str, Any]:
        """Unarchive a channel."""
        resolved = self._resolve_channel(channel)
        return self._call("POST", "/conversations.unarchive", json={"channel": resolved})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def open_im(self, users: list[str], *, return_im: bool = True) -> dict[str, Any]:
        """Open a direct-message conversation with one or more users.

        Returns the IM channel record. The resulting ``channel.id`` can be
        passed straight into :meth:`post_message`.
        """
        if not users:
            raise ValueError("users must contain at least one id")
        return self._call(
            "POST",
            "/conversations.open",
            json={"users": ",".join(users), "return_im": return_im},
        )

    # MARK: - Messages (modify / pin / react)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def post_ephemeral(
        self,
        channel: SlackChannelInput,
        user: str,
        text: str | None = None,
        *,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Post an ephemeral message visible only to ``user``."""
        resolved = self._resolve_channel(channel)
        if not user:
            raise ValueError("user must be non-empty")
        if not text and not blocks:
            raise ValueError("text or blocks must be supplied")
        payload: dict[str, Any] = {"channel": resolved, "user": user}
        if text is not None:
            payload["text"] = text
        if blocks is not None:
            payload["blocks"] = blocks
        return self._call("POST", "/chat.postEphemeral", json=payload)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_message(
        self,
        channel: SlackChannelInput,
        ts: SlackMessageTsInput,
        text: str | None = None,
        *,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Update a previously-posted message.

        Both ``channel`` and ``ts`` accept the natural output of
        :meth:`channel_history`: ``ts`` may be a raw timestamp string or a
        message-summary dict (the ``ts`` field is read out of it).
        """
        resolved = self._resolve_channel(channel)
        resolved_ts = self._resolve_message_ts(ts)
        if not text and not blocks:
            raise ValueError("text or blocks must be supplied")
        payload: dict[str, Any] = {"channel": resolved, "ts": resolved_ts}
        if text is not None:
            payload["text"] = text
        if blocks is not None:
            payload["blocks"] = blocks
        return self._call("POST", "/chat.update", json=payload)

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_message(self, channel: SlackChannelInput, ts: SlackMessageTsInput) -> dict[str, Any]:
        """Delete a message.

        Destructive: the message cannot be recovered. Accepts the same input
        shapes as :meth:`update_message`. Confirm with the user first.
        """
        resolved = self._resolve_channel(channel)
        resolved_ts = self._resolve_message_ts(ts)
        return self._call("POST", "/chat.delete", json={"channel": resolved, "ts": resolved_ts})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def schedule_message(
        self,
        channel: SlackChannelInput,
        post_at: int,
        text: str,
    ) -> dict[str, Any]:
        """Schedule a message for future posting.

        ``post_at`` is the Unix epoch second when Slack should publish.
        """
        resolved = self._resolve_channel(channel)
        if not text:
            raise ValueError("text must be non-empty")
        if post_at <= 0:
            raise ValueError("post_at must be a positive Unix timestamp")
        return self._call(
            "POST",
            "/chat.scheduleMessage",
            json={"channel": resolved, "post_at": post_at, "text": text},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_permalink(
        self, channel: SlackChannelInput, message_ts: SlackMessageTsInput
    ) -> dict[str, Any]:
        """Return a permalink to a specific message.

        Accepts the same tolerant inputs as :meth:`update_message`.
        """
        resolved = self._resolve_channel(channel)
        resolved_ts = self._resolve_message_ts(message_ts)
        return self._call(
            "GET",
            "/chat.getPermalink",
            params={"channel": resolved, "message_ts": resolved_ts},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_reaction(
        self,
        channel: SlackChannelInput,
        timestamp: SlackMessageTsInput,
        name: str,
    ) -> dict[str, Any]:
        """Add an emoji reaction to a message.

        ``name`` is the reaction name without colons (``"thumbsup"``,
        ``"white_check_mark"``).
        """
        resolved = self._resolve_channel(channel)
        resolved_ts = self._resolve_message_ts(timestamp)
        if not name:
            raise ValueError("name must be non-empty")
        return self._call(
            "POST",
            "/reactions.add",
            json={"channel": resolved, "timestamp": resolved_ts, "name": name},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def remove_reaction(
        self,
        channel: SlackChannelInput,
        timestamp: SlackMessageTsInput,
        name: str,
    ) -> dict[str, Any]:
        """Remove an emoji reaction from a message."""
        resolved = self._resolve_channel(channel)
        resolved_ts = self._resolve_message_ts(timestamp)
        if not name:
            raise ValueError("name must be non-empty")
        return self._call(
            "POST",
            "/reactions.remove",
            json={"channel": resolved, "timestamp": resolved_ts, "name": name},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def pin_message(
        self, channel: SlackChannelInput, timestamp: SlackMessageTsInput
    ) -> dict[str, Any]:
        """Pin a message to a channel."""
        resolved = self._resolve_channel(channel)
        resolved_ts = self._resolve_message_ts(timestamp)
        return self._call(
            "POST",
            "/pins.add",
            json={"channel": resolved, "timestamp": resolved_ts},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def unpin_message(
        self, channel: SlackChannelInput, timestamp: SlackMessageTsInput
    ) -> dict[str, Any]:
        """Unpin a message from a channel."""
        resolved = self._resolve_channel(channel)
        resolved_ts = self._resolve_message_ts(timestamp)
        return self._call(
            "POST",
            "/pins.remove",
            json={"channel": resolved, "timestamp": resolved_ts},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_pins(self, channel: SlackChannelInput) -> dict[str, Any]:
        """List pinned items in a channel."""
        resolved = self._resolve_channel(channel)
        return self._call("GET", "/pins.list", params={"channel": resolved})

    # MARK: - Files

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_files(
        self,
        *,
        channel: SlackChannelInput | None = None,
        user: str | None = None,
        count: int = 100,
        page: int = 1,
    ) -> dict[str, Any]:
        """List files (optionally filtered by channel/user)."""
        params: dict[str, Any] = {"count": count, "page": page}
        if channel is not None:
            params["channel"] = self._resolve_channel(channel)
        if user is not None:
            params["user"] = user
        return self._call("GET", "/files.list", params=params)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def file_info(self, file_id: str) -> dict[str, Any]:
        """Return metadata for a single file."""
        if not file_id:
            raise ValueError("file_id must be a non-empty string")
        return self._call("GET", "/files.info", params={"file": file_id})

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_file(self, file_id: str) -> dict[str, Any]:
        """Delete a Slack file.

        Destructive: the upload is removed and cannot be recovered. Confirm
        with the user first.
        """
        if not file_id:
            raise ValueError("file_id must be a non-empty string")
        return self._call("POST", "/files.delete", json={"file": file_id})

    # MARK: - Reminders, emoji, team

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_reminder(
        self,
        text: str,
        time: str,
        *,
        user: str | None = None,
    ) -> dict[str, Any]:
        """Add a reminder.

        ``time`` accepts free-form English (``"in 1 hour"``) or a Unix epoch
        second as a string.
        """
        if not text or not time:
            raise ValueError("text and time must be non-empty")
        payload: dict[str, Any] = {"text": text, "time": time}
        if user is not None:
            payload["user"] = user
        return self._call("POST", "/reminders.add", json=payload)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_reminders(self) -> dict[str, Any]:
        """List reminders set by the token's user."""
        return self._call("GET", "/reminders.list")

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_reminder(self, reminder_id: str) -> dict[str, Any]:
        """Delete a reminder.

        Destructive: the reminder cannot be recovered.
        """
        if not reminder_id:
            raise ValueError("reminder_id must be a non-empty string")
        return self._call("POST", "/reminders.delete", json={"reminder": reminder_id})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def emoji_list(self) -> dict[str, Any]:
        """List custom emoji in the workspace."""
        return self._call("GET", "/emoji.list")

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def team_info(self) -> dict[str, Any]:
        """Return workspace/team metadata."""
        return self._call("GET", "/team.info")

    # MARK: - Internal

    def _resolve_channel(self, channel: Any) -> str:
        """Coerce a channel name/dict/list into a raw Slack channel ID.

        Accepts:
        - raw IDs (``"C0123"``, ``"D0456"``, ``"G0789"``)
        - friendly channel names (``"general"``), resolved against the cache
          populated by :meth:`list_channels` and :meth:`create_channel`
        - channel-summary dicts from :meth:`list_channels` (looks for
          ``channel_id``, ``id``, then ``name``)
        - single-item lists of any of the above
        """
        if isinstance(channel, list):
            channel_list = cast("list[Any]", channel)
            if not channel_list:
                raise ValueError("channel must be non-empty")
            channel = channel_list[0]
        if isinstance(channel, dict):
            channel_dict = cast("dict[str, Any]", channel)
            for key in ("channel_id", "id", "channel"):
                value: object = channel_dict.get(key)
                if isinstance(value, str) and value:
                    return value
            name: object = channel_dict.get("name")
            if isinstance(name, str) and name:
                resolved = self._channel_name_cache.get(name)
                if resolved:
                    return resolved
                # Falling back to the name itself; Slack accepts ``#general``
                # style references for some endpoints.
                return name
            raise ValueError("channel dict must contain channel_id, id, or name")
        if isinstance(channel, str):
            if not channel:
                raise ValueError("channel must be a non-empty string")
            if channel.startswith(("C", "D", "G")) and len(channel) >= 9:
                return channel
            stripped = channel.lstrip("#")
            cached = self._channel_name_cache.get(stripped)
            if cached:
                return cached
            return channel
        raise ValueError("channel must be a string, dict, or list")

    @staticmethod
    def _resolve_message_ts(ts: Any) -> str:
        """Coerce a Slack message ts string or message-summary dict into a ts.

        Accepts a raw ``"1234567890.123456"`` timestamp string or a dict
        returned by :meth:`channel_history`/:meth:`post_message` (reads the
        ``ts`` field).
        """
        if isinstance(ts, dict):
            ts_dict = cast("dict[str, Any]", ts)
            value: object = (
                ts_dict.get("ts") or ts_dict.get("timestamp") or ts_dict.get("message_ts")
            )
            if isinstance(value, str) and value:
                return value
            message: object = ts_dict.get("message")
            if isinstance(message, dict):
                message_dict = cast("dict[str, Any]", message)
                value = message_dict.get("ts")
                if isinstance(value, str) and value:
                    return value
            raise ValueError("ts dict must contain a 'ts' field")
        if isinstance(ts, str):
            if not ts:
                raise ValueError("ts must be a non-empty string")
            return ts
        if isinstance(ts, int | float):
            return str(ts)
        raise ValueError("ts must be a string or message dict")

    def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._client.request(
            method,
            path,
            params=params,
            json=json,
            headers={"Content-Type": "application/json; charset=utf-8"} if json else None,
        )
        raw: object = response.json()
        data: dict[str, Any] | None = cast("dict[str, Any]", raw) if isinstance(raw, dict) else None
        if data is None or not data.get("ok", False):
            error: object = data.get("error") if data is not None else "unknown_error"
            detail: dict[str, Any] = data if data is not None else {"raw": raw}
            raise SlackApiError(
                f"Slack API call {path} failed: {error}",
                detail=detail,
                status=response.status,
            )
        return data
