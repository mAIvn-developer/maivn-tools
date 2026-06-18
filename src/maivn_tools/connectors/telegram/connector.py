"""Telegram Bot API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.base import NoAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import GET_UPDATES_OUTPUT

# MARK: - Constants

_DEFAULT_UPDATES_LIMIT = 25


# MARK: - Helpers


def _as_str_dict(value: object) -> dict[str, Any] | None:
    """Return ``value`` as a ``dict[str, Any]`` when it is a dict, else ``None``.

    Narrows untyped JSON payload fragments (``Any``/``object``) into a typed
    mapping without widening to ``dict[Unknown, Unknown]``.
    """
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)
    return None


# MARK: - ToolSet


@toolset(prefix="telegram")
class TelegramToolSet:
    """A connector for the Telegram Bot API.

    Args:
        bot_token: Bot token from BotFather (``"123456:ABC-..."``).
        base_url: API root. The default is ``https://api.telegram.org``.

    The token is embedded in the request path (``/bot<TOKEN>/...``), as
    required by the Telegram Bot API. No header-based auth is used.
    """

    metadata = ProviderMetadata(
        name="telegram",
        display_name="Telegram",
        version="0.1.0",
        description="Bot identity, messages, chats, callbacks, and webhooks.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://core.telegram.org/bots/api",
        homepage_url="https://telegram.org/",
        tags=("social-media", "chat", "bot"),
    )

    def __init__(
        self,
        *,
        bot_token: str,
        base_url: str = "https://api.telegram.org",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not bot_token:
            raise ValueError("bot_token is required")
        self.connection = connection
        self._token = bot_token
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=NoAuth(),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _method(self, method: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._client.post(f"/bot{self._token}/{method}", json=body or {}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_me(self) -> dict[str, Any]:
        """Return the bot's identity (``getMe``).

        Best first call at startup to verify the bot token works and to
        discover the bot's username and ID.
        """
        return self._method("getMe")

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(GET_UPDATES_OUTPUT)
    def get_updates(
        self,
        *,
        offset: int | None = None,
        limit: int = _DEFAULT_UPDATES_LIMIT,
        timeout: int = 0,
        allowed_updates: list[str] | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Long-poll for updates.

        Best first tool to discover recent activity (incoming messages,
        callbacks). By default returns compact summaries with
        ``update_ref``, ``type`` (``message`` / ``callback_query`` / etc.),
        ``chat_title``, ``sender``, ``text``. Telegram update_id / message_id
        integers are omitted by default; pass ``include_ids=True`` when a
        follow-up tool needs them. Set ``include_metadata=False`` for the raw
        Telegram response.
        """
        body: dict[str, Any] = {"limit": limit, "timeout": timeout}
        if offset is not None:
            body["offset"] = offset
        if allowed_updates is not None:
            body["allowed_updates"] = allowed_updates
        payload = self._method("getUpdates", body)
        if not include_metadata:
            return payload

        results: object = payload.get("result")
        result_items: list[object] = cast(
            "list[object]", results if isinstance(results, list) else []
        )
        updates: list[dict[str, Any]] = []
        for index, update in enumerate(result_items, start=1):
            update_dict = _as_str_dict(update)
            if update_dict is None:
                continue
            updates.append(self._update_summary(update_dict, index=index, include_ids=include_ids))
        return {"ok": bool(payload.get("ok", True)), "updates": updates}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def send_message(
        self,
        *,
        chat_id: Any,
        text: str,
        parse_mode: str | None = None,
        reply_to_message_id: Any | None = None,
        disable_notification: bool = False,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a text message to a chat.

        ``chat_id`` accepts a Telegram chat ID (int or string like
        ``"@channelname"``) or a chat-summary dict / update dict returned by
        :meth:`get_updates` (with ``include_ids=True``).
        ``reply_to_message_id`` similarly tolerates a message-summary dict.
        """
        resolved_chat = self._resolve_chat_id(chat_id)
        if text == "":
            raise ValueError("text is required")
        body: dict[str, Any] = {
            "chat_id": resolved_chat,
            "text": text,
            "disable_notification": disable_notification,
        }
        if parse_mode is not None:
            body["parse_mode"] = parse_mode
        if reply_to_message_id is not None:
            body["reply_to_message_id"] = self._resolve_message_id(reply_to_message_id)
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        return self._method("sendMessage", body)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def edit_message_text(
        self,
        *,
        chat_id: Any,
        message_id: Any,
        text: str,
        parse_mode: str | None = None,
    ) -> dict[str, Any]:
        """Edit a previously-sent message.

        ``chat_id`` and ``message_id`` tolerate the dicts returned by
        :meth:`get_updates`.
        """
        resolved_chat = self._resolve_chat_id(chat_id)
        resolved_message = self._resolve_message_id(message_id)
        if not text:
            raise ValueError("text is required")
        body: dict[str, Any] = {
            "chat_id": resolved_chat,
            "message_id": resolved_message,
            "text": text,
        }
        if parse_mode is not None:
            body["parse_mode"] = parse_mode
        return self._method("editMessageText", body)

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_message(self, *, chat_id: Any, message_id: Any) -> dict[str, Any]:
        """Delete a previously-sent message.

        Destructive: the message is removed for everyone in the chat.
        ``chat_id`` and ``message_id`` tolerate update/message dicts from
        :meth:`get_updates`.
        """
        resolved_chat = self._resolve_chat_id(chat_id)
        resolved_message = self._resolve_message_id(message_id)
        return self._method(
            "deleteMessage", {"chat_id": resolved_chat, "message_id": resolved_message}
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def send_photo(
        self,
        *,
        chat_id: Any,
        photo: str,
        caption: str | None = None,
        parse_mode: str | None = None,
    ) -> dict[str, Any]:
        """Send a photo (URL or file ID)."""
        resolved_chat = self._resolve_chat_id(chat_id)
        if not photo:
            raise ValueError("photo is required")
        body: dict[str, Any] = {"chat_id": resolved_chat, "photo": photo}
        if caption is not None:
            body["caption"] = caption
        if parse_mode is not None:
            body["parse_mode"] = parse_mode
        return self._method("sendPhoto", body)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> dict[str, Any]:
        """Reply to a callback query.

        ``callback_query_id`` is obtained from the ``callback_query`` field
        of an update returned by :meth:`get_updates` (with
        ``include_ids=True``).
        """
        if not callback_query_id:
            raise ValueError("callback_query_id is required")
        body: dict[str, Any] = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }
        if text is not None:
            body["text"] = text
        return self._method("answerCallbackQuery", body)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_chat(self, chat_id: Any) -> dict[str, Any]:
        """Return chat metadata.

        Accepts a Telegram chat ID or a chat-summary dict from
        :meth:`get_updates`.
        """
        resolved = self._resolve_chat_id(chat_id)
        return self._method("getChat", {"chat_id": resolved})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_chat_member(
        self,
        *,
        chat_id: Any,
        user_id: int,
    ) -> dict[str, Any]:
        """Return a chat member's status."""
        resolved_chat = self._resolve_chat_id(chat_id)
        if not user_id:
            raise ValueError("user_id is required")
        return self._method("getChatMember", {"chat_id": resolved_chat, "user_id": user_id})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def set_webhook(
        self,
        *,
        url: str,
        secret_token: str | None = None,
        allowed_updates: list[str] | None = None,
        drop_pending_updates: bool = False,
    ) -> dict[str, Any]:
        """Set a webhook for receiving updates."""
        if not url:
            raise ValueError("url is required")
        body: dict[str, Any] = {
            "url": url,
            "drop_pending_updates": drop_pending_updates,
        }
        if secret_token is not None:
            body["secret_token"] = secret_token
        if allowed_updates is not None:
            body["allowed_updates"] = allowed_updates
        return self._method("setWebhook", body)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def delete_webhook(self, *, drop_pending_updates: bool = False) -> dict[str, Any]:
        """Remove the bot's webhook."""
        return self._method("deleteWebhook", {"drop_pending_updates": drop_pending_updates})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_webhook_info(self) -> dict[str, Any]:
        """Return the current webhook configuration."""
        return self._method("getWebhookInfo")

    # MARK: - Internal

    @staticmethod
    def _resolve_chat_id(chat: Any) -> str | int:
        chat_dict = _as_str_dict(chat)
        if chat_dict is not None:
            for key in ("chat_id", "id"):
                value: object = chat_dict.get(key)
                if isinstance(value, str | int) and value != "":
                    return value
            inner_chat = _as_str_dict(chat_dict.get("chat"))
            if inner_chat is not None:
                inner: object = inner_chat.get("id")
                if isinstance(inner, str | int) and inner != "":
                    return inner
            message = _as_str_dict(chat_dict.get("message"))
            if message is not None:
                message_chat = _as_str_dict(message.get("chat"))
                nested_id: object = message_chat.get("id") if message_chat is not None else None
                if isinstance(nested_id, str | int) and nested_id != "":
                    return nested_id
            raise ValueError("chat dict must contain chat_id, id, or chat.id")
        if isinstance(chat, str):
            if chat == "":
                raise ValueError("chat_id is required")
            return chat
        if isinstance(chat, int):
            return chat
        raise ValueError("chat_id must be a string, int, or dict")

    @staticmethod
    def _resolve_message_id(message: Any) -> int:
        message_dict = _as_str_dict(message)
        if message_dict is not None:
            for key in ("message_id", "id"):
                value: object = message_dict.get(key)
                if isinstance(value, int) and value:
                    return value
            inner = _as_str_dict(message_dict.get("message"))
            if inner is not None:
                inner_value: object = inner.get("message_id")
                if isinstance(inner_value, int) and inner_value:
                    return inner_value
            raise ValueError("message dict must contain message_id")
        if isinstance(message, int):
            if not message:
                raise ValueError("message_id is required")
            return message
        if isinstance(message, str):
            if not message:
                raise ValueError("message_id is required")
            return int(message)
        raise ValueError("message_id must be an int or message dict")

    @staticmethod
    def _update_summary(
        update: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        kind: str
        raw_inner: object
        if "message" in update:
            kind = "message"
            raw_inner = update.get("message") or {}
        elif "edited_message" in update:
            kind = "edited_message"
            raw_inner = update.get("edited_message") or {}
        elif "channel_post" in update:
            kind = "channel_post"
            raw_inner = update.get("channel_post") or {}
        elif "callback_query" in update:
            kind = "callback_query"
            raw_inner = update.get("callback_query") or {}
        else:
            kind = "other"
            raw_inner = {}
        inner: dict[str, Any] = _as_str_dict(raw_inner) or {}
        chat: dict[str, Any] = _as_str_dict(inner.get("chat")) or {}
        sender: dict[str, Any] = _as_str_dict(inner.get("from")) or {}
        text: object = inner.get("text") or inner.get("data") or ""
        summary: dict[str, Any] = {
            "update_ref": f"update_{index}",
            "type": kind,
            "chat_title": chat.get("title") or chat.get("username") or "",
            "sender": sender.get("username") or sender.get("first_name") or "",
            "text": text,
        }
        if include_ids:
            summary["update_id"] = update.get("update_id")
            if "message_id" in inner:
                summary["message_id"] = inner.get("message_id")
            if "id" in inner:
                summary["callback_query_id"] = inner.get("id")
            if chat:
                summary["chat_id"] = chat.get("id")
        return summary
