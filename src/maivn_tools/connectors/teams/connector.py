"""Microsoft Teams connector via Microsoft Graph."""
# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.oauth import OAuth2Token, OAuth2TokenProvider
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from ..microsoft_graph._shared import TokenSource, make_graph_client
from .output_schemas import (
    LIST_CHANNEL_MESSAGES_OUTPUT,
    LIST_CHANNELS_OUTPUT,
    LIST_CHAT_MESSAGES_OUTPUT,
    LIST_CHATS_OUTPUT,
    LIST_JOINED_TEAMS_OUTPUT,
)

_DEFAULT_LIST_LIMIT = 25


@toolset(prefix="teams")
class MicrosoftTeamsToolSet:
    """A connector for Microsoft Teams via Microsoft Graph v1.0."""

    metadata = ProviderMetadata(
        name="microsoft_teams",
        display_name="Microsoft Teams",
        version="0.1.0",
        description="Read and post to Teams channels, chats, and members.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "Team.ReadBasic.All": "Read teams the user is in.",
            "Channel.ReadBasic.All": "List channels.",
            "ChannelMessage.Send": "Send channel messages.",
            "Chat.Read": "Read 1:1 / group chats.",
            "Chat.ReadWrite": "Read and send chat messages.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://learn.microsoft.com/en-us/graph/teams-concept-overview",
        homepage_url="https://www.microsoft.com/en-us/microsoft-teams",
        tags=("collaboration", "microsoft"),
    )

    def __init__(
        self,
        *,
        token: TokenSource,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        self.connection = connection
        self._client: HttpClient = make_graph_client(token, transport=transport)
        # team_id -> {channel display name -> channel id}; populated by
        # ``list_channels`` so write tools can accept a channel name.
        self._channel_name_cache: dict[str, dict[str, str]] = {}
        # team display name -> team id; populated by ``list_joined_teams``.
        self._team_name_cache: dict[str, str] = {}

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Joined teams

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_JOINED_TEAMS_OUTPUT)
    def list_joined_teams(
        self,
        *,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List teams the current user is a member of.

        Best first tool to discover which Teams the user has access to.
        Returns compact summaries with ``team_ref`` (stable ``team_1``,
        ``team_2``), ``display_name``, and ``description``. Graph team IDs
        (GUIDs) are omitted by default; pass ``include_ids=True`` when a
        follow-up tool needs ``team_id``. ``include_metadata=False`` returns
        the raw Graph response.
        """
        payload: dict[str, Any] = self._client.get("/me/joinedTeams").json()
        if not include_metadata:
            return payload

        teams: list[dict[str, Any]] = []
        values: list[Any] = payload.get("value") or []
        for index, team in enumerate(values, start=1):
            if not isinstance(team, dict):
                continue
            team_dict = cast(dict[str, Any], team)
            display_name = team_dict.get("displayName", "")
            team_id = team_dict.get("id", "")
            if display_name and team_id:
                self._team_name_cache[display_name] = team_id
            summary: dict[str, Any] = {
                "team_ref": f"team_{index}",
                "display_name": display_name,
                "description": team_dict.get("description", ""),
            }
            if include_ids:
                summary["team_id"] = team_id
            teams.append(summary)
        return {"teams": teams}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_team(self, team_id: Any) -> dict[str, Any]:
        """Return one team by ID.

        Accepts a Graph team GUID, a team display name (resolved against the
        :meth:`list_joined_teams` cache), or a team-summary dict from
        :meth:`list_joined_teams`.
        """
        resolved = self._resolve_team(team_id)
        return self._client.get(f"/teams/{resolved}").json()

    # MARK: - Channels

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_CHANNELS_OUTPUT)
    def list_channels(
        self,
        team_id: Any,
        *,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List channels in a team.

        Best first tool when posting to a Teams channel. Returns compact
        summaries with ``channel_ref``, ``display_name``, ``description``,
        and ``membership_type``. Channel IDs are omitted by default; pass
        ``include_ids=True`` when a follow-up tool needs ``channel_id``.
        """
        resolved_team = self._resolve_team(team_id)
        payload: dict[str, Any] = self._client.get(f"/teams/{resolved_team}/channels").json()
        if not include_metadata:
            return payload

        channels: list[dict[str, Any]] = []
        team_cache = self._channel_name_cache.setdefault(resolved_team, {})
        values: list[Any] = payload.get("value") or []
        for index, channel in enumerate(values, start=1):
            if not isinstance(channel, dict):
                continue
            channel_dict = cast(dict[str, Any], channel)
            display_name = channel_dict.get("displayName", "")
            channel_id = channel_dict.get("id", "")
            if display_name and channel_id:
                team_cache[display_name] = channel_id
            summary: dict[str, Any] = {
                "channel_ref": f"channel_{index}",
                "display_name": display_name,
                "description": channel_dict.get("description", ""),
                "membership_type": channel_dict.get("membershipType", "standard"),
            }
            if include_ids:
                summary["channel_id"] = channel_id
                summary["team_id"] = resolved_team
            channels.append(summary)
        return {"channels": channels}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_channel(self, team_id: Any, channel_id: Any) -> dict[str, Any]:
        """Return one channel.

        Both ``team_id`` and ``channel_id`` tolerate display names or
        summary dicts from list tools.
        """
        resolved_team = self._resolve_team(team_id)
        resolved_channel = self._resolve_channel(resolved_team, channel_id)
        return self._client.get(f"/teams/{resolved_team}/channels/{resolved_channel}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_channel(
        self,
        team_id: Any,
        *,
        display_name: str,
        description: str | None = None,
        membership_type: str = "standard",
    ) -> dict[str, Any]:
        """Create a new channel.

        ``membership_type`` is one of ``"standard"``, ``"private"``, or
        ``"shared"``. Returns the new channel resource.
        """
        resolved_team = self._resolve_team(team_id)
        if not display_name:
            raise ValueError("display_name must be non-empty")
        if membership_type not in {"standard", "private", "shared"}:
            raise ValueError("membership_type must be standard/private/shared")
        payload: dict[str, Any] = {
            "displayName": display_name,
            "membershipType": membership_type,
        }
        if description is not None:
            payload["description"] = description
        result: Any = self._client.post(f"/teams/{resolved_team}/channels", json=payload).json()
        if isinstance(result, dict):
            result_dict = cast(dict[str, Any], result)
            channel_id = result_dict.get("id")
            if isinstance(channel_id, str) and channel_id:
                self._channel_name_cache.setdefault(resolved_team, {})[display_name] = channel_id
        return cast(dict[str, Any], result)

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_channel(self, team_id: Any, channel_id: Any) -> dict[str, Any]:
        """Delete a channel.

        Destructive: the channel and its history are removed. Confirm with
        the user first.
        """
        resolved_team = self._resolve_team(team_id)
        resolved_channel = self._resolve_channel(resolved_team, channel_id)
        self._client.delete(f"/teams/{resolved_team}/channels/{resolved_channel}")
        return {"id": resolved_channel, "deleted": True}

    # MARK: - Channel messages

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_CHANNEL_MESSAGES_OUTPUT)
    def list_channel_messages(
        self,
        team_id: Any,
        channel_id: Any,
        *,
        top: int = _DEFAULT_LIST_LIMIT,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List recent messages in a channel.

        Best first tool to read what is happening in a Teams channel. By
        default returns compact summaries with ``message_ref``, ``sender``
        (display name), ``content_preview`` (first ~200 chars stripped of
        HTML tags), and ``created_at``. Graph message IDs are omitted by
        default; pass ``include_ids=True`` when a follow-up tool needs
        ``message_id``. ``include_metadata=False`` returns the raw response.
        """
        resolved_team = self._resolve_team(team_id)
        resolved_channel = self._resolve_channel(resolved_team, channel_id)
        params: dict[str, Any] | None = {"$top": top} if top else None
        payload: dict[str, Any] = self._client.get(
            f"/teams/{resolved_team}/channels/{resolved_channel}/messages",
            params=params,
        ).json()
        if not include_metadata:
            return payload

        summaries: list[dict[str, Any]] = []
        values: list[Any] = payload.get("value") or []
        for index, message in enumerate(values, start=1):
            if not isinstance(message, dict):
                continue
            message_dict = cast(dict[str, Any], message)
            summaries.append(
                self._message_summary(message_dict, index=index, include_ids=include_ids)
            )
        result: dict[str, Any] = {"messages": summaries}
        next_link = payload.get("@odata.nextLink")
        if next_link:
            result["next_link"] = next_link
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def send_channel_message(
        self,
        team_id: Any,
        channel_id: Any,
        *,
        content: str,
        content_type: str = "html",
        subject: str | None = None,
    ) -> dict[str, Any]:
        """Post a message to a channel.

        ``team_id`` and ``channel_id`` tolerate display names or summary
        dicts. Returns the new Graph ``chatMessage`` resource.
        """
        resolved_team = self._resolve_team(team_id)
        resolved_channel = self._resolve_channel(resolved_team, channel_id)
        if not content:
            raise ValueError("content must be non-empty")
        if content_type not in {"text", "html"}:
            raise ValueError("content_type must be 'text' or 'html'")
        body: dict[str, Any] = {"body": {"contentType": content_type, "content": content}}
        if subject is not None:
            body["subject"] = subject
        return self._client.post(
            f"/teams/{resolved_team}/channels/{resolved_channel}/messages",
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_channel_replies(
        self,
        team_id: Any,
        channel_id: Any,
        message_id: Any,
    ) -> dict[str, Any]:
        """List replies under a channel message."""
        resolved_team = self._resolve_team(team_id)
        resolved_channel = self._resolve_channel(resolved_team, channel_id)
        resolved_message = self._resolve_message_id(message_id)
        return self._client.get(
            f"/teams/{resolved_team}/channels/{resolved_channel}"
            f"/messages/{resolved_message}/replies",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def reply_to_channel_message(
        self,
        team_id: Any,
        channel_id: Any,
        message_id: Any,
        *,
        content: str,
        content_type: str = "html",
    ) -> dict[str, Any]:
        """Reply in a thread under a channel message.

        ``message_id`` accepts the dict returned by
        :meth:`list_channel_messages` (with ``include_ids=True``).
        """
        resolved_team = self._resolve_team(team_id)
        resolved_channel = self._resolve_channel(resolved_team, channel_id)
        resolved_message = self._resolve_message_id(message_id)
        if not content:
            raise ValueError("content must be non-empty")
        body = {"body": {"contentType": content_type, "content": content}}
        return self._client.post(
            f"/teams/{resolved_team}/channels/{resolved_channel}"
            f"/messages/{resolved_message}/replies",
            json=body,
        ).json()

    # MARK: - Members

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_members(self, team_id: Any) -> dict[str, Any]:
        """List members of a team."""
        resolved_team = self._resolve_team(team_id)
        return self._client.get(f"/teams/{resolved_team}/members").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_member(
        self,
        team_id: Any,
        *,
        user_id: str,
        roles: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add a member to a team.

        ``user_id`` is the Azure AD user GUID.
        """
        resolved_team = self._resolve_team(team_id)
        if not user_id:
            raise ValueError("user_id must be non-empty")
        payload = {
            "@odata.type": "#microsoft.graph.aadUserConversationMember",
            "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{user_id}",
            "roles": roles or [],
        }
        return self._client.post(f"/teams/{resolved_team}/members", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def remove_member(self, team_id: Any, membership_id: str) -> dict[str, Any]:
        """Remove a member.

        Destructive: the user loses access to the team and its channels.
        """
        resolved_team = self._resolve_team(team_id)
        if not membership_id:
            raise ValueError("membership_id must be non-empty")
        self._client.delete(f"/teams/{resolved_team}/members/{membership_id}")
        return {"id": membership_id, "removed": True}

    # MARK: - Chats

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_CHATS_OUTPUT)
    def list_chats(
        self,
        *,
        top: int = _DEFAULT_LIST_LIMIT,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List chats for the current user.

        Returns compact summaries with ``chat_ref``, ``topic`` (display
        title), ``chat_type``, and ``last_updated``. Chat IDs are omitted by
        default; pass ``include_ids=True`` when sending follow-up messages
        via :meth:`send_chat_message`.
        """
        params: dict[str, Any] | None = {"$top": top} if top else None
        payload: dict[str, Any] = self._client.get("/me/chats", params=params).json()
        if not include_metadata:
            return payload

        chats: list[dict[str, Any]] = []
        values: list[Any] = payload.get("value") or []
        for index, chat in enumerate(values, start=1):
            if not isinstance(chat, dict):
                continue
            chat_dict = cast(dict[str, Any], chat)
            summary: dict[str, Any] = {
                "chat_ref": f"chat_{index}",
                "topic": chat_dict.get("topic", ""),
                "chat_type": chat_dict.get("chatType", ""),
                "last_updated": chat_dict.get("lastUpdatedDateTime", ""),
            }
            if include_ids:
                summary["chat_id"] = chat_dict.get("id", "")
            chats.append(summary)
        result: dict[str, Any] = {"chats": chats}
        next_link = payload.get("@odata.nextLink")
        if next_link:
            result["next_link"] = next_link
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_chat(self, chat_id: Any) -> dict[str, Any]:
        """Return one chat.

        Accepts a Graph chat ID or a chat-summary dict from
        :meth:`list_chats`.
        """
        resolved = self._resolve_chat(chat_id)
        return self._client.get(f"/chats/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_CHAT_MESSAGES_OUTPUT)
    def list_chat_messages(
        self,
        chat_id: Any,
        *,
        top: int = _DEFAULT_LIST_LIMIT,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List messages in a chat.

        Returns compact summaries with ``message_ref``, ``sender``,
        ``content_preview``, and ``created_at`` by default.
        """
        resolved = self._resolve_chat(chat_id)
        params: dict[str, Any] | None = {"$top": top} if top else None
        payload: dict[str, Any] = self._client.get(
            f"/chats/{resolved}/messages", params=params
        ).json()
        if not include_metadata:
            return payload

        summaries: list[dict[str, Any]] = []
        values: list[Any] = payload.get("value") or []
        for index, message in enumerate(values, start=1):
            if not isinstance(message, dict):
                continue
            message_dict = cast(dict[str, Any], message)
            summaries.append(
                self._message_summary(message_dict, index=index, include_ids=include_ids)
            )
        return {"messages": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def send_chat_message(
        self,
        chat_id: Any,
        *,
        content: str,
        content_type: str = "html",
    ) -> dict[str, Any]:
        """Send a 1:1 or group chat message.

        ``chat_id`` accepts a Graph chat ID or chat-summary dict.
        """
        resolved = self._resolve_chat(chat_id)
        if not content:
            raise ValueError("content must be non-empty")
        body = {"body": {"contentType": content_type, "content": content}}
        return self._client.post(f"/chats/{resolved}/messages", json=body).json()

    # MARK: - Internal

    def _resolve_team(self, team: Any) -> str:
        if isinstance(team, list):
            if not team:
                raise ValueError("team_id must be non-empty")
            team = cast(Any, team[0])
        if isinstance(team, dict):
            team_dict = cast(dict[str, Any], team)
            for key in ("team_id", "id"):
                value = team_dict.get(key)
                if isinstance(value, str) and value:
                    return value
            display_name = team_dict.get("display_name") or team_dict.get("displayName")
            if isinstance(display_name, str) and display_name:
                cached = self._team_name_cache.get(display_name)
                if cached:
                    return cached
                return display_name
            raise ValueError("team dict must contain team_id, id, or display_name")
        if isinstance(team, str):
            if not team:
                raise ValueError("team_id must be a non-empty string")
            cached = self._team_name_cache.get(team)
            if cached:
                return cached
            return team
        raise ValueError("team_id must be a string, dict, or list")

    def _resolve_channel(self, team_id: str, channel: Any) -> str:
        if isinstance(channel, list):
            if not channel:
                raise ValueError("channel_id must be non-empty")
            channel = cast(Any, channel[0])
        team_cache = self._channel_name_cache.get(team_id, {})
        if isinstance(channel, dict):
            channel_dict = cast(dict[str, Any], channel)
            for key in ("channel_id", "id"):
                value = channel_dict.get(key)
                if isinstance(value, str) and value:
                    return value
            display_name = channel_dict.get("display_name") or channel_dict.get("displayName")
            if isinstance(display_name, str) and display_name:
                cached = team_cache.get(display_name)
                if cached:
                    return cached
                return display_name
            raise ValueError("channel dict must contain channel_id, id, or display_name")
        if isinstance(channel, str):
            if not channel:
                raise ValueError("channel_id must be a non-empty string")
            cached = team_cache.get(channel)
            if cached:
                return cached
            return channel
        raise ValueError("channel_id must be a string, dict, or list")

    @staticmethod
    def _resolve_chat(chat: Any) -> str:
        if isinstance(chat, dict):
            chat_dict = cast(dict[str, Any], chat)
            for key in ("chat_id", "id"):
                value = chat_dict.get(key)
                if isinstance(value, str) and value:
                    return value
            raise ValueError("chat dict must contain chat_id or id")
        if isinstance(chat, str):
            if not chat:
                raise ValueError("chat_id must be a non-empty string")
            return chat
        raise ValueError("chat_id must be a string or dict")

    @staticmethod
    def _resolve_message_id(message: Any) -> str:
        if isinstance(message, dict):
            message_dict = cast(dict[str, Any], message)
            for key in ("message_id", "id"):
                value = message_dict.get(key)
                if isinstance(value, str) and value:
                    return value
            raise ValueError("message dict must contain message_id or id")
        if isinstance(message, str):
            if not message:
                raise ValueError("message_id must be a non-empty string")
            return message
        raise ValueError("message_id must be a string or dict")

    @staticmethod
    def _message_summary(
        message: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        body: Any = message.get("body") or {}
        raw_content: Any = ""
        if isinstance(body, dict):
            raw_content = cast(dict[str, Any], body).get("content", "")
        content: str = raw_content if isinstance(raw_content, str) else ""
        # Strip naive HTML tags for a friendlier preview.
        import re

        preview = re.sub(r"<[^>]+>", "", content)
        preview = preview.strip()
        if len(preview) > 200:
            preview = preview[:197] + "..."
        from_obj: Any = message.get("from") or {}
        sender_obj: Any = from_obj.get("user") or {}
        raw_sender: Any = ""
        if isinstance(sender_obj, dict):
            raw_sender = cast(dict[str, Any], sender_obj).get("displayName", "")
        sender: str = raw_sender if isinstance(raw_sender, str) else ""
        summary: dict[str, Any] = {
            "message_ref": f"message_{index}",
            "sender": sender,
            "content_preview": preview,
            "created_at": message.get("createdDateTime", ""),
        }
        if include_ids:
            summary["message_id"] = message.get("id", "")
        return summary


__all__ = ["MicrosoftTeamsToolSet", "OAuth2Token", "OAuth2TokenProvider"]
