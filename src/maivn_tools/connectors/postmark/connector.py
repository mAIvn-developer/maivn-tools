"""Postmark transactional email API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.base import AuthStrategy
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_OUTBOUND_MESSAGES_OUTPUT, LIST_TEMPLATES_OUTPUT

# MARK: - Auth


class _ServerTokenAuth(AuthStrategy):
    mode = AuthMode.API_KEY

    def __init__(self, token: str, *, header: str) -> None:
        if not token:
            raise ValueError("token must be non-empty")
        self._token = token
        self._header = header

    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        headers = dict(request.get("headers") or {})
        headers[self._header] = self._token
        request["headers"] = headers
        return request

    def describe(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "header": self._header}


# MARK: - ToolSet


@toolset(prefix="postmark")
class PostmarkToolSet:
    """A connector for Postmark."""

    metadata = ProviderMetadata(
        name="postmark",
        display_name="Postmark",
        version="0.1.0",
        description="Send transactional email, manage templates and message streams.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://postmarkapp.com/developer/api/email-api",
        homepage_url="https://postmarkapp.com/",
        tags=("email", "transactional"),
    )

    def __init__(
        self,
        *,
        server_token: str | None = None,
        account_token: str | None = None,
        base_url: str = "https://api.postmarkapp.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not server_token and not account_token:
            raise ValueError("provide server_token or account_token")
        self.connection = connection
        token = server_token or account_token
        header = "X-Postmark-Server-Token" if server_token else "X-Postmark-Account-Token"
        assert token is not None
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=_ServerTokenAuth(token, header=header),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @staticmethod
    def _template_summary(
        template: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "template_ref": f"template_{index}",
            "name": template.get("Name", ""),
            "alias": template.get("Alias", ""),
            "template_type": template.get("TemplateType", ""),
            "active": template.get("Active", True),
        }
        if include_ids:
            summary["template_id"] = template.get("TemplateId")
        return summary

    @staticmethod
    def _message_summary(
        message: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        recipients: object = message.get("Recipients") or []
        recipient_emails: list[str] = []
        if isinstance(recipients, list):
            entries = cast("list[object]", recipients)
            for entry in entries:
                if isinstance(entry, str):
                    recipient_emails.append(entry)
                elif isinstance(entry, dict):
                    entry_dict = cast("dict[str, Any]", entry)
                    email = entry_dict.get("Email") or entry_dict.get("email") or ""
                    if isinstance(email, str) and email:
                        recipient_emails.append(email)
        summary: dict[str, Any] = {
            "message_ref": f"message_{index}",
            "from_address": message.get("From", ""),
            "to": recipient_emails,
            "subject": message.get("Subject", ""),
            "status": message.get("Status", ""),
            "received_at": message.get("ReceivedAt", ""),
        }
        if include_ids:
            summary["message_id"] = message.get("MessageID", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def send_email(
        self,
        *,
        from_address: str,
        to: list[str] | str,
        subject: str | None = None,
        text_body: str | None = None,
        html_body: str | None = None,
        template_id: int | None = None,
        template_alias: str | None = None,
        template_model: dict[str, Any] | None = None,
        cc: str | None = None,
        bcc: str | None = None,
        track_opens: bool | None = None,
        message_stream: str | None = None,
    ) -> dict[str, Any]:
        """Send a single email (or one rendered from a template). Irreversible once sent.

        Marked destructive because emails cannot be unsent. Always confirm
        recipients and subject with the user before calling. If
        ``template_id`` or ``template_alias`` is provided, this routes to
        ``/email/withTemplate`` and uses ``template_model`` for
        substitutions.
        """
        if not from_address:
            raise ValueError("from_address must be a non-empty string")
        to_value = to if isinstance(to, str) else ",".join(to)
        body: dict[str, Any] = {"From": from_address, "To": to_value}
        if subject is not None:
            body["Subject"] = subject
        if text_body is not None:
            body["TextBody"] = text_body
        if html_body is not None:
            body["HtmlBody"] = html_body
        if cc is not None:
            body["Cc"] = cc
        if bcc is not None:
            body["Bcc"] = bcc
        if track_opens is not None:
            body["TrackOpens"] = track_opens
        if message_stream is not None:
            body["MessageStream"] = message_stream
        if template_id is None and template_alias is None:
            return self._client.post("/email", json=body).json()
        if template_id is not None:
            body["TemplateId"] = template_id
        if template_alias is not None:
            body["TemplateAlias"] = template_alias
        if template_model is not None:
            body["TemplateModel"] = template_model
        return self._client.post("/email/withTemplate", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def send_batch(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Send up to 500 messages in one batch. Irreversible once sent.

        Marked destructive because emails cannot be unsent. Each entry
        carries the same fields as ``send_email``.
        """
        if not messages:
            raise ValueError("messages must be non-empty")
        return self._client.post("/email/batch", json=messages).json()

    # MARK: - Templates

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_TEMPLATES_OUTPUT)
    def list_templates(
        self,
        *,
        count: int = 25,
        offset: int = 0,
        template_type: str | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List templates with compact summaries.

        Returns compact summaries with ``template_ref`` plus name,
        alias (user-facing), template_type. Raw template IDs are omitted
        by default — alias is preferred for ``get_template`` /
        ``delete_template``.
        """
        if count < 1 or count > 500:
            raise ValueError("count must be between 1 and 500")
        params: dict[str, Any] = {"count": count, "offset": offset}
        if template_type is not None:
            params["TemplateType"] = template_type
        payload: dict[str, Any] = self._client.get("/templates", params=params).json()
        if include_raw:
            return payload
        templates: list[object] = payload.get("Templates") or []
        summaries = [
            self._template_summary(cast("dict[str, Any]", t), index=i, include_ids=include_ids)
            for i, t in enumerate(templates, start=1)
            if isinstance(t, dict)
        ]
        return {
            "templates": summaries,
            "count": len(summaries),
            "total_count": payload.get("TotalCount"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_template(self, template_id_or_alias: str | int) -> dict[str, Any]:
        """Return one template by ID or alias.

        Aliases are user-facing. Use after ``list_templates``.
        """
        return self._client.get(f"/templates/{template_id_or_alias}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_template(
        self,
        *,
        name: str,
        subject: str,
        html_body: str | None = None,
        text_body: str | None = None,
        alias: str | None = None,
        template_type: str = "Standard",
    ) -> dict[str, Any]:
        """Create a template.

        Provide ``alias`` for a user-facing handle (otherwise use the
        returned ``TemplateId``). Returns the new template resource.
        """
        if not name or not subject:
            raise ValueError("name and subject must be non-empty")
        body: dict[str, Any] = {
            "Name": name,
            "Subject": subject,
            "TemplateType": template_type,
        }
        if html_body is not None:
            body["HtmlBody"] = html_body
        if text_body is not None:
            body["TextBody"] = text_body
        if alias is not None:
            body["Alias"] = alias
        return self._client.post("/templates", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_template(self, template_id_or_alias: str | int) -> dict[str, Any]:
        """Permanently delete a template. Destructive — confirm with the user first."""
        return self._client.delete(f"/templates/{template_id_or_alias}").json()

    # MARK: - Messages, streams, servers

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_OUTBOUND_MESSAGES_OUTPUT)
    def list_outbound_messages(
        self,
        *,
        count: int = 25,
        offset: int = 0,
        recipient: str | None = None,
        tag: str | None = None,
        status: str | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """Search outbound messages with compact summaries.

        Best first tool for outbound triage. Returns compact summaries
        with ``message_ref`` plus from_address, to, subject, status. Raw
        Postmark message IDs are omitted by default — set
        ``include_ids=True`` when ``get_outbound_message`` needs them.
        """
        if count < 1 or count > 500:
            raise ValueError("count must be between 1 and 500")
        params: dict[str, Any] = {"count": count, "offset": offset}
        if recipient is not None:
            params["recipient"] = recipient
        if tag is not None:
            params["tag"] = tag
        if status is not None:
            params["status"] = status
        payload: dict[str, Any] = self._client.get("/messages/outbound", params=params).json()
        if include_raw:
            return payload
        messages: list[object] = payload.get("Messages") or []
        summaries = [
            self._message_summary(cast("dict[str, Any]", m), index=i, include_ids=include_ids)
            for i, m in enumerate(messages, start=1)
            if isinstance(m, dict)
        ]
        return {
            "messages": summaries,
            "count": len(summaries),
            "total_count": payload.get("TotalCount"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_outbound_message(self, message_id: str) -> dict[str, Any]:
        """Return one outbound message with full details.

        Use after ``list_outbound_messages(include_ids=True)``.
        """
        if not message_id:
            raise ValueError("message_id must be a non-empty string")
        return self._client.get(f"/messages/outbound/{message_id}/details").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_message_streams(self) -> dict[str, Any]:
        """List message streams configured on the server.

        Streams separate broadcast/transactional/inbound message types.
        """
        return self._client.get("/message-streams").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_servers(self) -> dict[str, Any]:
        """List servers on the account (requires account token).

        Postmark "servers" are mail-sending workspaces.
        """
        return self._client.get("/servers").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_delivery_stats(self) -> dict[str, Any]:
        """Return aggregate delivery statistics for the server.

        Returns inactive mail counts and bounce-type totals.
        """
        return self._client.get("/deliverystats").json()
