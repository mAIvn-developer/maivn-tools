"""Brevo (formerly Sendinblue) API v3 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: ToolSet


@toolset(prefix="brevo")
class BrevoToolSet:
    """A connector for the Brevo (Sendinblue) API v3."""

    metadata = ProviderMetadata(
        name="brevo",
        display_name="Brevo",
        version="0.1.0",
        description="Transactional email, contacts, campaigns, SMS, and WhatsApp.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developers.brevo.com/reference",
        homepage_url="https://www.brevo.com/",
        tags=("email", "marketing", "sms"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.brevo.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="api-key"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @staticmethod
    def _contact_summary(
        contact: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        raw_attrs: object = contact.get("attributes") or {}
        attrs: dict[str, Any] = (
            cast("dict[str, Any]", raw_attrs) if isinstance(raw_attrs, dict) else {}
        )
        first = attrs.get("FIRSTNAME") or ""
        last = attrs.get("LASTNAME") or ""
        summary: dict[str, Any] = {
            "contact_ref": f"contact_{index}",
            "name": f"{first} {last}".strip() or contact.get("email", ""),
            "email": contact.get("email", ""),
            "email_blacklisted": contact.get("emailBlacklisted", False),
            "sms_blacklisted": contact.get("smsBlacklisted", False),
            "list_ids": contact.get("listIds", []),
        }
        if include_ids:
            summary["contact_id"] = contact.get("id")
        return summary

    @staticmethod
    def _list_summary(
        lst: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "list_ref": f"list_{index}",
            "name": lst.get("name", ""),
            "total_subscribers": lst.get("totalSubscribers", 0),
            "total_blacklisted": lst.get("totalBlacklisted", 0),
            "folder_id": lst.get("folderId"),
        }
        if include_ids:
            summary["list_id"] = lst.get("id")
        return summary

    @staticmethod
    def _campaign_summary(
        campaign: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "campaign_ref": f"campaign_{index}",
            "name": campaign.get("name", ""),
            "subject": campaign.get("subject", ""),
            "type": campaign.get("type", ""),
            "status": campaign.get("status", ""),
            "scheduled_at": campaign.get("scheduledAt", ""),
        }
        if include_ids:
            summary["campaign_id"] = campaign.get("id")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def send_transactional_email(
        self,
        *,
        sender: dict[str, str],
        to: list[dict[str, str]],
        subject: str | None = None,
        html_content: str | None = None,
        text_content: str | None = None,
        template_id: int | None = None,
        params: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        reply_to: dict[str, str] | None = None,
        tags: list[str] | None = None,
        scheduled_at: str | None = None,
    ) -> dict[str, Any]:
        """Send a transactional email. Irreversible once sent.

        Marked destructive because emails cannot be unsent. ``sender`` is
        a dict like ``{"email": "x@y", "name": "X"}``; ``to`` is a list of
        the same. Always confirm recipients with the user first.
        """
        if not sender or not to:
            raise ValueError("sender and to must be non-empty")
        body: dict[str, Any] = {"sender": sender, "to": to}
        if subject is not None:
            body["subject"] = subject
        if html_content is not None:
            body["htmlContent"] = html_content
        if text_content is not None:
            body["textContent"] = text_content
        if template_id is not None:
            body["templateId"] = template_id
        if params is not None:
            body["params"] = params
        if attachments is not None:
            body["attachment"] = attachments
        if reply_to is not None:
            body["replyTo"] = reply_to
        if tags is not None:
            body["tags"] = tags
        if scheduled_at is not None:
            body["scheduledAt"] = scheduled_at
        return self._client.post("/v3/smtp/email", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_contacts(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        sort: str = "desc",
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List contacts with compact summaries.

        Returns compact summaries with ``contact_ref`` plus name, email
        (user-facing), email_blacklisted, list_ids. Raw contact IDs are
        omitted by default.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        payload: dict[str, Any] = self._client.get(
            "/v3/contacts",
            params={"limit": limit, "offset": offset, "sort": sort},
        ).json()
        if include_raw:
            return payload
        raw_contacts: list[Any] = payload.get("contacts") or []
        contacts: list[dict[str, Any]] = [c for c in raw_contacts if isinstance(c, dict)]
        summaries = [
            self._contact_summary(c, index=i, include_ids=include_ids)
            for i, c in enumerate(contacts, start=1)
        ]
        return {
            "contacts": summaries,
            "count": len(summaries),
            "total": payload.get("count"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_contact(self, email_or_id: str) -> dict[str, Any]:
        """Return one contact by email or ID.

        Email is the user-facing identifier — prefer it over the numeric
        ID.
        """
        if not email_or_id:
            raise ValueError("email_or_id must be a non-empty string")
        return self._client.get(f"/v3/contacts/{email_or_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_contact(
        self,
        *,
        email: str,
        attributes: dict[str, Any] | None = None,
        list_ids: list[int] | None = None,
        update_enabled: bool = False,
    ) -> dict[str, Any]:
        """Create a contact.

        Set ``update_enabled=True`` to upsert if the email already exists.
        Returns ``{"id": ...}``.
        """
        if not email:
            raise ValueError("email must be a non-empty string")
        body: dict[str, Any] = {"email": email, "updateEnabled": update_enabled}
        if attributes is not None:
            body["attributes"] = attributes
        if list_ids is not None:
            body["listIds"] = list_ids
        return self._client.post("/v3/contacts", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_contact(self, email_or_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Update a contact's attributes / list memberships.

        Returns ``{"id": ..., "updated": True, "status": <http_status>}``.
        """
        if not email_or_id or not fields:
            raise ValueError("email_or_id and fields must be non-empty")
        response = self._client.put(f"/v3/contacts/{email_or_id}", json=fields)
        return {"id": email_or_id, "updated": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_contact(self, email_or_id: str) -> dict[str, Any]:
        """Permanently delete a contact. Destructive — confirm first.

        Unsubscribing/removing a contact is irreversible from their
        perspective.
        """
        if not email_or_id:
            raise ValueError("email_or_id must be a non-empty string")
        self._client.delete(f"/v3/contacts/{email_or_id}")
        return {"id": email_or_id, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_lists(
        self,
        *,
        limit: int = 10,
        offset: int = 0,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List contact lists with compact summaries.

        Returns compact summaries with ``list_ref`` plus name,
        total_subscribers. Raw list IDs are omitted by default.
        """
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")
        payload: dict[str, Any] = self._client.get(
            "/v3/contacts/lists",
            params={"limit": limit, "offset": offset},
        ).json()
        if include_raw:
            return payload
        raw_lists: list[Any] = payload.get("lists") or []
        lists: list[dict[str, Any]] = [lst for lst in raw_lists if isinstance(lst, dict)]
        summaries = [
            self._list_summary(lst, index=i, include_ids=include_ids)
            for i, lst in enumerate(lists, start=1)
        ]
        return {
            "lists": summaries,
            "count": len(summaries),
            "total": payload.get("count"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_list(self, *, name: str, folder_id: int) -> dict[str, Any]:
        """Create a contact list inside a folder.

        Returns ``{"id": ...}``.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        return self._client.post(
            "/v3/contacts/lists",
            json={"name": name, "folderId": folder_id},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_email_campaigns(
        self,
        *,
        type: str | None = None,
        status: str | None = None,
        limit: int = 25,
        offset: int = 0,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List email campaigns with compact summaries.

        Returns compact summaries with ``campaign_ref`` plus name, subject,
        type, status. ``status`` filters: ``draft``, ``sent``, ``archive``,
        ``queued``, ``suspended``, ``in_process``.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if type is not None:
            params["type"] = type
        if status is not None:
            params["status"] = status
        payload: dict[str, Any] = self._client.get("/v3/emailCampaigns", params=params).json()
        if include_raw:
            return payload
        raw_campaigns: list[Any] = payload.get("campaigns") or []
        campaigns: list[dict[str, Any]] = [c for c in raw_campaigns if isinstance(c, dict)]
        summaries = [
            self._campaign_summary(c, index=i, include_ids=include_ids)
            for i, c in enumerate(campaigns, start=1)
        ]
        return {
            "campaigns": summaries,
            "count": len(summaries),
            "total": payload.get("count"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def send_sms(
        self,
        *,
        sender: str,
        recipient: str,
        content: str,
        type: str = "transactional",
    ) -> dict[str, Any]:
        """Send an SMS message. Irreversible once sent.

        Marked destructive because SMS cannot be unsent. ``type`` is
        ``transactional`` or ``marketing``. Always confirm with the user.
        """
        if not sender or not recipient or not content:
            raise ValueError("sender, recipient, and content must be non-empty")
        if type not in {"transactional", "marketing"}:
            raise ValueError("type must be 'transactional' or 'marketing'")
        return self._client.post(
            "/v3/transactionalSMS/sms",
            json={
                "sender": sender,
                "recipient": recipient,
                "content": content,
                "type": type,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_account(self) -> dict[str, Any]:
        """Return account plan and usage info.

        Returns email/sms quotas and plan details.
        """
        return self._client.get("/v3/account").json()
