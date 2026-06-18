"""Gmail API connector.

The connector authenticates with a Google-issued OAuth 2.0 bearer token and
exposes the most useful Gmail v1 endpoints. Token acquisition is the
caller's responsibility — pass either an :class:`OAuth2Token`, a token
callable returning one (the recommended pattern for refreshable tokens),
or a raw access-token string.

Recommended usage::

    from maivn_tools import OAuth2EndpointConfig, OAuth2Flow
    from maivn_tools.connectors.google_workspace import GmailToolSet

    flow = OAuth2Flow(
        client_id=...,
        client_secret=...,
        endpoints=OAuth2EndpointConfig(
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
        ),
    )
    cache = flow.refresh_token_cache(
        refresh_token,
        scope="https://www.googleapis.com/auth/gmail.modify",
    )
    connector = GmailToolSet(token=cache)
"""

# pyright: strict

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from ._shared import TokenSource, make_bearer_auth
from .output_schemas import SEARCH_MESSAGES_OUTPUT

# MARK: - Constants

GMAIL_API_URL = "https://gmail.googleapis.com/gmail/v1"
_METADATA_SUMMARY_MAX_RESULTS = 10


@toolset(prefix="gmail")
class GmailToolSet:
    """A connector for Gmail.

    Args:
        token: OAuth bearer credential. Accepts an :class:`OAuth2Token`, a
            callable returning one, or a raw access-token string.
        user: Gmail user identifier. Defaults to ``"me"`` (the authenticated
            user).
        transport: Optional :class:`HttpTransport` override.
        base_url: Override for tests or for self-hosted mirrors.
    """

    metadata = ProviderMetadata(
        name="gmail",
        display_name="Gmail",
        version="0.1.0",
        description="Read, search, label, and send Gmail messages.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "https://www.googleapis.com/auth/gmail.readonly": "Read mail and labels.",
            "https://www.googleapis.com/auth/gmail.modify": "Read, modify, and send mail.",
            "https://www.googleapis.com/auth/gmail.send": "Send mail only.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developers.google.com/gmail/api",
        homepage_url="https://mail.google.com",
        tags=("email", "google"),
    )

    def __init__(
        self,
        token: TokenSource,
        *,
        user: str = "me",
        transport: HttpTransport | None = None,
        base_url: str = GMAIL_API_URL,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not user:
            raise ValueError("user must be a non-empty string")
        self.connection = connection
        self._user = user
        self._client = HttpClient(
            base_url=base_url,
            auth=make_bearer_auth(token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @staticmethod
    def _headers_by_name(message: dict[str, Any]) -> dict[str, str]:
        payload_obj: object = message.get("payload", {})
        payload: dict[str, Any] = (
            cast("dict[str, Any]", payload_obj) if isinstance(payload_obj, dict) else {}
        )
        raw_headers: object = payload.get("headers", [])
        if not isinstance(raw_headers, list):
            return {}
        headers: list[object] = cast("list[object]", raw_headers)
        result: dict[str, str] = {}
        for header in headers:
            if not isinstance(header, dict):
                continue
            entry: dict[str, object] = cast("dict[str, object]", header)
            name: object = entry.get("name")
            value: object = entry.get("value")
            if isinstance(name, str) and isinstance(value, str):
                result[name.lower()] = value
        return result

    @classmethod
    def _message_summary(
        cls,
        message: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        headers = cls._headers_by_name(message)
        summary: dict[str, Any] = {
            "message_ref": f"message_{index}",
            "sender": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "received_at": headers.get("date", ""),
            "snippet": message.get("snippet", ""),
            "label_ids": message.get("labelIds", []),
        }
        if include_ids:
            summary["message_id"] = message.get("id", "")
            summary["thread_id"] = message.get("threadId", "")
        return summary

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def validate_connection(self) -> dict[str, Any]:
        """Verify the OAuth token by fetching the authenticated mailbox profile.

        Returns the Gmail profile dict — ``emailAddress``, ``messagesTotal``,
        ``threadsTotal``, ``historyId``. Use this once at startup to confirm
        the token has the right scopes before issuing other calls.
        """
        return self._client.get(self._user_path("/profile")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_labels(self) -> list[dict[str, Any]]:
        """List every label defined on the mailbox.

        Returns a list of label dicts: ``id`` (e.g. ``"INBOX"``, ``"Label_42"``),
        ``name``, ``type`` (``"system"`` or ``"user"``), and visibility fields.
        Pass an ``id`` from this list to label/thread operations — never
        invent label IDs.
        """
        payload: dict[str, Any] = self._client.get(self._user_path("/labels")).json()
        labels: object = payload.get("labels", [])
        return cast("list[dict[str, Any]]", labels) if isinstance(labels, list) else []

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SEARCH_MESSAGES_OUTPUT)
    def search_messages(
        self,
        query: str = "",
        *,
        label_ids: list[str] | None = None,
        max_results: int = 10,
        page_token: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search for messages using Gmail's query syntax.

        Best first tool for inbox triage. By default it returns compact,
        human-readable message summaries: ``message_ref``, sender, subject,
        received date, labels, and snippet. Summary mode caps ``max_results``
        at 10 so agent runs stay fast. Raw Gmail IDs are omitted by default
        because they are internal handles, not useful final-answer content.
        Set ``include_ids=True`` only when a follow-up Gmail tool needs a
        ``message_id`` or ``thread_id``.
        """
        if max_results < 1 or max_results > 500:
            raise ValueError("max_results must be between 1 and 500")
        requested_max_results = max_results
        if include_metadata:
            max_results = min(max_results, _METADATA_SUMMARY_MAX_RESULTS)
        params: dict[str, Any] = {"maxResults": max_results}
        if query:
            params["q"] = query
        if label_ids:
            params["labelIds"] = label_ids
        if page_token is not None:
            params["pageToken"] = page_token
        payload: dict[str, Any] = self._client.get(
            self._user_path("/messages"), params=params
        ).json()
        if not include_metadata:
            return payload

        summaries: list[dict[str, Any]] = []
        raw_messages: object = payload.get("messages", [])
        messages: list[object] = (
            cast("list[object]", raw_messages) if isinstance(raw_messages, list) else []
        )
        for index, item in enumerate(messages, start=1):
            if not isinstance(item, dict):
                continue
            entry: dict[str, Any] = cast("dict[str, Any]", item)
            item_id: object = entry.get("id")
            if not item_id:
                continue
            message: dict[str, Any] = self._client.get(
                self._user_path(f"/messages/{entry['id']}"),
                params={"format": "metadata"},
            ).json()
            summaries.append(
                self._message_summary(
                    message,
                    index=index,
                    include_ids=include_ids,
                )
            )
        result: dict[str, Any] = {
            "messages": summaries,
            "nextPageToken": payload.get("nextPageToken"),
            "resultSizeEstimate": payload.get("resultSizeEstimate", len(summaries)),
        }
        if requested_max_results != max_results:
            result["requestedMaxResults"] = requested_max_results
            result["summaryLimit"] = _METADATA_SUMMARY_MAX_RESULTS
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_message(
        self,
        message_id: str,
        format: str = "metadata",
    ) -> dict[str, Any]:
        """Fetch a single message by ID.

        Returns the Gmail message resource. With ``format="metadata"`` the
        ``payload.headers`` array carries ``From``, ``To``, ``Subject``, and
        ``Date``. Do not use this for ordinary inbox triage unless
        ``search_messages(include_ids=True)`` gave you a specific internal
        ``message_id`` to inspect.
        """
        if not message_id:
            raise ValueError("message_id must be a non-empty string")
        if format not in {"minimal", "metadata", "full", "raw"}:
            raise ValueError("format must be one of: minimal, metadata, full, raw")
        return self._client.get(
            self._user_path(f"/messages/{message_id}"),
            params={"format": format},
        ).json()

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
        sender: str | None = None,
        reply_to: str | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Send an email via the Gmail send endpoint.

        Returns the sent message resource (``id``, ``threadId``, ``labelIds``).
        Always confirm the recipient list with the user before calling this
        in an interactive agent loop.
        """
        if not to:
            raise ValueError("to must contain at least one recipient")
        if body_text is None and body_html is None:
            raise ValueError("body_text or body_html must be supplied")
        message = EmailMessage()
        message["To"] = ", ".join(to)
        message["Subject"] = subject
        if sender:
            message["From"] = sender
        if cc:
            message["Cc"] = ", ".join(cc)
        if bcc:
            message["Bcc"] = ", ".join(bcc)
        if reply_to:
            message["Reply-To"] = reply_to
        message.set_content(body_text or "")
        if body_html is not None:
            message.add_alternative(body_html, subtype="html")
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        payload: dict[str, Any] = {"raw": encoded}
        if thread_id is not None:
            payload["threadId"] = thread_id
        return self._client.post(self._user_path("/messages/send"), json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def modify_labels(
        self,
        message_id: str,
        *,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add and/or remove labels on a message.

        Returns the updated message resource. Use this to archive
        (``remove_label_ids=["INBOX"]``), mark read (``remove=["UNREAD"]``),
        or apply a category.
        """
        if not message_id:
            raise ValueError("message_id must be a non-empty string")
        if not add_label_ids and not remove_label_ids:
            raise ValueError("Provide at least one of add_label_ids or remove_label_ids")
        payload: dict[str, Any] = {}
        if add_label_ids:
            payload["addLabelIds"] = list(add_label_ids)
        if remove_label_ids:
            payload["removeLabelIds"] = list(remove_label_ids)
        return self._client.post(
            self._user_path(f"/messages/{message_id}/modify"),
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def trash_message(
        self,
        message_id: str,
    ) -> dict[str, Any]:
        """Move a message to Trash. Reversible via :meth:`untrash_message` until purged.

        Returns the updated message resource. Confirm with the user before
        calling — this is a destructive operation.
        """
        if not message_id:
            raise ValueError("message_id must be a non-empty string")
        return self._client.post(self._user_path(f"/messages/{message_id}/trash")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def untrash_message(
        self,
        message_id: str,
    ) -> dict[str, Any]:
        """Restore a message from Trash.

        Returns the updated message resource (``labelIds`` will no longer
        include ``TRASH``).
        """
        if not message_id:
            raise ValueError("message_id must be a non-empty string")
        return self._client.post(self._user_path(f"/messages/{message_id}/untrash")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_profile(self) -> dict[str, Any]:
        """Return mailbox profile.

        Returns ``{"emailAddress": ..., "messagesTotal": ...,
        "threadsTotal": ..., "historyId": ...}``. The ``historyId`` is a
        good starting point for :meth:`list_history` if you need
        incremental updates.
        """
        return self._client.get(self._user_path("/profile")).json()

    # MARK: - Threads

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_threads(
        self,
        query: str = "",
        *,
        label_ids: list[str] | None = None,
        max_results: int = 25,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List threads matching a query.

        Returns ``{"threads": [{"id": ..., "historyId": ..., "snippet": ...}],
        "nextPageToken": ..., "resultSizeEstimate": ...}``. Threads carry a
        snippet so this is more LLM-friendly than search_messages for triage
        — but ``messages`` are still IDs-only; use :meth:`get_thread` for
        full bodies.
        """
        if max_results < 1 or max_results > 500:
            raise ValueError("max_results must be between 1 and 500")
        params: dict[str, Any] = {"maxResults": max_results}
        if query:
            params["q"] = query
        if label_ids:
            params["labelIds"] = label_ids
        if page_token is not None:
            params["pageToken"] = page_token
        return self._client.get(self._user_path("/threads"), params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_thread(
        self,
        thread_id: str,
        format: str = "metadata",
    ) -> dict[str, Any]:
        """Fetch a thread by ID with all its messages.

        Returns ``{"id": ..., "historyId": ..., "messages": [<message>...]}``.
        Each entry in ``messages`` has the same shape as a get_message
        response at the requested format level.
        """
        if not thread_id:
            raise ValueError("thread_id must be a non-empty string")
        if format not in {"minimal", "metadata", "full"}:
            raise ValueError("format must be one of: minimal, metadata, full")
        return self._client.get(
            self._user_path(f"/threads/{thread_id}"),
            params={"format": format},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def modify_thread_labels(
        self,
        thread_id: str,
        *,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add/remove labels on every message in a thread.

        Returns the updated thread resource. Useful for bulk archival
        (``remove=["INBOX"]``) or marking a conversation read
        (``remove=["UNREAD"]``).
        """
        if not thread_id:
            raise ValueError("thread_id must be a non-empty string")
        if not add_label_ids and not remove_label_ids:
            raise ValueError("Provide at least one of add_label_ids or remove_label_ids")
        payload: dict[str, Any] = {}
        if add_label_ids:
            payload["addLabelIds"] = list(add_label_ids)
        if remove_label_ids:
            payload["removeLabelIds"] = list(remove_label_ids)
        return self._client.post(
            self._user_path(f"/threads/{thread_id}/modify"),
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def trash_thread(
        self,
        thread_id: str,
    ) -> dict[str, Any]:
        """Move every message in a thread to Trash.

        Returns the updated thread resource. Destructive — confirm with the
        user first.
        """
        if not thread_id:
            raise ValueError("thread_id must be a non-empty string")
        return self._client.post(self._user_path(f"/threads/{thread_id}/trash")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def untrash_thread(
        self,
        thread_id: str,
    ) -> dict[str, Any]:
        """Restore every message in a thread from Trash.

        Returns the updated thread resource.
        """
        if not thread_id:
            raise ValueError("thread_id must be a non-empty string")
        return self._client.post(self._user_path(f"/threads/{thread_id}/untrash")).json()

    # MARK: - Drafts

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_drafts(
        self,
        *,
        max_results: int = 25,
        page_token: str | None = None,
        query: str = "",
    ) -> dict[str, Any]:
        """List drafts in the mailbox.

        Returns ``{"drafts": [{"id": ..., "message": {"id": ...,
        "threadId": ...}}], "nextPageToken": ..., "resultSizeEstimate":
        ...}``. The ``drafts[*].id`` values can be passed to get_draft,
        send_draft, etc.
        """
        if max_results < 1 or max_results > 500:
            raise ValueError("max_results must be between 1 and 500")
        params: dict[str, Any] = {"maxResults": max_results}
        if query:
            params["q"] = query
        if page_token is not None:
            params["pageToken"] = page_token
        return self._client.get(self._user_path("/drafts"), params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_draft(
        self,
        draft_id: str,
        format: str = "metadata",
    ) -> dict[str, Any]:
        """Fetch one draft by ID.

        Returns ``{"id": ..., "message": <message resource>}``.
        """
        if not draft_id:
            raise ValueError("draft_id must be a non-empty string")
        if format not in {"minimal", "metadata", "full", "raw"}:
            raise ValueError("format must be one of: minimal, metadata, full, raw")
        return self._client.get(
            self._user_path(f"/drafts/{draft_id}"),
            params={"format": format},
        ).json()

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
        sender: str | None = None,
        reply_to: str | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new draft message.

        Returns the new draft resource (``id``, ``message.id``,
        ``message.threadId``). Use :meth:`send_draft` to send it later.
        """
        if not to:
            raise ValueError("to must contain at least one recipient")
        if body_text is None and body_html is None:
            raise ValueError("body_text or body_html must be supplied")
        message = self._build_mime(
            to=to,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            cc=cc,
            bcc=bcc,
            sender=sender,
            reply_to=reply_to,
        )
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        payload: dict[str, Any] = {"message": {"raw": encoded}}
        if thread_id is not None:
            payload["message"]["threadId"] = thread_id
        return self._client.post(self._user_path("/drafts"), json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_draft(
        self,
        draft_id: str,
        to: list[str],
        subject: str,
        body_text: str | None = None,
        *,
        body_html: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        sender: str | None = None,
        reply_to: str | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Replace the contents of an existing draft.

        Returns the updated draft resource. This is a full replace — fields
        you omit are reset, not preserved.
        """
        if not draft_id:
            raise ValueError("draft_id must be a non-empty string")
        if not to:
            raise ValueError("to must contain at least one recipient")
        if body_text is None and body_html is None:
            raise ValueError("body_text or body_html must be supplied")
        message = self._build_mime(
            to=to,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            cc=cc,
            bcc=bcc,
            sender=sender,
            reply_to=reply_to,
        )
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        payload: dict[str, Any] = {"message": {"raw": encoded}}
        if thread_id is not None:
            payload["message"]["threadId"] = thread_id
        return self._client.put(
            self._user_path(f"/drafts/{draft_id}"),
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def send_draft(
        self,
        draft_id: str,
    ) -> dict[str, Any]:
        """Send an existing draft.

        Returns the sent message resource (``id``, ``threadId``,
        ``labelIds``). Always confirm with the user before calling.
        """
        if not draft_id:
            raise ValueError("draft_id must be a non-empty string")
        return self._client.post(
            self._user_path("/drafts/send"),
            json={"id": draft_id},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_draft(
        self,
        draft_id: str,
    ) -> dict[str, Any]:
        """Permanently delete a draft.

        Returns ``{"id": ..., "deleted": True}``. Destructive — confirm
        with the user before calling.
        """
        if not draft_id:
            raise ValueError("draft_id must be a non-empty string")
        self._client.delete(self._user_path(f"/drafts/{draft_id}"))
        return {"id": draft_id, "deleted": True}

    # MARK: - Labels

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_label(
        self,
        label_id: str,
    ) -> dict[str, Any]:
        """Return a single label by ID.

        Returns the label resource: ``id``, ``name``, ``type`` (``"system"``
        or ``"user"``), and visibility fields.
        """
        if not label_id:
            raise ValueError("label_id must be a non-empty string")
        return self._client.get(self._user_path(f"/labels/{label_id}")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_label(
        self,
        name: str,
        *,
        label_list_visibility: str = "labelShow",
        message_list_visibility: str = "show",
    ) -> dict[str, Any]:
        """Create a user label.

        Returns the new label resource (with its server-assigned ``id``).
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        payload = {
            "name": name,
            "labelListVisibility": label_list_visibility,
            "messageListVisibility": message_list_visibility,
        }
        return self._client.post(self._user_path("/labels"), json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_label(
        self,
        label_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch an existing label.

        Returns the updated label resource.
        """
        if not label_id:
            raise ValueError("label_id must be a non-empty string")
        if not patch:
            raise ValueError("patch must contain at least one field")
        return self._client.patch(
            self._user_path(f"/labels/{label_id}"),
            json=patch,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_label(
        self,
        label_id: str,
    ) -> dict[str, Any]:
        """Delete a user label (removes it from every message).

        Returns ``{"id": ..., "deleted": True}``. Destructive — confirm with
        the user.
        """
        if not label_id:
            raise ValueError("label_id must be a non-empty string")
        self._client.delete(self._user_path(f"/labels/{label_id}"))
        return {"id": label_id, "deleted": True}

    # MARK: - Attachments and batch ops

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_attachment(
        self,
        message_id: str,
        attachment_id: str,
    ) -> dict[str, Any]:
        """Return base64-encoded attachment bytes.

        Returns ``{"size": <bytes>, "data": <base64-url string>}``. Decode
        ``data`` with ``base64.urlsafe_b64decode`` to get the raw bytes.
        """
        if not message_id or not attachment_id:
            raise ValueError("message_id and attachment_id must be non-empty")
        return self._client.get(
            self._user_path(f"/messages/{message_id}/attachments/{attachment_id}")
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def batch_modify_messages(
        self,
        message_ids: list[str],
        *,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add/remove labels on up to 1000 messages in one request.

        Returns ``{"count": <n>, "ok": True}`` on success. Gmail returns an
        empty 204 body on success, so the count is reflected back to the
        caller.
        """
        if not message_ids:
            raise ValueError("message_ids must contain at least one id")
        if len(message_ids) > 1000:
            raise ValueError("Gmail allows at most 1000 ids per batchModify call")
        if not add_label_ids and not remove_label_ids:
            raise ValueError("Provide at least one of add_label_ids or remove_label_ids")
        payload: dict[str, Any] = {"ids": list(message_ids)}
        if add_label_ids:
            payload["addLabelIds"] = list(add_label_ids)
        if remove_label_ids:
            payload["removeLabelIds"] = list(remove_label_ids)
        self._client.post(self._user_path("/messages/batchModify"), json=payload)
        return {"count": len(message_ids), "ok": True}

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def batch_delete_messages(
        self,
        message_ids: list[str],
    ) -> dict[str, Any]:
        """Permanently delete up to 1000 messages by id.

        Returns ``{"count": <n>, "deleted": True}``. Destructive and not
        reversible (no Trash). Confirm with the user first.
        """
        if not message_ids:
            raise ValueError("message_ids must contain at least one id")
        if len(message_ids) > 1000:
            raise ValueError("Gmail allows at most 1000 ids per batchDelete call")
        self._client.post(
            self._user_path("/messages/batchDelete"),
            json={"ids": list(message_ids)},
        )
        return {"count": len(message_ids), "deleted": True}

    # MARK: - History and filters

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_history(
        self,
        start_history_id: str,
        *,
        label_id: str | None = None,
        history_types: list[str] | None = None,
        max_results: int = 100,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List mailbox history events since ``start_history_id``.

        Returns ``{"history": [...], "nextPageToken": ..., "historyId":
        ...}``. The trailing ``historyId`` is what you pass as
        ``start_history_id`` on the next call.
        """
        if not start_history_id:
            raise ValueError("start_history_id must be a non-empty string")
        if max_results < 1 or max_results > 500:
            raise ValueError("max_results must be between 1 and 500")
        params: dict[str, Any] = {
            "startHistoryId": start_history_id,
            "maxResults": max_results,
        }
        if label_id is not None:
            params["labelId"] = label_id
        if history_types:
            params["historyTypes"] = history_types
        if page_token is not None:
            params["pageToken"] = page_token
        return self._client.get(self._user_path("/history"), params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_filters(self) -> dict[str, Any]:
        """List Gmail filters configured for the mailbox.

        Returns ``{"filter": [{"id": ..., "criteria": {...}, "action":
        {...}}]}``.
        """
        return self._client.get(self._user_path("/settings/filters")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_filter(
        self,
        criteria: dict[str, Any],
        action: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a Gmail filter with ``criteria`` and ``action`` payloads.

        Returns the new filter resource (``id``, ``criteria``, ``action``).
        """
        if not criteria or not action:
            raise ValueError("criteria and action must both be non-empty")
        return self._client.post(
            self._user_path("/settings/filters"),
            json={"criteria": criteria, "action": action},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_filter(
        self,
        filter_id: str,
    ) -> dict[str, Any]:
        """Delete a filter by ID.

        Returns ``{"id": ..., "deleted": True}``.
        """
        if not filter_id:
            raise ValueError("filter_id must be a non-empty string")
        self._client.delete(self._user_path(f"/settings/filters/{filter_id}"))
        return {"id": filter_id, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_send_as(self) -> dict[str, Any]:
        """List configured send-as aliases.

        Returns ``{"sendAs": [{"sendAsEmail": ..., "displayName": ...,
        "isPrimary": ..., "isDefault": ...}, ...]}``.
        """
        return self._client.get(self._user_path("/settings/sendAs")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_vacation_settings(self) -> dict[str, Any]:
        """Return the vacation auto-responder settings.

        Returns ``{"enableAutoReply": bool, "responseSubject": str,
        "responseBodyPlainText": str, "responseBodyHtml": str,
        "restrictToContacts": bool, "restrictToDomain": bool,
        "startTime": str, "endTime": str}``.
        """
        return self._client.get(self._user_path("/settings/vacation")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_vacation_settings(
        self,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        """Update the vacation auto-responder.

        Returns the updated settings resource (same shape as
        :meth:`get_vacation_settings`).
        """
        if not settings:
            raise ValueError("settings must not be empty")
        return self._client.put(
            self._user_path("/settings/vacation"),
            json=settings,
        ).json()

    # MARK: - Internal

    def _user_path(self, suffix: str) -> str:
        return f"/users/{self._user}{suffix}"

    @staticmethod
    def _build_mime(
        *,
        to: list[str],
        subject: str,
        body_text: str | None,
        body_html: str | None,
        cc: list[str] | None,
        bcc: list[str] | None,
        sender: str | None,
        reply_to: str | None,
    ) -> EmailMessage:
        message = EmailMessage()
        message["To"] = ", ".join(to)
        message["Subject"] = subject
        if sender:
            message["From"] = sender
        if cc:
            message["Cc"] = ", ".join(cc)
        if bcc:
            message["Bcc"] = ", ".join(bcc)
        if reply_to:
            message["Reply-To"] = reply_to
        message.set_content(body_text or "")
        if body_html is not None:
            message.add_alternative(body_html, subtype="html")
        return message
