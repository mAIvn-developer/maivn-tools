"""Mailgun Messages / Domains / Events API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="mailgun")
class MailgunToolSet:
    """A connector for the Mailgun v3 API."""

    metadata = ProviderMetadata(
        name="mailgun",
        display_name="Mailgun",
        version="0.1.0",
        description="Send transactional email, manage domains, mailing lists, and logs.",
        auth_modes=(AuthMode.BASIC,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://documentation.mailgun.com/docs/mailgun/api-reference/",
        homepage_url="https://www.mailgun.com/",
        tags=("email", "transactional"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        domain: str | None = None,
        base_url: str = "https://api.mailgun.net",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._default_domain = domain
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BasicAuth("api", api_key),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _domain(self, domain: str | None) -> str:
        d = domain or self._default_domain
        if not d:
            raise ValueError("domain must be provided (constructor or method)")
        return d

    @staticmethod
    def _domain_summary(
        domain: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "domain_ref": f"domain_{index}",
            "name": domain.get("name", ""),
            "state": domain.get("state", ""),
            "type": domain.get("type", ""),
            "created_at": domain.get("created_at", ""),
        }
        if include_ids:
            summary["id"] = domain.get("id", "")
        return summary

    @staticmethod
    def _list_summary(
        mlist: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "list_ref": f"list_{index}",
            "address": mlist.get("address", ""),
            "name": mlist.get("name", ""),
            "members_count": mlist.get("members_count", 0),
            "description": mlist.get("description", ""),
        }
        if include_ids:
            summary["address_raw"] = mlist.get("address", "")
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
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        domain: str | None = None,
        tag: list[str] | None = None,
        template: str | None = None,
        template_variables: dict[str, Any] | None = None,
        delivery_time: str | None = None,
    ) -> dict[str, Any]:
        """Send a transactional email via the form-encoded ``/messages`` endpoint.

        Irreversible once sent — marked destructive. Always confirm
        recipients and subject with the user before calling.
        ``delivery_time`` is an RFC 2822 datetime for scheduled sends.
        Returns ``{"id": <queued message id>, "message": "Queued..."}``.
        """
        if not from_address or not subject:
            raise ValueError("from_address and subject must be non-empty")
        if text is None and html is None and template is None:
            raise ValueError("provide text, html, or template")
        params: dict[str, Any] = {
            "from": from_address,
            "to": to if isinstance(to, list) else [to],
            "subject": subject,
        }
        if text is not None:
            params["text"] = text
        if html is not None:
            params["html"] = html
        if cc is not None:
            params["cc"] = cc
        if bcc is not None:
            params["bcc"] = bcc
        if tag is not None:
            params["o:tag"] = tag
        if template is not None:
            params["template"] = template
        if template_variables is not None:
            import json as _json

            params["h:X-Mailgun-Variables"] = _json.dumps(template_variables)
        if delivery_time is not None:
            params["o:deliverytime"] = delivery_time
        return self._client.post(
            f"/v3/{self._domain(domain)}/messages",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_domains(
        self,
        *,
        limit: int = 25,
        skip: int = 0,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List Mailgun domains with compact summaries.

        Returns compact summaries with ``domain_ref`` plus name (the
        user-facing domain), state, type. Raw provider-internal IDs are
        omitted by default.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        payload: dict[str, Any] = self._client.get(
            "/v4/domains",
            params={"limit": limit, "skip": skip},
        ).json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("items") or []
        summaries = [
            self._domain_summary(cast("dict[str, Any]", d), index=i, include_ids=include_ids)
            for i, d in enumerate(items, start=1)
            if isinstance(d, dict)
        ]
        return {
            "domains": summaries,
            "count": len(summaries),
            "total_count": payload.get("total_count"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_domain(
        self,
        *,
        name: str,
        spam_action: str = "disabled",
        wildcard: bool = False,
    ) -> dict[str, Any]:
        """Add a domain (DNS verification required).

        Returns the new domain resource and DNS records to add.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        return self._client.post(
            "/v4/domains",
            params={
                "name": name,
                "spam_action": spam_action,
                "wildcard": str(wildcard).lower(),
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_domain(self, domain_name: str) -> dict[str, Any]:
        """Permanently delete a domain. Destructive — confirm with the user first."""
        if not domain_name:
            raise ValueError("domain_name must be a non-empty string")
        return self._client.delete(f"/v4/domains/{domain_name}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_events(
        self,
        *,
        domain: str | None = None,
        event: str | None = None,
        begin: str | None = None,
        end: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Query the events log for a domain.

        ``event`` filters by type (``delivered``, ``opened``, ``failed``,
        ``bounced``, ``complained``). Returns the raw Mailgun events
        payload with pagination links.
        """
        params: dict[str, Any] = {"limit": limit}
        if event is not None:
            params["event"] = event
        if begin is not None:
            params["begin"] = begin
        if end is not None:
            params["end"] = end
        return self._client.get(
            f"/v3/{self._domain(domain)}/events",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_bounces(
        self,
        *,
        domain: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List bounces for a domain.

        Returns the raw provider payload — each item has ``address``,
        ``code``, ``error``, ``created_at``.
        """
        return self._client.get(
            f"/v3/{self._domain(domain)}/bounces",
            params={"limit": limit},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_bounce(
        self,
        address: str,
        *,
        domain: str | None = None,
    ) -> dict[str, Any]:
        """Remove an address from the bounce list. Destructive — confirm first.

        Re-enables future sends to the address.
        """
        if not address:
            raise ValueError("address must be a non-empty string")
        return self._client.delete(
            f"/v3/{self._domain(domain)}/bounces/{address}",
        ).json()

    # MARK: - Mailing lists

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_mailing_lists(
        self,
        *,
        limit: int = 25,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List mailing lists with compact summaries.

        Returns compact summaries with ``list_ref`` plus address (the
        user-facing list email), name, members_count.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        payload: dict[str, Any] = self._client.get(
            "/v3/lists/pages", params={"limit": limit}
        ).json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("items") or []
        summaries = [
            self._list_summary(cast("dict[str, Any]", ml), index=i, include_ids=include_ids)
            for i, ml in enumerate(items, start=1)
            if isinstance(ml, dict)
        ]
        return {"lists": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_mailing_list(
        self,
        *,
        address: str,
        name: str | None = None,
        description: str | None = None,
        access_level: str = "readonly",
    ) -> dict[str, Any]:
        """Create a mailing list.

        ``address`` is the list email (e.g. ``announce@example.com``).
        Returns the new list resource.
        """
        if not address:
            raise ValueError("address must be a non-empty string")
        params: dict[str, Any] = {"address": address, "access_level": access_level}
        if name is not None:
            params["name"] = name
        if description is not None:
            params["description"] = description
        return self._client.post("/v3/lists", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_list_member(
        self,
        list_address: str,
        *,
        address: str,
        name: str | None = None,
        subscribed: bool = True,
        upsert: bool = True,
    ) -> dict[str, Any]:
        """Add a member to a mailing list.

        ``upsert=True`` updates the member if they already exist. Returns
        the new/updated member resource.
        """
        if not list_address or not address:
            raise ValueError("list_address and address must be non-empty")
        params: dict[str, Any] = {
            "address": address,
            "subscribed": str(subscribed).lower(),
            "upsert": str(upsert).lower(),
        }
        if name is not None:
            params["name"] = name
        return self._client.post(
            f"/v3/lists/{list_address}/members",
            params=params,
        ).json()
