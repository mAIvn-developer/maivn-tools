"""SendGrid Web API v3 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_LISTS_OUTPUT, LIST_TEMPLATES_OUTPUT


@toolset(prefix="sendgrid")
class SendGridToolSet:
    """A connector for the SendGrid Web API v3."""

    metadata = ProviderMetadata(
        name="sendgrid",
        display_name="SendGrid",
        version="0.1.0",
        description="Send email, manage templates, contacts, lists, and suppressions.",
        auth_modes=(AuthMode.BEARER, AuthMode.API_KEY),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.sendgrid.com/api-reference/",
        homepage_url="https://sendgrid.com/",
        tags=("email", "transactional", "marketing"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.sendgrid.com",
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
    def _list_summary(
        list_obj: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "list_ref": f"list_{index}",
            "name": list_obj.get("name", ""),
            "contact_count": list_obj.get("contact_count", 0),
        }
        if include_ids:
            summary["list_id"] = list_obj.get("id", "")
        return summary

    @staticmethod
    def _next_page_token(payload: dict[str, Any]) -> str | None:
        """Extract a cursor for the next page from a SendGrid list payload.

        SendGrid paginates either via a top-level ``next_page_token`` (legacy
        list endpoints) or a ``_metadata.next`` URL (marketing endpoints).
        Returns the next-page token / URL, or ``None`` when there are no more
        pages.
        """
        token = payload.get("next_page_token")
        if isinstance(token, str) and token:
            return token
        metadata = payload.get("_metadata")
        if isinstance(metadata, dict):
            metadata_dict = cast("dict[str, Any]", metadata)
            next_url = metadata_dict.get("next")
            if isinstance(next_url, str) and next_url:
                return next_url
        return None

    @staticmethod
    def _template_summary(
        template: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "template_ref": f"template_{index}",
            "name": template.get("name", ""),
            "generation": template.get("generation", ""),
            "updated_at": template.get("updated_at", ""),
        }
        if include_ids:
            summary["template_id"] = template.get("id", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def send_email(
        self,
        *,
        from_address: str,
        to: list[str] | str,
        subject: str,
        text: str | None = None,
        html: str | None = None,
        template_id: str | None = None,
        dynamic_template_data: dict[str, Any] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        categories: list[str] | None = None,
        send_at: int | None = None,
    ) -> dict[str, Any]:
        """Send an email via the v3 ``/mail/send`` endpoint. Irreversible once sent.

        Marked destructive because emails cannot be unsent. Always confirm
        recipients and subject with the user before calling. ``send_at``
        is a Unix timestamp for scheduled sends. Returns ``{"status":
        <http_status>, "headers": {...}}`` (SendGrid returns an empty body
        with ``X-Message-Id`` header).
        """
        if not from_address or not subject:
            raise ValueError("from_address and subject must be non-empty")
        recipients = [{"email": addr} for addr in (to if isinstance(to, list) else [to])]
        if not recipients:
            raise ValueError("to must contain at least one recipient")
        personalizations: dict[str, Any] = {"to": recipients, "subject": subject}
        if cc is not None:
            personalizations["cc"] = [{"email": a} for a in cc]
        if bcc is not None:
            personalizations["bcc"] = [{"email": a} for a in bcc]
        if dynamic_template_data is not None:
            personalizations["dynamic_template_data"] = dynamic_template_data
        body: dict[str, Any] = {
            "personalizations": [personalizations],
            "from": {"email": from_address},
        }
        contents: list[dict[str, str]] = []
        if text is not None:
            contents.append({"type": "text/plain", "value": text})
        if html is not None:
            contents.append({"type": "text/html", "value": html})
        if contents:
            body["content"] = contents
        if template_id is not None:
            body["template_id"] = template_id
        if attachments is not None:
            body["attachments"] = attachments
        if categories is not None:
            body["categories"] = categories
        if send_at is not None:
            body["send_at"] = send_at
        response = self._client.post("/v3/mail/send", json=body)
        return {"status": response.status, "headers": dict(response.headers)}

    # MARK: - Templates

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_TEMPLATES_OUTPUT)
    def list_templates(
        self,
        *,
        generations: str = "dynamic",
        page_size: int = 200,
        page_token: str | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List dynamic or legacy templates with compact summaries.

        Returns compact summaries with ``template_ref`` plus name,
        generation, updated_at, and a ``next_page_token`` (or ``None``)
        for paging through accounts with more than ``page_size`` templates.
        Raw template IDs are omitted by default — set ``include_ids=True``
        when ``get_template`` / ``delete_template`` needs them.

        ``page_size`` is a required SendGrid query parameter (1..200). Pass
        the returned ``next_page_token`` back as ``page_token`` to fetch the
        next page.
        """
        if page_size < 1 or page_size > 200:
            raise ValueError("page_size must be between 1 and 200")
        params: dict[str, Any] = {
            "generations": generations,
            "page_size": page_size,
        }
        if page_token is not None:
            params["page_token"] = page_token
        payload: dict[str, Any] = self._client.get(
            "/v3/templates",
            params=params,
        ).json()
        if include_raw:
            return payload
        raw_templates: list[Any] = payload.get("templates") or payload.get("result") or []
        templates: list[dict[str, Any]] = [t for t in raw_templates if isinstance(t, dict)]
        summaries = [
            self._template_summary(t, index=i, include_ids=include_ids)
            for i, t in enumerate(templates, start=1)
        ]
        next_page_token = self._next_page_token(payload)
        return {
            "templates": summaries,
            "count": len(summaries),
            "next_page_token": next_page_token,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_template(self, template_id: str) -> dict[str, Any]:
        """Return one template with all versions.

        Use after ``list_templates(include_ids=True)``.
        """
        if not template_id:
            raise ValueError("template_id must be a non-empty string")
        return self._client.get(f"/v3/templates/{template_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_template(self, *, name: str, generation: str = "dynamic") -> dict[str, Any]:
        """Create a new template container.

        Returns the new template resource. Add a version with the version
        endpoints (not in this surface).
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        return self._client.post(
            "/v3/templates",
            json={"name": name, "generation": generation},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_template(self, template_id: str) -> dict[str, Any]:
        """Permanently delete a template. Destructive — confirm with the user first."""
        if not template_id:
            raise ValueError("template_id must be a non-empty string")
        self._client.delete(f"/v3/templates/{template_id}")
        return {"id": template_id, "deleted": True}

    # MARK: - Marketing contacts and lists

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_marketing_contacts(self) -> dict[str, Any]:
        """Return total contacts count and segment summary.

        Returns ``{"contact_count": ..., "billable_count": ...}``.
        """
        return self._client.get("/v3/marketing/contacts/count").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upsert_marketing_contacts(
        self,
        contacts: list[dict[str, Any]],
        *,
        list_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add or update up to 30,000 marketing contacts (async job).

        Returns ``{"job_id": ...}``. Each contact needs at least ``email``.
        """
        if not contacts:
            raise ValueError("contacts must be non-empty")
        body: dict[str, Any] = {"contacts": contacts}
        if list_ids is not None:
            body["list_ids"] = list_ids
        return self._client.put("/v3/marketing/contacts", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_LISTS_OUTPUT)
    def list_lists(
        self,
        *,
        page_size: int = 25,
        page_token: str | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List contact lists with compact summaries.

        Returns compact summaries with ``list_ref`` plus name,
        contact_count, and a ``next_page_token`` (or ``None``) drawn from
        the payload's ``_metadata.next`` cursor for paging through accounts
        with more than ``page_size`` lists. Raw list IDs are omitted by
        default — set ``include_ids=True`` when ``delete_list`` needs them.

        Pass the returned ``next_page_token`` back as ``page_token`` to fetch
        the next page.
        """
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        params: dict[str, Any] = {"page_size": page_size}
        if page_token is not None:
            params["page_token"] = page_token
        payload: dict[str, Any] = self._client.get(
            "/v3/marketing/lists",
            params=params,
        ).json()
        if include_raw:
            return payload
        raw_lists: list[Any] = payload.get("result") or []
        lists: list[dict[str, Any]] = [lst for lst in raw_lists if isinstance(lst, dict)]
        summaries = [
            self._list_summary(lst, index=i, include_ids=include_ids)
            for i, lst in enumerate(lists, start=1)
        ]
        next_page_token = self._next_page_token(payload)
        return {
            "lists": summaries,
            "count": len(summaries),
            "next_page_token": next_page_token,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_list(self, *, name: str) -> dict[str, Any]:
        """Create a contact list.

        Returns the new list resource.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        return self._client.post("/v3/marketing/lists", json={"name": name}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_list(self, list_id: str, *, delete_contacts: bool = False) -> dict[str, Any]:
        """Permanently delete a contact list. Destructive — confirm with the user first.

        Setting ``delete_contacts=True`` also removes the contacts from
        the account (not just the list).
        """
        if not list_id:
            raise ValueError("list_id must be a non-empty string")
        self._client.delete(
            f"/v3/marketing/lists/{list_id}",
            params={"delete_contacts": str(delete_contacts).lower()},
        )
        return {"id": list_id, "deleted": True}

    # MARK: - Suppressions

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_bounces(
        self,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> dict[str, Any]:
        """List recent bounces (failed deliveries).

        Returns the raw SendGrid payload. Times are Unix timestamps.
        """
        params: dict[str, Any] = {}
        if start_time is not None:
            params["start_time"] = start_time
        if end_time is not None:
            params["end_time"] = end_time
        return self._client.get(
            "/v3/suppression/bounces",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_blocks(self) -> dict[str, Any]:
        """List blocked addresses.

        Returns the raw SendGrid payload. Each entry has ``email``,
        ``status``, ``reason``, ``created``.
        """
        return self._client.get("/v3/suppression/blocks").json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_bounce(self, email: str) -> dict[str, Any]:
        """Remove an address from the bounce list. Destructive — confirm first.

        This re-enables future sends to the address.
        """
        if not email:
            raise ValueError("email must be a non-empty string")
        self._client.delete(f"/v3/suppression/bounces/{email}")
        return {"email": email, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_account_scopes(self) -> dict[str, Any]:
        """Return the API key's allowed scopes.

        Useful for debugging permission issues.
        """
        return self._client.get("/v3/scopes").json()
