"""Amazon Simple Email Service (SES) v2 REST connector.

AWS APIs require SigV4 request signing. This connector intentionally
takes an :class:`AuthStrategy` so callers can plug in their own signer
(typically by wrapping ``botocore.auth.SigV4Auth`` or by using a
``HttpTransport`` that signs requests on the way out). The default
``NoAuth`` strategy lets unit tests call the surface without a real
account.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.base import AuthStrategy, NoAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_IDENTITIES_OUTPUT, LIST_TEMPLATES_OUTPUT


@toolset(prefix="ses")
class AmazonSESToolSet:
    """A connector for Amazon SES v2 REST.

    Args:
        region: AWS region, e.g. ``"us-east-1"``.
        auth: ``AuthStrategy`` that signs the request (typically SigV4).
            Defaults to :class:`NoAuth`, which is suitable for mocked tests
            and for setups where the underlying transport handles signing.
        base_url: Optional override of the regional endpoint.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="amazon_ses",
        display_name="Amazon SES",
        version="0.1.0",
        description="Send email via Amazon SES v2 (SigV4 auth required for live use).",
        auth_modes=(AuthMode.CUSTOM,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.aws.amazon.com/ses/latest/APIReference-V2/",
        homepage_url="https://aws.amazon.com/ses/",
        tags=("email", "transactional", "aws"),
    )

    def __init__(
        self,
        *,
        region: str,
        auth: AuthStrategy | None = None,
        base_url: str | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not region:
            raise ValueError("region is required")
        self.connection = connection
        self._region = region
        url = base_url or f"https://email.{region}.amazonaws.com"
        self._client = HttpClient(
            base_url=url.rstrip("/"),
            auth=auth or NoAuth(),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @staticmethod
    def _identity_summary(
        identity: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "identity_ref": f"identity_{index}",
            "identity_name": identity.get("IdentityName", ""),
            "identity_type": identity.get("IdentityType", ""),
            "sending_enabled": identity.get("SendingEnabled"),
            "verification_status": identity.get("VerificationStatus", ""),
        }
        if include_ids:
            summary["identity_arn"] = identity.get("IdentityArn", "")
        return summary

    @staticmethod
    def _template_summary(
        template: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        return {
            "template_ref": f"template_{index}",
            "template_name": template.get("TemplateName", ""),
            "created_timestamp": template.get("CreatedTimestamp", ""),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def send_email(
        self,
        *,
        from_address: str,
        to: list[str],
        subject: str,
        text_body: str | None = None,
        html_body: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        configuration_set_name: str | None = None,
        tags: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Send a simple email via the SES v2 SendEmail API. Irreversible once sent.

        Marked destructive because emails cannot be unsent. Always confirm
        recipients and subject with the user before calling. Returns
        ``{"MessageId": ...}``.
        """
        if not from_address or not subject or not to:
            raise ValueError("from_address, to, and subject must be non-empty")
        if text_body is None and html_body is None:
            raise ValueError("provide text_body or html_body")
        content_body: dict[str, Any] = {}
        if text_body is not None:
            content_body["Text"] = {"Data": text_body}
        if html_body is not None:
            content_body["Html"] = {"Data": html_body}
        payload: dict[str, Any] = {
            "FromEmailAddress": from_address,
            "Destination": {"ToAddresses": to},
            "Content": {
                "Simple": {
                    "Subject": {"Data": subject},
                    "Body": content_body,
                }
            },
        }
        if cc is not None:
            payload["Destination"]["CcAddresses"] = cc
        if bcc is not None:
            payload["Destination"]["BccAddresses"] = bcc
        if configuration_set_name is not None:
            payload["ConfigurationSetName"] = configuration_set_name
        if tags is not None:
            payload["EmailTags"] = tags
        return self._client.post("/v2/email/outbound-emails", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def send_template(
        self,
        *,
        from_address: str,
        to: list[str],
        template_name: str,
        template_data: dict[str, Any],
        configuration_set_name: str | None = None,
    ) -> dict[str, Any]:
        """Send a templated email. Irreversible once sent.

        Marked destructive because emails cannot be unsent. Always confirm
        recipients with the user before calling.
        """
        if not from_address or not template_name or not to:
            raise ValueError("from_address, template_name, and to must be non-empty")
        import json as _json

        payload: dict[str, Any] = {
            "FromEmailAddress": from_address,
            "Destination": {"ToAddresses": to},
            "Content": {
                "Template": {
                    "TemplateName": template_name,
                    "TemplateData": _json.dumps(template_data),
                }
            },
        }
        if configuration_set_name is not None:
            payload["ConfigurationSetName"] = configuration_set_name
        return self._client.post("/v2/email/outbound-emails", json=payload).json()

    # MARK: - Identities

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_IDENTITIES_OUTPUT)
    def list_identities(
        self,
        *,
        page_size: int = 25,
        next_token: str | None = None,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List sender identities (email addresses and domains) with compact summaries.

        Returns compact summaries with ``identity_ref`` plus
        identity_name (user-facing email/domain), identity_type,
        sending_enabled. Raw ARNs are omitted by default.
        """
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        params: dict[str, Any] = {"PageSize": page_size}
        if next_token is not None:
            params["NextToken"] = next_token
        payload: dict[str, Any] = self._client.get("/v2/email/identities", params=params).json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("EmailIdentities") or []
        summaries: list[dict[str, Any]] = [
            self._identity_summary(cast("dict[str, Any]", i), index=idx, include_ids=include_ids)
            for idx, i in enumerate(items, start=1)
            if isinstance(i, dict)
        ]
        return {
            "identities": summaries,
            "count": len(summaries),
            "next_token": payload.get("NextToken"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_identity(self, identity: str) -> dict[str, Any]:
        """Return DKIM / verification status for an identity.

        Identity is the user-facing email or domain.
        """
        if not identity:
            raise ValueError("identity must be a non-empty string")
        return self._client.get(f"/v2/email/identities/{identity}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_identity(self, identity: str) -> dict[str, Any]:
        """Create a new verified identity (email or domain).

        Returns DKIM tokens for DNS setup if the identity is a domain.
        """
        if not identity:
            raise ValueError("identity must be a non-empty string")
        return self._client.post(
            "/v2/email/identities",
            json={"EmailIdentity": identity},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_identity(self, identity: str) -> dict[str, Any]:
        """Permanently delete an identity. Destructive — confirm with the user first.

        After deletion the address/domain can no longer send mail.
        """
        if not identity:
            raise ValueError("identity must be a non-empty string")
        return self._client.delete(f"/v2/email/identities/{identity}").json()

    # MARK: - Templates

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_TEMPLATES_OUTPUT)
    def list_templates(
        self,
        *,
        page_size: int = 25,
        next_token: str | None = None,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List email templates with compact summaries.

        Returns compact summaries with ``template_ref`` plus
        template_name (user-facing), created_timestamp. SES uses
        template_name as the only identifier.
        """
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")
        params: dict[str, Any] = {"PageSize": page_size}
        if next_token is not None:
            params["NextToken"] = next_token
        payload: dict[str, Any] = self._client.get("/v2/email/templates", params=params).json()
        if include_raw:
            return payload
        templates: list[Any] = payload.get("TemplatesMetadata") or []
        summaries: list[dict[str, Any]] = [
            self._template_summary(cast("dict[str, Any]", t), index=i, include_ids=False)
            for i, t in enumerate(templates, start=1)
            if isinstance(t, dict)
        ]
        return {
            "templates": summaries,
            "count": len(summaries),
            "next_token": payload.get("NextToken"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_template(
        self,
        *,
        name: str,
        subject_part: str,
        text_part: str | None = None,
        html_part: str | None = None,
    ) -> dict[str, Any]:
        """Create a template.

        ``subject_part`` and the body parts support handlebars-style
        ``{{variable}}`` substitution.
        """
        if not name or not subject_part:
            raise ValueError("name and subject_part must be non-empty")
        content: dict[str, Any] = {"Subject": subject_part}
        if text_part is not None:
            content["Text"] = text_part
        if html_part is not None:
            content["Html"] = html_part
        return self._client.post(
            "/v2/email/templates",
            json={"TemplateName": name, "TemplateContent": content},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_template(self, name: str) -> dict[str, Any]:
        """Permanently delete a template by name. Destructive — confirm first."""
        if not name:
            raise ValueError("name must be a non-empty string")
        return self._client.delete(f"/v2/email/templates/{name}").json()

    # MARK: - Suppression

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_suppressed_destinations(
        self,
        *,
        page_size: int = 25,
        next_token: str | None = None,
        reasons: list[str] | None = None,
    ) -> dict[str, Any]:
        """List addresses currently suppressed.

        ``reasons`` filters by ``BOUNCE`` and/or ``COMPLAINT``. Returns
        the raw provider payload with ``EmailAddress`` and ``Reason`` per
        entry.
        """
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        params: dict[str, Any] = {"PageSize": page_size}
        if next_token is not None:
            params["NextToken"] = next_token
        if reasons is not None:
            params["Reasons"] = ",".join(reasons)
        return self._client.get(
            "/v2/email/suppression/addresses",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def remove_suppressed_destination(self, email: str) -> dict[str, Any]:
        """Remove an address from the account-level suppression list.

        Destructive — confirm first. Re-enables future sends to the
        address.
        """
        if not email:
            raise ValueError("email must be a non-empty string")
        return self._client.delete(
            f"/v2/email/suppression/addresses/{email}",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_account(self) -> dict[str, Any]:
        """Return account-level send quota and metadata.

        Returns sending limits, reputation status, and configuration set
        defaults.
        """
        return self._client.get("/v2/email/account").json()
