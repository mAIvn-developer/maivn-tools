"""Google Chat API v1 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from ..google_workspace._shared import TokenSource, make_bearer_auth

_DEFAULT_LIST_LIMIT = 25
_DEFAULT_MESSAGES_LIMIT = 20


@toolset(prefix="google_chat")
class GoogleChatToolSet:
    """A connector for Google Chat (Workspace) v1.

    Args:
        token: OAuth bearer token, ``OAuth2Token``, or callable provider.
        base_url: API root.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="google_chat",
        display_name="Google Chat",
        version="0.1.0",
        description="List Google Chat spaces, send messages, and manage members.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "chat.spaces.readonly": "Read space metadata.",
            "chat.messages": "Read and send messages.",
            "chat.memberships": "Manage memberships.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developers.google.com/chat/api/reference/rest",
        homepage_url="https://workspace.google.com/products/chat/",
        tags=("collaboration", "google-workspace"),
    )

    def __init__(
        self,
        *,
        token: TokenSource,
        base_url: str = "https://chat.googleapis.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=make_bearer_auth(token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )
        # display name -> resource name (``spaces/AAAA``) cache populated by
        # ``list_spaces``/``search_spaces`` so write tools accept a friendly
        # space name.
        self._space_name_cache: dict[str, str] = {}

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Spaces

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_spaces(
        self,
        *,
        page_size: int = _DEFAULT_LIST_LIMIT,
        page_token: str | None = None,
        filter: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List spaces visible to the user.

        Best first tool to discover which spaces the bot can post to.
        Returns compact summaries by default: ``space_ref`` (stable
        ``space_1``, ``space_2``), ``display_name``, ``space_type``,
        ``threaded``. Provider resource names (``spaces/AAA``) are internal
        handles and are omitted by default; pass ``include_ids=True`` when a
        follow-up tool needs the ``space_name`` to call :meth:`get_space`,
        :meth:`send_message`, or :meth:`list_messages`.
        ``include_metadata=False`` returns the raw Google Chat response.

        ``filter`` scopes results by space type using the documented
        ``spaceType`` clause syntax, e.g. ``spaceType = "SPACE"`` or
        ``spaceType = "GROUP_CHAT" OR spaceType = "DIRECT_MESSAGE"``.
        """
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        params: dict[str, Any] = {"pageSize": page_size}
        if page_token is not None:
            params["pageToken"] = page_token
        if filter is not None:
            params["filter"] = filter
        payload: dict[str, Any] = self._client.get("/v1/spaces", params=params).json()
        if not include_metadata:
            return payload

        spaces: list[dict[str, Any]] = []
        raw_spaces: list[Any] = payload.get("spaces", []) or []
        for index, space in enumerate(raw_spaces, start=1):
            if not isinstance(space, dict):
                continue
            space_dict = cast("dict[str, Any]", space)
            display_name = space_dict.get("displayName", "")
            space_name = space_dict.get("name", "")
            if display_name and space_name:
                self._space_name_cache[display_name] = space_name
            summary: dict[str, Any] = {
                "space_ref": f"space_{index}",
                "display_name": display_name,
                "space_type": space_dict.get("spaceType", space_dict.get("type", "")),
                "threaded": space_dict.get("singleUserBotDm", False) is False
                and space_dict.get("type") != "DM",
            }
            if include_ids:
                summary["space_name"] = space_name
            spaces.append(summary)
        return {
            "spaces": spaces,
            "next_page_token": payload.get("nextPageToken"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_space(self, name: Any) -> dict[str, Any]:
        """Return one space by resource name (e.g. ``spaces/AAAA``).

        Accepts a raw resource name, a friendly display name (resolved
        against the :meth:`list_spaces` cache), or a space-summary dict from
        :meth:`list_spaces`.
        """
        resolved = self._resolve_space(name)
        result: dict[str, Any] = self._client.get(f"/v1/{resolved}").json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_space(
        self,
        *,
        display_name: str,
        space_type: str = "SPACE",
        external_user_allowed: bool = False,
    ) -> dict[str, Any]:
        """Create a named space.

        Returns the new space resource (with its ``name`` like
        ``spaces/AAA``). The display name is cached so subsequent calls can
        reference the space by name.
        """
        if not display_name:
            raise ValueError("display_name must be a non-empty string")
        if space_type not in {"SPACE", "GROUP_CHAT", "DIRECT_MESSAGE"}:
            raise ValueError("space_type must be SPACE/GROUP_CHAT/DIRECT_MESSAGE")
        body = {
            "displayName": display_name,
            "spaceType": space_type,
            "externalUserAllowed": external_user_allowed,
        }
        result: Any = self._client.post("/v1/spaces", json=body).json()
        if isinstance(result, dict):
            result_dict: dict[str, Any] = cast("dict[str, Any]", result)
            space_name = result_dict.get("name")
            if isinstance(space_name, str) and space_name:
                self._space_name_cache[display_name] = space_name
        return cast("dict[str, Any]", result)

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_space(self, name: Any) -> dict[str, Any]:
        """Delete a space.

        Destructive: the space and its message history are removed. Confirm
        with the user first.
        """
        resolved = self._resolve_space(name)
        self._client.delete(f"/v1/{resolved}")
        return {"name": resolved, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_spaces(
        self,
        query: str | None = None,
        *,
        space_type: str = "SPACE",
        customer: str = "customers/my_customer",
        page_size: int = _DEFAULT_LIST_LIMIT,
        page_token: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search spaces across a Workspace organization (admin only).

        Google Chat's ``spaces:search`` is a domain-admin endpoint: it
        always runs with ``useAdminAccess=true`` and requires user
        authentication with administrator privileges and the
        ``chat.admin.spaces`` (or ``chat.admin.spaces.readonly``) scope. It
        is NOT a free-text display-name search; the request must carry a
        structured ``query`` filter that includes a ``customer`` clause
        (only ``customers/my_customer`` is supported) and a ``spaceType``
        clause (currently only ``SPACE`` is valid).

        Pass a fully-formed structured ``query`` to use it verbatim, or
        leave ``query`` unset and let ``customer`` / ``space_type`` build the
        required ``customer = "..." AND spaceType = "..."`` filter. For
        ordinary (non-admin) callers, use :meth:`list_spaces` with its
        ``filter`` param instead.

        Same summary shape as :meth:`list_spaces`. Pass ``include_ids=True``
        to receive resource names for follow-up tools.
        """
        if query is not None and not query:
            raise ValueError("query must be a non-empty string when provided")
        if query is None:
            query = f'customer = "{customer}" AND spaceType = "{space_type}"'
        params: dict[str, Any] = {
            "useAdminAccess": True,
            "query": query,
            "pageSize": page_size,
        }
        if page_token is not None:
            params["pageToken"] = page_token
        payload: dict[str, Any] = self._client.get("/v1/spaces:search", params=params).json()
        if not include_metadata:
            return payload

        spaces: list[dict[str, Any]] = []
        raw_spaces: list[Any] = payload.get("spaces", []) or []
        for index, space in enumerate(raw_spaces, start=1):
            if not isinstance(space, dict):
                continue
            space_dict = cast("dict[str, Any]", space)
            display_name = space_dict.get("displayName", "")
            space_name = space_dict.get("name", "")
            if display_name and space_name:
                self._space_name_cache[display_name] = space_name
            summary: dict[str, Any] = {
                "space_ref": f"space_{index}",
                "display_name": display_name,
                "space_type": space_dict.get("spaceType", space_dict.get("type", "")),
            }
            if include_ids:
                summary["space_name"] = space_name
            spaces.append(summary)
        return {
            "spaces": spaces,
            "next_page_token": payload.get("nextPageToken"),
        }

    # MARK: - Messages

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_messages(
        self,
        space: Any,
        *,
        page_size: int = _DEFAULT_MESSAGES_LIMIT,
        page_token: str | None = None,
        filter: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List messages in a space.

        Best first tool to read recent activity. ``space`` accepts a space
        display name, a raw resource name (``spaces/AAA``), or a
        space-summary dict from :meth:`list_spaces`. Returns compact
        summaries by default: ``message_ref``, ``sender``, ``text_preview``,
        ``created_at``. Provider resource names are omitted by default; pass
        ``include_ids=True`` for the ``message_name`` follow-up tools need.
        """
        resolved = self._resolve_space(space)
        params: dict[str, Any] = {"pageSize": page_size}
        if page_token is not None:
            params["pageToken"] = page_token
        if filter is not None:
            params["filter"] = filter
        payload: dict[str, Any] = self._client.get(f"/v1/{resolved}/messages", params=params).json()
        if not include_metadata:
            return payload

        summaries: list[dict[str, Any]] = []
        raw_messages: list[Any] = payload.get("messages", []) or []
        for index, message in enumerate(raw_messages, start=1):
            if not isinstance(message, dict):
                continue
            message_dict = cast("dict[str, Any]", message)
            text = str(message_dict.get("text", "") or "")
            preview = text.strip()
            if len(preview) > 200:
                preview = preview[:197] + "..."
            sender_obj: Any = message_dict.get("sender") or {}
            sender = ""
            if isinstance(sender_obj, dict):
                sender_dict = cast("dict[str, Any]", sender_obj)
                sender = sender_dict.get("displayName", "")
            summary: dict[str, Any] = {
                "message_ref": f"message_{index}",
                "sender": sender,
                "text_preview": preview,
                "created_at": message_dict.get("createTime", ""),
            }
            if include_ids:
                summary["message_name"] = message_dict.get("name", "")
            summaries.append(summary)
        return {
            "messages": summaries,
            "next_page_token": payload.get("nextPageToken"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_message(self, name: Any) -> dict[str, Any]:
        """Return one message by resource name.

        Accepts a raw resource name (``spaces/AAA/messages/m1``) or a
        message-summary dict from :meth:`list_messages` (with
        ``include_ids=True``).
        """
        resolved = self._resolve_message(name)
        result: dict[str, Any] = self._client.get(f"/v1/{resolved}").json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def send_message(
        self,
        space: Any,
        *,
        text: str | None = None,
        cards: list[dict[str, Any]] | None = None,
        thread_key: str | None = None,
        message_id: str | None = None,
        message_reply_option: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Post a new message to a space.

        ``space`` accepts a display name, raw resource name, or
        space-summary dict. Returns the new message resource with the
        provider ``name`` field (use it with :meth:`update_message` /
        :meth:`delete_message`).

        When ``thread_key`` is set, pass ``message_reply_option`` to control
        threading behaviour (e.g. ``REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD`` or
        ``REPLY_MESSAGE_OR_FAIL``); without it the message may start a new
        thread rather than reply. ``request_id`` is an optional idempotency
        key so retries do not create duplicate messages.
        """
        resolved = self._resolve_space(space)
        if text is None and cards is None:
            raise ValueError("text or cards must be provided")
        body: dict[str, Any] = {}
        if text is not None:
            body["text"] = text
        if cards is not None:
            body["cardsV2"] = cards
        if thread_key is not None:
            body["thread"] = {"threadKey": thread_key}
        params: dict[str, Any] = {}
        if message_id is not None:
            params["messageId"] = message_id
        if message_reply_option is not None:
            params["messageReplyOption"] = message_reply_option
        if request_id is not None:
            params["requestId"] = request_id
        result: dict[str, Any] = self._client.post(
            f"/v1/{resolved}/messages",
            params=params or None,
            json=body,
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_message(
        self,
        name: Any,
        *,
        text: str | None = None,
        cards: list[dict[str, Any]] | None = None,
        update_mask: str = "text",
    ) -> dict[str, Any]:
        """Patch a message body.

        ``name`` accepts a raw resource name or a message-summary dict from
        :meth:`list_messages`.
        """
        resolved = self._resolve_message(name)
        body: dict[str, Any] = {}
        if text is not None:
            body["text"] = text
        if cards is not None:
            body["cardsV2"] = cards
        result: dict[str, Any] = self._client.patch(
            f"/v1/{resolved}",
            params={"updateMask": update_mask},
            json=body,
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_message(self, name: Any) -> dict[str, Any]:
        """Delete a message.

        Destructive: the message is removed and cannot be recovered. Accepts
        the same tolerant input as :meth:`update_message`.
        """
        resolved = self._resolve_message(name)
        self._client.delete(f"/v1/{resolved}")
        return {"name": resolved, "deleted": True}

    # MARK: - Members

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_members(
        self,
        space: Any,
        *,
        page_size: int = _DEFAULT_LIST_LIMIT,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List members of a space."""
        resolved = self._resolve_space(space)
        params: dict[str, Any] = {"pageSize": page_size}
        if page_token is not None:
            params["pageToken"] = page_token
        result: dict[str, Any] = self._client.get(f"/v1/{resolved}/members", params=params).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_member(
        self,
        space: Any,
        *,
        user_name: str,
        role: str = "ROLE_MEMBER",
    ) -> dict[str, Any]:
        """Add a member to a space."""
        resolved = self._resolve_space(space)
        if not user_name:
            raise ValueError("user_name must be non-empty")
        body: dict[str, Any] = {
            "member": {"name": user_name, "type": "HUMAN"},
            "role": role,
        }
        result: dict[str, Any] = self._client.post(f"/v1/{resolved}/members", json=body).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def remove_member(self, name: str) -> dict[str, Any]:
        """Remove a member by resource name.

        Destructive: the user loses access to the space.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        self._client.delete(f"/v1/{name}")
        return {"name": name, "removed": True}

    # MARK: - Reactions

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_reaction(self, message: Any, *, emoji: str) -> dict[str, Any]:
        """Add an emoji reaction to a message.

        ``message`` tolerates the dict returned by :meth:`list_messages`.
        """
        resolved = self._resolve_message(message)
        if not emoji:
            raise ValueError("emoji must be non-empty")
        body: dict[str, Any] = {"emoji": {"unicode": emoji}}
        result: dict[str, Any] = self._client.post(f"/v1/{resolved}/reactions", json=body).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_reaction(self, name: str) -> dict[str, Any]:
        """Remove a reaction by resource name.

        Destructive: the reaction is removed and cannot be recovered.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        self._client.delete(f"/v1/{name}")
        return {"name": name, "removed": True}

    # MARK: - Internal

    def _resolve_space(self, space: Any) -> str:
        if isinstance(space, list):
            space_list = cast("list[Any]", space)
            if not space_list:
                raise ValueError("space must be non-empty")
            space = space_list[0]
        if isinstance(space, dict):
            space_dict = cast("dict[str, Any]", space)
            for key in ("space_name", "name"):
                value = space_dict.get(key)
                if isinstance(value, str) and value.startswith("spaces/"):
                    return value
            display_name = space_dict.get("display_name") or space_dict.get("displayName")
            if isinstance(display_name, str) and display_name:
                cached = self._space_name_cache.get(display_name)
                if cached:
                    return cached
            raise ValueError("space dict must contain space_name, name, or display_name")
        if isinstance(space, str):
            if not space:
                raise ValueError("space must be a non-empty string")
            if space.startswith("spaces/"):
                return space
            cached = self._space_name_cache.get(space)
            if cached:
                return cached
            return space
        raise ValueError("space must be a string, dict, or list")

    @staticmethod
    def _resolve_message(message: Any) -> str:
        if isinstance(message, dict):
            message_dict = cast("dict[str, Any]", message)
            for key in ("message_name", "name"):
                value = message_dict.get(key)
                if isinstance(value, str) and value:
                    return value
            raise ValueError("message dict must contain message_name or name")
        if isinstance(message, str):
            if not message:
                raise ValueError("message name must be non-empty")
            return message
        raise ValueError("message must be a string or message dict")
