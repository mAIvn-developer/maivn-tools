"""Discord REST API connector (bot-token flavored)."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: - Constants

_DEFAULT_LIST_LIMIT = 25
_DEFAULT_MESSAGES_LIMIT = 20


# MARK: - ToolSet


@toolset(prefix="discord")
class DiscordToolSet:
    """A connector for the Discord REST API.

    Args:
        token: Bot token (default) or user OAuth bearer.
        token_type: ``"Bot"`` (default) or ``"Bearer"`` -- sent as the
            ``Authorization`` prefix.
        api_version: API version path segment (e.g. ``"10"``).
    """

    metadata = ProviderMetadata(
        name="discord",
        display_name="Discord",
        version="0.1.0",
        description="Guilds, channels, messages, members, roles, and DMs.",
        auth_modes=(AuthMode.API_KEY, AuthMode.OAUTH2_AUTH_CODE),
        scopes={
            "identify": "Read the bot or user identity.",
            "guilds": "List the user's guilds.",
            "messages.read": "Read DM history.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://discord.com/developers/docs/intro",
        homepage_url="https://discord.com/",
        tags=("social-media", "chat"),
    )

    def __init__(
        self,
        *,
        token: str,
        token_type: str = "Bot",
        api_version: str = "10",
        base_url: str = "https://discord.com/api",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not token:
            raise ValueError("token is required")
        if token_type not in {"Bot", "Bearer"}:
            raise ValueError("token_type must be Bot or Bearer")
        self.connection = connection
        self._version = api_version
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(token, header="Authorization", prefix=token_type),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        # name -> id cache populated by ``list_guild_channels`` so write tools
        # can accept friendly channel names.
        self._channel_name_cache: dict[str, str] = {}

    @property
    def client(self) -> HttpClient:
        return self._client

    def _v(self, suffix: str) -> str:
        return f"/v{self._version}{suffix}"

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_current_user(self) -> dict[str, Any]:
        """Return the bot or user identity (``/users/@me``).

        Best first call at startup to verify the bot token works and to
        discover the bot's Discord user ID.
        """
        return self._client.get(self._v("/users/@me")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_current_user_guilds(
        self,
        *,
        before: str | None = None,
        after: str | None = None,
        limit: int = _DEFAULT_LIST_LIMIT,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List guilds the current user is a member of.

        Best first tool to find which Discord servers (guilds) the bot can
        operate in. Returns compact summaries with ``guild_ref`` (stable
        ``guild_1``, ``guild_2``), ``name``, ``owner``, and ``permissions``.
        Raw Discord snowflake IDs are omitted by default; pass
        ``include_ids=True`` when you need ``guild_id`` to feed into
        :meth:`list_guild_channels` or :meth:`list_guild_members`. Set
        ``include_metadata=False`` for the raw Discord response.
        """
        params: dict[str, Any] = {"limit": limit}
        if before is not None:
            params["before"] = before
        if after is not None:
            params["after"] = after
        payload: Any = self._client.get(self._v("/users/@me/guilds"), params=params).json()
        if not include_metadata:
            return payload

        guilds: list[dict[str, Any]] = []
        items: list[Any] = cast(list[Any], payload) if isinstance(payload, list) else []
        for index, guild in enumerate(items, start=1):
            if not isinstance(guild, dict):
                continue
            guild = cast(dict[str, Any], guild)
            summary: dict[str, Any] = {
                "guild_ref": f"guild_{index}",
                "name": guild.get("name", ""),
                "owner": bool(guild.get("owner")),
                "permissions": guild.get("permissions"),
            }
            if include_ids:
                summary["guild_id"] = guild.get("id", "")
            guilds.append(summary)
        return {"guilds": guilds}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_guild(self, guild_id: str) -> dict[str, Any]:
        """Return a guild's metadata.

        ``guild_id`` is the raw Discord snowflake; obtain it via
        :meth:`list_current_user_guilds` with ``include_ids=True``.
        """
        if not guild_id:
            raise ValueError("guild_id is required")
        return self._client.get(self._v(f"/guilds/{guild_id}")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_guild_channels(
        self,
        guild_id: str,
        *,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List channels in a guild.

        Returns compact summaries with ``channel_ref``, ``name``, ``type``,
        ``topic``, and ``position`` by default. Raw IDs are omitted; pass
        ``include_ids=True`` to receive ``channel_id`` for follow-up message
        tools. ``include_metadata=False`` returns the raw response.
        """
        if not guild_id:
            raise ValueError("guild_id is required")
        payload: Any = self._client.get(self._v(f"/guilds/{guild_id}/channels")).json()
        if not include_metadata:
            return payload

        channels: list[dict[str, Any]] = []
        items: list[Any] = cast(list[Any], payload) if isinstance(payload, list) else []
        for index, channel in enumerate(items, start=1):
            if not isinstance(channel, dict):
                continue
            channel = cast(dict[str, Any], channel)
            name = channel.get("name", "")
            channel_id = channel.get("id", "")
            if name and channel_id:
                self._channel_name_cache[name] = channel_id
            summary: dict[str, Any] = {
                "channel_ref": f"channel_{index}",
                "name": name,
                "type": channel.get("type"),
                "topic": channel.get("topic"),
                "position": channel.get("position"),
            }
            if include_ids:
                summary["channel_id"] = channel_id
            channels.append(summary)
        return {"channels": channels}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_guild_members(
        self,
        guild_id: str,
        *,
        limit: int = 100,
        after: str | None = None,
    ) -> dict[str, Any]:
        """List members of a guild.

        Returns the raw Discord member-list response (each entry has ``user``
        and ``roles``).
        """
        if not guild_id:
            raise ValueError("guild_id is required")
        params: dict[str, Any] = {"limit": limit}
        if after is not None:
            params["after"] = after
        return self._client.get(self._v(f"/guilds/{guild_id}/members"), params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_channel(self, channel_id: str) -> dict[str, Any]:
        """Return a channel's metadata."""
        if not channel_id:
            raise ValueError("channel_id is required")
        return self._client.get(self._v(f"/channels/{channel_id}")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_messages(
        self,
        channel_id: Any,
        *,
        limit: int = _DEFAULT_MESSAGES_LIMIT,
        before: str | None = None,
        after: str | None = None,
        around: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List messages in a channel.

        Best first tool for reading channel history. Accepts a channel name
        (resolved against the cache populated by :meth:`list_guild_channels`),
        a raw snowflake ID, or a channel-summary dict. Returns compact
        summaries with ``message_ref``, ``author`` (username), ``content``,
        ``timestamp``, and ``has_attachments``. The Discord snowflake IDs are
        internal handles -- they are omitted by default. Set
        ``include_ids=True`` when a follow-up tool needs ``message_id``.
        ``include_metadata=False`` returns the raw Discord response.
        """
        resolved = self._resolve_channel(channel_id)
        params: dict[str, Any] = {"limit": limit}
        if before is not None:
            params["before"] = before
        if after is not None:
            params["after"] = after
        if around is not None:
            params["around"] = around
        payload: Any = self._client.get(
            self._v(f"/channels/{resolved}/messages"), params=params
        ).json()
        if not include_metadata:
            return payload

        summaries: list[dict[str, Any]] = []
        items: list[Any] = cast(list[Any], payload) if isinstance(payload, list) else []
        for index, message in enumerate(items, start=1):
            if not isinstance(message, dict):
                continue
            message = cast(dict[str, Any], message)
            author_raw: Any = message.get("author") or {}
            author: dict[str, Any] = (
                cast(dict[str, Any], author_raw) if isinstance(author_raw, dict) else {}
            )
            summary: dict[str, Any] = {
                "message_ref": f"message_{index}",
                "author": author.get("username", ""),
                "content": message.get("content", ""),
                "timestamp": message.get("timestamp", ""),
                "has_attachments": bool(message.get("attachments")),
            }
            if include_ids:
                summary["message_id"] = message.get("id", "")
                summary["channel_id"] = resolved
            summaries.append(summary)
        return {"messages": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_message(self, *, channel_id: Any, message_id: Any) -> dict[str, Any]:
        """Return a single message.

        Both arguments tolerate the dicts returned by :meth:`list_messages`
        (with ``include_ids=True``) -- pass the message dict directly.
        """
        resolved_channel = self._resolve_channel(channel_id)
        resolved_message = self._resolve_message_id(message_id)
        return self._client.get(
            self._v(f"/channels/{resolved_channel}/messages/{resolved_message}")
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_message(
        self,
        *,
        channel_id: Any,
        content: str | None = None,
        embeds: list[dict[str, Any]] | None = None,
        components: list[dict[str, Any]] | None = None,
        message_reference: dict[str, Any] | None = None,
        tts: bool = False,
    ) -> dict[str, Any]:
        """Send a message to a channel.

        ``channel_id`` accepts a channel name (resolved against the
        :meth:`list_guild_channels` cache), a raw snowflake, or a channel
        summary dict. Returns the new Discord ``message`` resource (``id``,
        ``channel_id``, ``content``).
        """
        resolved = self._resolve_channel(channel_id)
        if not content and not embeds:
            raise ValueError("content or embeds is required")
        body: dict[str, Any] = {"tts": tts}
        if content is not None:
            body["content"] = content
        if embeds is not None:
            body["embeds"] = embeds
        if components is not None:
            body["components"] = components
        if message_reference is not None:
            body["message_reference"] = message_reference
        return self._client.post(self._v(f"/channels/{resolved}/messages"), json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def edit_message(
        self,
        *,
        channel_id: Any,
        message_id: Any,
        content: str | None = None,
        embeds: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Edit a previously-sent message.

        Both ``channel_id`` and ``message_id`` tolerate the dicts returned by
        :meth:`list_messages` (use ``include_ids=True`` when listing).
        """
        resolved_channel = self._resolve_channel(channel_id)
        resolved_message = self._resolve_message_id(message_id)
        body: dict[str, Any] = {}
        if content is not None:
            body["content"] = content
        if embeds is not None:
            body["embeds"] = embeds
        if not body:
            raise ValueError("content or embeds is required")
        return self._client.patch(
            self._v(f"/channels/{resolved_channel}/messages/{resolved_message}"), json=body
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_message(self, *, channel_id: Any, message_id: Any) -> dict[str, Any]:
        """Delete a message.

        Destructive: the message cannot be recovered. Confirm with the user
        first. Same tolerant inputs as :meth:`edit_message`.
        """
        resolved_channel = self._resolve_channel(channel_id)
        resolved_message = self._resolve_message_id(message_id)
        response = self._client.delete(
            self._v(f"/channels/{resolved_channel}/messages/{resolved_message}")
        )
        return {"message_id": resolved_message, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_reaction(
        self,
        *,
        channel_id: Any,
        message_id: Any,
        emoji: str,
    ) -> dict[str, Any]:
        """Add the bot's reaction to a message.

        ``emoji`` is a literal Unicode emoji or ``name:id`` for a custom one.
        """
        resolved_channel = self._resolve_channel(channel_id)
        resolved_message = self._resolve_message_id(message_id)
        if not emoji:
            raise ValueError("emoji is required")
        from urllib.parse import quote

        response = self._client.put(
            self._v(
                f"/channels/{resolved_channel}/messages/{resolved_message}/reactions/"
                f"{quote(emoji, safe='')}/@me"
            )
        )
        return {"status": response.status, "reacted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_dm(self, recipient_id: str) -> dict[str, Any]:
        """Open or fetch a DM channel with a user.

        Returns the DM channel resource; pass ``channel.id`` to
        :meth:`create_message` to send the DM.
        """
        if not recipient_id:
            raise ValueError("recipient_id is required")
        return self._client.post(
            self._v("/users/@me/channels"),
            json={"recipient_id": recipient_id},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_guild_member_role(
        self,
        *,
        guild_id: str,
        user_id: str,
        role_id: str,
    ) -> dict[str, Any]:
        """Grant a role to a guild member."""
        if not guild_id or not user_id or not role_id:
            raise ValueError("guild_id, user_id, and role_id are required")
        response = self._client.put(
            self._v(f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}")
        )
        return {"status": response.status, "granted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def remove_guild_member(
        self,
        *,
        guild_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        """Kick a member from a guild.

        Destructive: the member is removed from the server. Confirm with the
        user before calling.
        """
        if not guild_id or not user_id:
            raise ValueError("guild_id and user_id are required")
        response = self._client.delete(self._v(f"/guilds/{guild_id}/members/{user_id}"))
        return {"user_id": user_id, "removed": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def execute_webhook(
        self,
        *,
        webhook_id: str,
        webhook_token: str,
        content: str | None = None,
        embeds: list[dict[str, Any]] | None = None,
        username: str | None = None,
        avatar_url: str | None = None,
    ) -> dict[str, Any]:
        """Execute a webhook (a common automation entrypoint).

        Returns the new message resource if the webhook returns one,
        otherwise ``{"status": <http-status>}``.
        """
        if not webhook_id or not webhook_token:
            raise ValueError("webhook_id and webhook_token are required")
        if not content and not embeds:
            raise ValueError("content or embeds is required")
        body: dict[str, Any] = {}
        if content is not None:
            body["content"] = content
        if embeds is not None:
            body["embeds"] = embeds
        if username is not None:
            body["username"] = username
        if avatar_url is not None:
            body["avatar_url"] = avatar_url
        response = self._client.post(
            self._v(f"/webhooks/{webhook_id}/{webhook_token}"),
            json=body,
        )
        try:
            return response.json()
        except ValueError:
            return {"status": response.status}

    # MARK: - Internal

    def _resolve_channel(self, channel: Any) -> str:
        """Coerce a channel name/dict into a Discord channel ID."""
        if isinstance(channel, list):
            channel_list = cast(list[Any], channel)
            if not channel_list:
                raise ValueError("channel_id must be non-empty")
            channel = channel_list[0]
        if isinstance(channel, dict):
            channel_dict = cast(dict[str, Any], channel)
            for key in ("channel_id", "id"):
                value: Any = channel_dict.get(key)
                if isinstance(value, str) and value:
                    return value
            name: Any = channel_dict.get("name")
            if isinstance(name, str) and name:
                cached = self._channel_name_cache.get(name)
                if cached:
                    return cached
                return name
            raise ValueError("channel dict must contain channel_id, id, or name")
        if isinstance(channel, str):
            if not channel:
                raise ValueError("channel_id is required")
            if channel.isdigit():
                return channel
            cached = self._channel_name_cache.get(channel.lstrip("#"))
            if cached:
                return cached
            return channel
        if isinstance(channel, int):
            return str(channel)
        raise ValueError("channel_id must be a string, dict, or list")

    @staticmethod
    def _resolve_message_id(message: Any) -> str:
        """Coerce a Discord message ID or message-summary dict into an ID."""
        if isinstance(message, dict):
            message_dict = cast(dict[str, Any], message)
            for key in ("message_id", "id"):
                value: Any = message_dict.get(key)
                if isinstance(value, str) and value:
                    return value
            raise ValueError("message dict must contain message_id or id")
        if isinstance(message, str):
            if not message:
                raise ValueError("message_id is required")
            return message
        if isinstance(message, int):
            return str(message)
        raise ValueError("message_id must be a string or message dict")
