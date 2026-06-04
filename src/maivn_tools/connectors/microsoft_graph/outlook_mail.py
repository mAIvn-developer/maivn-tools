"""Outlook Mail connector backed by Microsoft Graph v1.0."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpTransport
from ._shared import GRAPH_API_URL, TokenSource, make_graph_client

_DEFAULT_MESSAGE_SELECT = "id,subject,from,toRecipients,receivedDateTime,bodyPreview,isRead"
_DEFAULT_FOLDER_LIST_TOP = 25
_DEFAULT_MESSAGE_LIST_TOP = 25


@toolset(prefix="outlook_mail")
class OutlookMailToolSet:
    """A connector for Outlook / Microsoft 365 mail via Microsoft Graph.

    Args:
        token: OAuth bearer credential. Accepts an :class:`OAuth2Token`, a
            callable returning one, or a raw access-token string.
        user: User principal name or ``"me"`` for the authenticated user.
        transport: Optional :class:`HttpTransport` override.
        base_url: Override for tests or for self-hosted mirrors.
    """

    metadata = ProviderMetadata(
        name="outlook_mail",
        display_name="Outlook Mail",
        version="0.1.0",
        description="Read, search, send, and label Outlook / Microsoft 365 messages.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "Mail.Read": "Read mail.",
            "Mail.Send": "Send mail.",
            "Mail.ReadWrite": "Read, modify, and move mail.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://learn.microsoft.com/graph/api/resources/mail-api-overview",
        homepage_url="https://outlook.live.com",
        tags=("email", "microsoft"),
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
    def list_folders(
        self,
        *,
        top: int = _DEFAULT_FOLDER_LIST_TOP,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List mail folders for the authenticated user.

        Returns compact summaries: each folder gets a stable ``folder_ref``
        (``folder_1``, ``folder_2``, ...), ``display_name``,
        ``total_item_count``, and ``unread_item_count``. Raw Graph folder
        IDs are omitted by default; set ``include_ids=True`` only when a
        follow-up tool such as :meth:`list_messages_in_folder` or
        :meth:`move_message` needs the raw ID.
        """
        if top < 1 or top > 1000:
            raise ValueError("top must be between 1 and 1000")
        payload: dict[str, Any] = self._client.get(
            self._user_path("/mailFolders"),
            params={"$top": top},
        ).json()
        folders: list[dict[str, Any]] = []
        raw_value: Any = payload.get("value", [])
        raw_folders: list[Any] = cast(list[Any], raw_value) if isinstance(raw_value, list) else []
        for index, folder in enumerate(raw_folders, start=1):
            if not isinstance(folder, dict):
                continue
            folder_dict: dict[str, Any] = cast(dict[str, Any], folder)
            summary: dict[str, Any] = {
                "folder_ref": f"folder_{index}",
                "display_name": folder_dict.get("displayName", ""),
                "total_item_count": folder_dict.get("totalItemCount", 0),
                "unread_item_count": folder_dict.get("unreadItemCount", 0),
            }
            if include_ids:
                summary["folder_id"] = folder_dict.get("id", "")
                summary["parent_folder_id"] = folder_dict.get("parentFolderId", "")
            folders.append(summary)
        return {
            "folders": folders,
            "nextLink": payload.get("@odata.nextLink"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_messages(
        self,
        *,
        search: str | None = None,
        filter: str | None = None,
        top: int = _DEFAULT_MESSAGE_LIST_TOP,
        select: str | None = _DEFAULT_MESSAGE_SELECT,
        order_by: str | None = "receivedDateTime desc",
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search messages with Graph ``$search`` or ``$filter``.

        Best first tool for Outlook inbox triage. By default it returns
        compact human-readable summaries: ``message_ref``, sender, subject,
        ``received_at``, ``preview``, and ``is_read``. Raw Graph message
        IDs are omitted by default because they are internal handles. Set
        ``include_ids=True`` only when a follow-up tool such as
        :meth:`get_message`, :meth:`reply_to_message`, :meth:`move_message`,
        or :meth:`delete_message` needs the raw ``message_id``. Set
        ``include_metadata=False`` to receive the raw Graph response with
        every field present.
        """
        if top < 1 or top > 1000:
            raise ValueError("top must be between 1 and 1000")
        params: dict[str, Any] = {"$top": top}
        if search is not None:
            params["$search"] = f'"{search}"' if not search.startswith('"') else search
        if filter is not None:
            params["$filter"] = filter
        if select is not None:
            params["$select"] = select
        if order_by is not None and search is None:
            # $orderby cannot combine with $search in Graph.
            params["$orderby"] = order_by
        payload: dict[str, Any] = self._client.get(
            self._user_path("/messages"), params=params
        ).json()
        if not include_metadata:
            return payload
        return self._summarize_message_list(payload, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_message(self, message_id: Any) -> dict[str, Any]:
        """Fetch a single message by ID.

        Use this after :meth:`search_messages` (with ``include_ids=True``)
        or :meth:`list_messages_in_folder` to read the full body of one
        message. ``message_id`` accepts a raw Graph ID string or a message
        dict from a list response (the ``message_id`` field is extracted
        automatically).
        """
        resolved = _extract_message_id(message_id)
        return self._client.get(self._user_path(f"/messages/{resolved}")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def send_email(
        self,
        to: list[str],
        subject: str,
        body_text: str | None = None,
        *,
        body_html: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        save_to_sent: bool = True,
    ) -> dict[str, Any]:
        """Send an email through Graph ``sendMail``.

        Returns ``{"sent": True, "status": <http status>}``. Always
        confirm the recipient list with the user before calling this in
        an interactive agent loop.
        """
        if not to:
            raise ValueError("to must contain at least one recipient")
        if body_text is None and body_html is None:
            raise ValueError("body_text or body_html must be supplied")
        body: dict[str, Any]
        if body_html is not None:
            body = {"contentType": "HTML", "content": body_html}
        else:
            body = {"contentType": "Text", "content": body_text or ""}
        payload: dict[str, Any] = {
            "message": {
                "subject": subject,
                "body": body,
                "toRecipients": _addresses(to),
            },
            "saveToSentItems": save_to_sent,
        }
        if cc:
            payload["message"]["ccRecipients"] = _addresses(cc)
        if bcc:
            payload["message"]["bccRecipients"] = _addresses(bcc)
        response = self._client.post(self._user_path("/sendMail"), json=payload)
        return {"sent": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def move_message(self, message_id: Any, destination_folder_id: Any) -> dict[str, Any]:
        """Move a message to another folder.

        Both ``message_id`` and ``destination_folder_id`` accept a raw ID
        string or a dict returned by :meth:`search_messages` /
        :meth:`list_folders` (with ``include_ids=True``); the IDs are
        extracted automatically.
        """
        resolved_message = _extract_message_id(message_id)
        resolved_folder = _extract_folder_id(destination_folder_id)
        return self._client.post(
            self._user_path(f"/messages/{resolved_message}/move"),
            json={"destinationId": resolved_folder},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_message(self, message_id: Any) -> dict[str, Any]:
        """Delete a message. Outlook places deletes in Deleted Items.

        Returns ``{"deleted": True, "status": <http status>}``. Destructive
        — confirm with the user first. ``message_id`` accepts a raw ID
        string or a message dict from a list response.
        """
        resolved = _extract_message_id(message_id)
        response = self._client.delete(self._user_path(f"/messages/{resolved}"))
        return {"deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def copy_message(self, message_id: Any, destination_folder_id: Any) -> dict[str, Any]:
        """Copy a message to another folder.

        Both arguments accept raw ID strings or dicts from list responses.
        """
        resolved_message = _extract_message_id(message_id)
        resolved_folder = _extract_folder_id(destination_folder_id)
        return self._client.post(
            self._user_path(f"/messages/{resolved_message}/copy"),
            json={"destinationId": resolved_folder},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_message(self, message_id: Any, patch: dict[str, Any]) -> dict[str, Any]:
        """Patch message fields (e.g. ``isRead``, ``flag``, ``categories``).

        ``message_id`` accepts a raw ID string or a message dict. Returns
        the updated message resource.
        """
        if not patch:
            raise ValueError("patch must contain at least one field")
        resolved = _extract_message_id(message_id)
        return self._client.patch(
            self._user_path(f"/messages/{resolved}"),
            json=patch,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def mark_read(self, message_id: Any, *, is_read: bool = True) -> dict[str, Any]:
        """Mark a message as read (or unread when ``is_read=False``).

        ``message_id`` accepts a raw ID string or a message dict.
        """
        return self.update_message(message_id, {"isRead": is_read})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def flag_message(
        self,
        message_id: Any,
        flag_status: str = "flagged",
    ) -> dict[str, Any]:
        """Set the follow-up flag on a message.

        ``flag_status`` must be one of ``notFlagged``, ``flagged``, or
        ``complete``. ``message_id`` accepts a raw ID string or a message
        dict.
        """
        if flag_status not in {"notFlagged", "flagged", "complete"}:
            raise ValueError("flag_status must be notFlagged, flagged, or complete")
        return self.update_message(message_id, {"flag": {"flagStatus": flag_status}})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def reply_to_message(
        self,
        message_id: Any,
        comment: str,
        *,
        reply_all: bool = False,
    ) -> dict[str, Any]:
        """Reply (or reply-all) to a message with ``comment``.

        ``message_id`` accepts a raw ID string or a message dict from a
        list response. Always confirm the response text with the user
        before sending.
        """
        resolved = _extract_message_id(message_id)
        suffix = "/replyAll" if reply_all else "/reply"
        response = self._client.post(
            self._user_path(f"/messages/{resolved}{suffix}"),
            json={"comment": comment},
        )
        return {"replied": True, "reply_all": reply_all, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def forward_message(
        self,
        message_id: Any,
        to: list[str],
        comment: str = "",
    ) -> dict[str, Any]:
        """Forward a message to ``to`` with optional ``comment``.

        ``message_id`` accepts a raw ID string or a message dict.
        """
        if not to:
            raise ValueError("to must contain at least one recipient")
        resolved = _extract_message_id(message_id)
        payload: dict[str, Any] = {
            "comment": comment,
            "toRecipients": _addresses(to),
        }
        response = self._client.post(
            self._user_path(f"/messages/{resolved}/forward"),
            json=payload,
        )
        return {"forwarded": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_attachments(self, message_id: Any) -> dict[str, Any]:
        """List attachments on a message.

        ``message_id`` accepts a raw ID string or a message dict.
        """
        resolved = _extract_message_id(message_id)
        return self._client.get(self._user_path(f"/messages/{resolved}/attachments")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_attachment(self, message_id: Any, attachment_id: str) -> dict[str, Any]:
        """Return a single attachment by ID (includes base64 content).

        ``message_id`` accepts a raw ID string or a message dict.
        ``attachment_id`` is the Graph attachment ID from
        :meth:`list_attachments`.
        """
        if not attachment_id:
            raise ValueError("attachment_id must be non-empty")
        resolved = _extract_message_id(message_id)
        return self._client.get(
            self._user_path(f"/messages/{resolved}/attachments/{attachment_id}")
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_attachment(
        self,
        message_id: Any,
        *,
        name: str,
        content_base64: str,
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        """Attach a file (base64) to an existing draft message.

        ``message_id`` accepts a raw ID string or a draft dict from
        :meth:`create_draft`.
        """
        if not name or not content_base64:
            raise ValueError("name and content_base64 must be non-empty")
        resolved = _extract_message_id(message_id)
        payload = {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": name,
            "contentType": content_type,
            "contentBytes": content_base64,
        }
        return self._client.post(
            self._user_path(f"/messages/{resolved}/attachments"),
            json=payload,
        ).json()

    # MARK: - Drafts

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_draft(
        self,
        to: list[str],
        subject: str,
        body_text: str | None = None,
        *,
        body_html: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a draft message (returns id usable for ``send_draft``).

        Returns the new draft resource (with its Graph ``id``). Use
        :meth:`send_draft` to send it later.
        """
        if not to:
            raise ValueError("to must contain at least one recipient")
        if body_text is None and body_html is None:
            raise ValueError("body_text or body_html must be supplied")
        body: dict[str, Any]
        if body_html is not None:
            body = {"contentType": "HTML", "content": body_html}
        else:
            body = {"contentType": "Text", "content": body_text or ""}
        payload: dict[str, Any] = {
            "subject": subject,
            "body": body,
            "toRecipients": _addresses(to),
        }
        if cc:
            payload["ccRecipients"] = _addresses(cc)
        if bcc:
            payload["bccRecipients"] = _addresses(bcc)
        return self._client.post(self._user_path("/messages"), json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def send_draft(self, message_id: Any) -> dict[str, Any]:
        """Send a draft created via ``create_draft``.

        ``message_id`` accepts a raw ID string or the draft dict returned
        by :meth:`create_draft`.
        """
        resolved = _extract_message_id(message_id)
        response = self._client.post(self._user_path(f"/messages/{resolved}/send"))
        return {"sent": True, "status": response.status}

    # MARK: - Folders

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_folder(self, folder_id: Any) -> dict[str, Any]:
        """Return a single mail folder by ID.

        ``folder_id`` accepts a raw ID string or a folder dict from
        :meth:`list_folders` (with ``include_ids=True``).
        """
        resolved = _extract_folder_id(folder_id)
        return self._client.get(self._user_path(f"/mailFolders/{resolved}")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_messages_in_folder(
        self,
        folder_id: Any,
        *,
        top: int = _DEFAULT_MESSAGE_LIST_TOP,
        filter: str | None = None,
        select: str | None = _DEFAULT_MESSAGE_SELECT,
        order_by: str | None = "receivedDateTime desc",
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List messages within a specific mail folder.

        Returns compact summaries (``message_ref``, sender, subject,
        ``received_at``, ``preview``, ``is_read``) by default. Raw Graph
        IDs are omitted unless ``include_ids=True``. Set
        ``include_metadata=False`` for the raw Graph response.
        ``folder_id`` accepts a raw ID string or a folder dict from
        :meth:`list_folders`. Well-known folder names like ``inbox`` and
        ``drafts`` are also accepted.
        """
        if top < 1 or top > 1000:
            raise ValueError("top must be between 1 and 1000")
        resolved = _extract_folder_id(folder_id)
        params: dict[str, Any] = {"$top": top}
        if filter is not None:
            params["$filter"] = filter
        if select is not None:
            params["$select"] = select
        if order_by is not None:
            params["$orderby"] = order_by
        payload: dict[str, Any] = self._client.get(
            self._user_path(f"/mailFolders/{resolved}/messages"),
            params=params,
        ).json()
        if not include_metadata:
            return payload
        return self._summarize_message_list(payload, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_folder(
        self,
        display_name: str,
        *,
        parent_folder_id: Any | None = None,
    ) -> dict[str, Any]:
        """Create a mail folder (optionally nested under ``parent_folder_id``).

        ``parent_folder_id`` accepts a raw ID string or a folder dict
        from :meth:`list_folders`.
        """
        if not display_name:
            raise ValueError("display_name must be a non-empty string")
        suffix = "/mailFolders"
        if parent_folder_id is not None:
            resolved = _extract_folder_id(parent_folder_id)
            suffix = f"/mailFolders/{resolved}/childFolders"
        return self._client.post(
            self._user_path(suffix),
            json={"displayName": display_name},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_folder(self, folder_id: Any, patch: dict[str, Any]) -> dict[str, Any]:
        """Patch a mail folder (typically to rename it).

        ``folder_id`` accepts a raw ID string or a folder dict.
        """
        if not patch:
            raise ValueError("patch must contain at least one field")
        resolved = _extract_folder_id(folder_id)
        return self._client.patch(
            self._user_path(f"/mailFolders/{resolved}"),
            json=patch,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_folder(self, folder_id: Any) -> dict[str, Any]:
        """Delete a mail folder (and the messages it contains).

        ``folder_id`` accepts a raw ID string or a folder dict.
        Destructive — confirm with the user first.
        """
        resolved = _extract_folder_id(folder_id)
        self._client.delete(self._user_path(f"/mailFolders/{resolved}"))
        return {"id": resolved, "deleted": True}

    # MARK: - Rules & categories

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_mail_rules(
        self,
        folder_id: Any = "inbox",
    ) -> dict[str, Any]:
        """List message rules attached to ``folder_id`` (defaults to Inbox)."""
        resolved = _extract_folder_id(folder_id)
        return self._client.get(self._user_path(f"/mailFolders/{resolved}/messageRules")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_mail_rule(
        self,
        rule: dict[str, Any],
        folder_id: Any = "inbox",
    ) -> dict[str, Any]:
        """Create a message rule on a folder (commonly Inbox)."""
        if not rule:
            raise ValueError("rule must not be empty")
        resolved = _extract_folder_id(folder_id)
        return self._client.post(
            self._user_path(f"/mailFolders/{resolved}/messageRules"),
            json=rule,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_mail_rule(
        self,
        rule_id: str,
        folder_id: Any = "inbox",
    ) -> dict[str, Any]:
        """Delete a message rule.

        Destructive — confirm with the user first.
        """
        if not rule_id:
            raise ValueError("rule_id must be a non-empty string")
        resolved = _extract_folder_id(folder_id)
        self._client.delete(self._user_path(f"/mailFolders/{resolved}/messageRules/{rule_id}"))
        return {"id": rule_id, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_categories(self) -> dict[str, Any]:
        """Return the user's master category list."""
        return self._client.get(self._user_path("/outlook/masterCategories")).json()

    # MARK: - Internal

    def _user_path(self, suffix: str) -> str:
        prefix = "/me" if self._user == "me" else f"/users/{self._user}"
        return f"{prefix}{suffix}"

    @staticmethod
    def _message_summary(
        message: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        from_field: Any = message.get("from") or {}
        from_addr: Any = (
            cast(dict[str, Any], from_field).get("emailAddress")
            if isinstance(from_field, dict)
            else None
        )
        sender: str = ""
        if isinstance(from_addr, dict):
            from_addr_dict: dict[str, Any] = cast(dict[str, Any], from_addr)
            name: str = from_addr_dict.get("name") or ""
            address: str = from_addr_dict.get("address") or ""
            if name and address:
                sender = f"{name} <{address}>"
            else:
                sender = address or name
        to_recipients: Any = message.get("toRecipients") or []
        to_list: list[str] = []
        if isinstance(to_recipients, list):
            recipients_list: list[Any] = cast(list[Any], to_recipients)
            for entry in recipients_list:
                if isinstance(entry, dict):
                    entry_dict: dict[str, Any] = cast(dict[str, Any], entry)
                    email_obj: Any = entry_dict.get("emailAddress") or {}
                    if isinstance(email_obj, dict):
                        email_dict: dict[str, Any] = cast(dict[str, Any], email_obj)
                        addr: Any = email_dict.get("address")
                        if isinstance(addr, str):
                            to_list.append(addr)
        summary: dict[str, Any] = {
            "message_ref": f"message_{index}",
            "sender": sender,
            "to": to_list,
            "subject": message.get("subject", ""),
            "received_at": message.get("receivedDateTime", ""),
            "preview": message.get("bodyPreview", ""),
            "is_read": message.get("isRead", False),
        }
        if include_ids:
            summary["message_id"] = message.get("id", "")
            conversation_id = message.get("conversationId")
            if conversation_id:
                summary["conversation_id"] = conversation_id
        return summary

    @classmethod
    def _summarize_message_list(
        cls,
        payload: dict[str, Any],
        *,
        include_ids: bool,
    ) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        raw: Any = payload.get("value", [])
        if isinstance(raw, list):
            raw_messages: list[Any] = cast(list[Any], raw)
            for index, message in enumerate(raw_messages, start=1):
                if not isinstance(message, dict):
                    continue
                message_dict: dict[str, Any] = cast(dict[str, Any], message)
                messages.append(
                    cls._message_summary(message_dict, index=index, include_ids=include_ids)
                )
        result: dict[str, Any] = {"messages": messages}
        next_link = payload.get("@odata.nextLink")
        if next_link is not None:
            result["nextLink"] = next_link
        return result


def _addresses(addresses: list[str]) -> list[dict[str, dict[str, str]]]:
    return [{"emailAddress": {"address": addr}} for addr in addresses]


def _extract_message_id(candidate: Any) -> str:
    """Extract a Graph message ID from a string or a list/dict response.

    Accepts a raw ID, a message dict (looking up ``message_id`` or ``id``),
    or a list whose first dict has one of those fields.
    """
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("message_id must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        candidate_dict: dict[str, Any] = cast(dict[str, Any], candidate)
        for key in ("message_id", "id"):
            value: Any = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("message dict must contain a non-empty 'message_id' or 'id'")
    if isinstance(candidate, list):
        candidate_list: list[Any] = cast(list[Any], candidate)
        for entry in candidate_list:
            try:
                return _extract_message_id(entry)
            except ValueError:
                continue
        raise ValueError("no valid message id found in list")
    raise ValueError("message_id must be a string, dict, or list with an id")


def _extract_folder_id(candidate: Any) -> str:
    """Extract a Graph folder ID from a string or a dict response.

    Accepts a raw ID, a folder dict (looking up ``folder_id`` or ``id``),
    or one of the well-known folder names (``inbox``, ``drafts``,
    ``sentitems``, ``deleteditems``, ``junkemail``, ``outbox``,
    ``archive``).
    """
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("folder_id must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        candidate_dict: dict[str, Any] = cast(dict[str, Any], candidate)
        for key in ("folder_id", "id"):
            value: Any = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("folder dict must contain a non-empty 'folder_id' or 'id'")
    raise ValueError("folder_id must be a string or dict with an id")
