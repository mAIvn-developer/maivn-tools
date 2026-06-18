"""Mailchimp Transactional (Mandrill) API connector.

The Mandrill API accepts an API key inside the JSON body for every call,
not as a header. This toolset wraps that pattern.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.base import NoAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_TEMPLATES_OUTPUT

# MARK: ToolSet


@toolset(prefix="mandrill")
class MandrillToolSet:
    """A connector for Mailchimp Transactional / Mandrill 1.0."""

    metadata = ProviderMetadata(
        name="mandrill",
        display_name="Mailchimp Transactional (Mandrill)",
        version="0.1.0",
        description="Send transactional email and manage templates and webhooks.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://mailchimp.com/developer/transactional/api/",
        homepage_url="https://mailchimp.com/features/transactional-email/",
        tags=("email", "transactional"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://mandrillapp.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._api_key = api_key
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=NoAuth(),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _call(self, path: str, body: dict[str, Any] | None = None) -> Any:
        payload: dict[str, Any] = {"key": self._api_key}
        if body:
            payload.update(body)
        return self._client.post(path, json=payload).json()

    @staticmethod
    def _template_summary(
        template: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        return {
            "template_ref": f"template_{index}",
            "name": template.get("name", ""),
            "slug": template.get("slug", ""),
            "subject": template.get("subject", ""),
            "from_email": template.get("from_email", ""),
            "publish_name": template.get("publish_name", ""),
            "published_at": template.get("published_at", ""),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def ping(self) -> dict[str, Any]:
        """Return ``PONG!`` if the API key is valid.

        Use to validate the API key at startup.
        """
        return self._call("/api/1.0/users/ping2")

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user_info(self) -> dict[str, Any]:
        """Return account / user info.

        Returns plan, hourly quota, reputation, and usage counters.
        """
        return self._call("/api/1.0/users/info")

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def send_email(
        self,
        *,
        from_email: str,
        to: list[dict[str, str]],
        subject: str,
        html: str | None = None,
        text: str | None = None,
        from_name: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        merge_vars: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
        async_send: bool | None = None,
        send_at: str | None = None,
    ) -> dict[str, Any]:
        """Send a transactional email. Irreversible once sent.

        Marked destructive because emails cannot be unsent. ``to`` is a
        list of dicts like ``[{"email": "a@b", "name": "A"}]``. Always
        confirm with the user before sending.
        """
        if not from_email or not subject or not to:
            raise ValueError("from_email, to, and subject must be non-empty")
        if html is None and text is None:
            raise ValueError("provide html or text")
        message: dict[str, Any] = {
            "from_email": from_email,
            "to": to,
            "subject": subject,
        }
        if from_name is not None:
            message["from_name"] = from_name
        if html is not None:
            message["html"] = html
        if text is not None:
            message["text"] = text
        if attachments is not None:
            message["attachments"] = attachments
        if merge_vars is not None:
            message["merge_vars"] = merge_vars
        if tags is not None:
            message["tags"] = tags
        body: dict[str, Any] = {"message": message}
        if async_send is not None:
            body["async"] = async_send
        if send_at is not None:
            body["send_at"] = send_at
        return self._call("/api/1.0/messages/send", body)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def send_template(
        self,
        *,
        template_name: str,
        template_content: list[dict[str, str]] | None,
        message: dict[str, Any],
        async_send: bool | None = None,
    ) -> dict[str, Any]:
        """Send via a stored template. Irreversible once sent.

        Marked destructive because emails cannot be unsent. Always confirm
        with the user first.
        """
        if not template_name:
            raise ValueError("template_name must be a non-empty string")
        body: dict[str, Any] = {
            "template_name": template_name,
            "template_content": template_content or [],
            "message": message,
        }
        if async_send is not None:
            body["async"] = async_send
        return self._call("/api/1.0/messages/send-template", body)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_message_info(self, message_id: str) -> dict[str, Any]:
        """Return info about a sent message.

        Returns delivery status, opens, clicks. Use to verify a send
        completed.
        """
        if not message_id:
            raise ValueError("message_id must be a non-empty string")
        return self._call("/api/1.0/messages/info", {"id": message_id})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_TEMPLATES_OUTPUT)
    def list_templates(
        self,
        *,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List stored templates with compact summaries.

        Returns compact summaries with ``template_ref`` plus name, slug
        (user-facing), subject, from_email. Mandrill uses ``name`` as the
        primary identifier.
        """
        payload: object = self._call("/api/1.0/templates/list")
        if include_raw:
            return cast("dict[str, Any]", payload)
        templates: list[object] = cast("list[object]", payload) if isinstance(payload, list) else []
        summaries = [
            self._template_summary(cast("dict[str, Any]", t), index=i, include_ids=include_ids)
            for i, t in enumerate(templates, start=1)
            if isinstance(t, dict)
        ]
        return {"templates": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_template(
        self,
        *,
        name: str,
        from_email: str | None = None,
        from_name: str | None = None,
        subject: str | None = None,
        code: str | None = None,
        text: str | None = None,
        publish: bool = True,
    ) -> dict[str, Any]:
        """Add a new template.

        ``code`` is the HTML body. Returns the new template resource.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        body: dict[str, Any] = {"name": name, "publish": publish}
        if from_email is not None:
            body["from_email"] = from_email
        if from_name is not None:
            body["from_name"] = from_name
        if subject is not None:
            body["subject"] = subject
        if code is not None:
            body["code"] = code
        if text is not None:
            body["text"] = text
        return self._call("/api/1.0/templates/add", body)

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_template(self, *, name: str) -> dict[str, Any]:
        """Permanently delete a template. Destructive — confirm with the user first."""
        if not name:
            raise ValueError("name must be a non-empty string")
        return self._call("/api/1.0/templates/delete", {"name": name})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_webhooks(self) -> dict[str, Any]:
        """List webhooks.

        Returns the raw provider payload — each webhook has ``id``,
        ``url``, ``events``.
        """
        return self._call("/api/1.0/webhooks/list")

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_webhook(
        self,
        *,
        url: str,
        events: list[str],
        description: str | None = None,
    ) -> dict[str, Any]:
        """Subscribe to webhooks for events like ``send``, ``open``, ``click``.

        Returns the new webhook resource.
        """
        if not url or not events:
            raise ValueError("url and events must be non-empty")
        body: dict[str, Any] = {"url": url, "events": events}
        if description is not None:
            body["description"] = description
        return self._call("/api/1.0/webhooks/add", body)
