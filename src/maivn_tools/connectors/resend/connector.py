"""Resend transactional email API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="resend")
class ResendToolSet:
    """A connector for the Resend transactional email API."""

    metadata = ProviderMetadata(
        name="resend",
        display_name="Resend",
        version="0.1.0",
        description="Send transactional email and manage domains/audiences/broadcasts.",
        auth_modes=(AuthMode.API_KEY, AuthMode.BEARER),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://resend.com/docs/api-reference",
        homepage_url="https://resend.com/",
        tags=("email", "transactional"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.resend.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(api_key),
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
        first = contact.get("first_name") or ""
        last = contact.get("last_name") or ""
        summary: dict[str, Any] = {
            "contact_ref": f"contact_{index}",
            "name": f"{first} {last}".strip() or contact.get("email", ""),
            "email": contact.get("email", ""),
            "unsubscribed": contact.get("unsubscribed", False),
            "created_at": contact.get("created_at", ""),
        }
        if include_ids:
            summary["contact_id"] = contact.get("id", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def send_email(
        self,
        *,
        from_address: str,
        to: list[str] | str,
        subject: str,
        html: str | None = None,
        text: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: list[str] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        tags: list[dict[str, str]] | None = None,
        scheduled_at: str | None = None,
    ) -> dict[str, Any]:
        """Send a transactional email. Irreversible once sent.

        Marked destructive because emails cannot be unsent. Always confirm
        recipients and subject with the user before calling. Returns
        ``{"id": <email_id>}`` — pass that to ``get_email`` for status, or
        to ``cancel_email`` only if ``scheduled_at`` was set.
        """
        if not from_address or not subject:
            raise ValueError("from_address and subject must be non-empty")
        if html is None and text is None:
            raise ValueError("at least one of html or text must be provided")
        body: dict[str, Any] = {"from": from_address, "to": to, "subject": subject}
        if html is not None:
            body["html"] = html
        if text is not None:
            body["text"] = text
        if cc is not None:
            body["cc"] = cc
        if bcc is not None:
            body["bcc"] = bcc
        if reply_to is not None:
            body["reply_to"] = reply_to
        if attachments is not None:
            body["attachments"] = attachments
        if tags is not None:
            body["tags"] = tags
        if scheduled_at is not None:
            body["scheduled_at"] = scheduled_at
        return self._client.post("/emails", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def send_batch(self, emails: list[dict[str, Any]]) -> dict[str, Any]:
        """Send up to 100 emails in a single batch. Irreversible once sent.

        Marked destructive because emails cannot be unsent. Each entry has
        the same shape as ``send_email`` args. Returns ``{"data": [{"id":
        ...}, ...]}``.
        """
        if not emails:
            raise ValueError("emails must be non-empty")
        return self._client.post("/emails/batch", json=emails).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_email(self, email_id: str) -> dict[str, Any]:
        """Return a previously sent email by ID.

        Use to check delivery status — the response carries ``last_event``
        (``sent``, ``delivered``, ``bounced``, ``complained``, etc.).
        """
        if not email_id:
            raise ValueError("email_id must be a non-empty string")
        return self._client.get(f"/emails/{email_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def cancel_email(self, email_id: str) -> dict[str, Any]:
        """Cancel a scheduled email. Destructive — confirm with the user first.

        Only works while the email is still scheduled. Once sent, use
        ``get_email`` to inspect status.
        """
        if not email_id:
            raise ValueError("email_id must be a non-empty string")
        return self._client.post(f"/emails/{email_id}/cancel").json()

    # MARK: - Domains

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_domains(self) -> dict[str, Any]:
        """List sending domains.

        Returns the raw Resend payload — each domain has ``name``,
        ``status`` (``verified``/``pending``/``not_started``), and ``region``.
        """
        return self._client.get("/domains").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_domain(self, *, name: str, region: str | None = None) -> dict[str, Any]:
        """Add a domain (DNS verification required before sending).

        Returns the new domain resource. After creation, set the returned
        DNS records and call ``verify_domain``.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        body: dict[str, Any] = {"name": name}
        if region is not None:
            body["region"] = region
        return self._client.post("/domains", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def verify_domain(self, domain_id: str) -> dict[str, Any]:
        """Trigger DNS-record verification for a pending domain."""
        if not domain_id:
            raise ValueError("domain_id must be a non-empty string")
        return self._client.post(f"/domains/{domain_id}/verify").json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_domain(self, domain_id: str) -> dict[str, Any]:
        """Permanently delete a domain. Destructive — confirm with the user first."""
        if not domain_id:
            raise ValueError("domain_id must be a non-empty string")
        return self._client.delete(f"/domains/{domain_id}").json()

    # MARK: - Audiences & contacts

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_audiences(self) -> dict[str, Any]:
        """List audiences (marketing contact groups).

        Returns the raw Resend payload — each audience has ``id``, ``name``,
        ``created_at``.

        Resend has rebranded Audiences to Segments; the ``/audiences``
        endpoints are deprecated and proxy to the Segments API internally.
        They still function but will be removed in the future.
        """
        return self._client.get("/audiences").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_audience(self, *, name: str) -> dict[str, Any]:
        """Create an audience (group of contacts).

        Returns the new audience resource.

        Resend has rebranded Audiences to Segments; the ``/audiences``
        endpoints are deprecated and proxy to the Segments API internally.
        They still function but will be removed in the future.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        return self._client.post("/audiences", json={"name": name}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_contact(
        self,
        audience_id: str,
        *,
        email: str,
        first_name: str | None = None,
        last_name: str | None = None,
        unsubscribed: bool | None = None,
    ) -> dict[str, Any]:
        """Add a contact to an audience.

        Returns the new contact resource.
        """
        if not audience_id or not email:
            raise ValueError("audience_id and email must be non-empty")
        body: dict[str, Any] = {"email": email}
        if first_name is not None:
            body["first_name"] = first_name
        if last_name is not None:
            body["last_name"] = last_name
        if unsubscribed is not None:
            body["unsubscribed"] = unsubscribed
        return self._client.post(
            f"/audiences/{audience_id}/contacts",
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_contacts(
        self,
        audience_id: str,
        *,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List contacts in an audience with compact summaries.

        Returns compact summaries with ``contact_ref`` plus name, email,
        unsubscribed status. Raw IDs are omitted by default — set
        ``include_ids=True`` when ``delete_contact`` will use them.
        """
        if not audience_id:
            raise ValueError("audience_id must be a non-empty string")
        payload: dict[str, Any] = self._client.get(f"/audiences/{audience_id}/contacts").json()
        if include_raw:
            return payload
        contacts: list[Any] = payload.get("data") or []
        summaries = [
            self._contact_summary(cast("dict[str, Any]", c), index=i, include_ids=include_ids)
            for i, c in enumerate(contacts, start=1)
            if isinstance(c, dict)
        ]
        return {"contacts": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_contact(self, audience_id: str, contact_id: str) -> dict[str, Any]:
        """Delete a contact from an audience. Destructive — confirm with the user first.

        Unsubscribing a contact is irreversible from their perspective —
        they receive no future broadcasts.
        """
        if not audience_id or not contact_id:
            raise ValueError("audience_id and contact_id must be non-empty")
        return self._client.delete(
            f"/audiences/{audience_id}/contacts/{contact_id}",
        ).json()

    # MARK: - Broadcasts

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_broadcast(
        self,
        *,
        audience_id: str,
        from_address: str,
        subject: str,
        html: str | None = None,
        text: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Create a broadcast (one-to-many) email (draft only — does not send).

        Returns the new broadcast resource. Use ``send_broadcast`` to send.

        The ``audience_id`` kwarg is sent on the wire as ``segment_id``:
        Resend rebranded Audiences to Segments, and ``audience_id`` is now
        only accepted via a deprecated backward-compat shim.
        """
        if not audience_id or not from_address or not subject:
            raise ValueError("audience_id, from_address, and subject must be non-empty")
        if html is None and text is None:
            raise ValueError("html or text is required")
        body: dict[str, Any] = {
            "segment_id": audience_id,
            "from": from_address,
            "subject": subject,
        }
        if html is not None:
            body["html"] = html
        if text is not None:
            body["text"] = text
        if name is not None:
            body["name"] = name
        return self._client.post("/broadcasts", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_broadcasts(self) -> dict[str, Any]:
        """List broadcasts.

        Returns the raw Resend payload.
        """
        return self._client.get("/broadcasts").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def send_broadcast(self, broadcast_id: str) -> dict[str, Any]:
        """Send a broadcast immediately to its audience. Irreversible once sent.

        Marked destructive — every contact in the audience will receive
        the email. Always confirm with the user first.
        """
        if not broadcast_id:
            raise ValueError("broadcast_id must be a non-empty string")
        return self._client.post(f"/broadcasts/{broadcast_id}/send").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_api_keys(self) -> dict[str, Any]:
        """List API keys on the account.

        Returns the raw Resend payload.
        """
        return self._client.get("/api-keys").json()
