"""WhatsApp Business Cloud API connector (Meta Graph)."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: - Constants

_DEFAULT_TEMPLATE_LIMIT = 25
_API_VERSION = "v23.0"


@toolset(prefix="whatsapp")
class WhatsAppBusinessToolSet:
    """A connector for the WhatsApp Business Cloud API.

    Args:
        access_token: System-user access token from the WABA dashboard.
        phone_number_id: Default phone number ID used when one is not
            passed explicitly to the per-method calls.
        graph_version: Graph API version (default ``"v23.0"``).
    """

    metadata = ProviderMetadata(
        name="whatsapp",
        display_name="WhatsApp Business",
        version="0.1.0",
        description="Send messages, templates, media, and manage WABA assets.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE, AuthMode.BEARER),
        scopes={
            "whatsapp_business_messaging": "Send business messages.",
            "whatsapp_business_management": "Manage WABA assets.",
        },
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url=("https://developers.facebook.com/docs/whatsapp/cloud-api/"),
        homepage_url="https://www.whatsapp.com/business/",
        tags=("social-media", "messaging", "meta"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        graph_version: str = _API_VERSION,
        base_url: str = "https://graph.facebook.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token or not phone_number_id:
            raise ValueError("access_token and phone_number_id are required")
        self.connection = connection
        self._version = graph_version
        self._phone_id = phone_number_id
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(access_token),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _phone_path(self, suffix: str, phone_id: str | None = None) -> str:
        pid = phone_id or self._phone_id
        return f"/{self._version}/{pid}{suffix}"

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def send_text(
        self,
        *,
        to: str,
        body: str,
        preview_url: bool = False,
        phone_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a text message.

        ``to`` is the recipient's WhatsApp number in E.164 format (e.g.
        ``"+15551234567"``). Returns the WhatsApp ``messages`` payload with
        the new message handle in ``messages[0].id`` -- pass it to
        :meth:`mark_message_read` if applicable.
        """
        if not to or not body:
            raise ValueError("to and body are required")
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": body, "preview_url": preview_url},
        }
        return self._client.post(self._phone_path("/messages", phone_id), json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def send_template(
        self,
        *,
        to: str,
        template_name: str,
        language_code: str,
        components: list[dict[str, Any]] | None = None,
        phone_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a templated message.

        ``template_name`` must reference a template approved in the WhatsApp
        Business Manager; discover available templates via
        :meth:`list_message_templates`. ``language_code`` is e.g.
        ``"en_US"``.
        """
        if not to or not template_name or not language_code:
            raise ValueError("to, template_name, and language_code are required")
        template: dict[str, Any] = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if components is not None:
            template["components"] = components
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": template,
        }
        return self._client.post(self._phone_path("/messages", phone_id), json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def send_media(
        self,
        *,
        to: str,
        media_type: str,
        link: str | None = None,
        media_id: str | None = None,
        caption: str | None = None,
        filename: str | None = None,
        phone_id: str | None = None,
    ) -> dict[str, Any]:
        """Send an image / audio / video / document by URL or media ID.

        Provide exactly one of ``link`` (public URL) or ``media_id``
        (uploaded asset). ``media_type`` is one of ``"image"``, ``"audio"``,
        ``"video"``, ``"document"``, or ``"sticker"``.
        """
        if not to:
            raise ValueError("to is required")
        if media_type not in {"image", "audio", "video", "document", "sticker"}:
            raise ValueError("media_type must be image/audio/video/document/sticker")
        if (link is None) == (media_id is None):
            raise ValueError("Provide exactly one of link or media_id")
        media: dict[str, Any] = {}
        if link is not None:
            media["link"] = link
        if media_id is not None:
            media["id"] = media_id
        if caption is not None:
            media["caption"] = caption
        if filename is not None:
            media["filename"] = filename
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": media_type,
            media_type: media,
        }
        return self._client.post(self._phone_path("/messages", phone_id), json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def mark_message_read(
        self,
        *,
        message_id: Any,
        phone_id: str | None = None,
    ) -> dict[str, Any]:
        """Mark an inbound message as read.

        ``message_id`` accepts a raw WhatsApp message handle (``"wamid..."``)
        or a message-summary dict from a previous send_* response.
        """
        resolved = self._resolve_message_id(message_id)
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": resolved,
        }
        return self._client.post(self._phone_path("/messages", phone_id), json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_media_metadata(self, media_id: str) -> dict[str, Any]:
        """Return metadata (including a temporary download URL) for media."""
        if not media_id:
            raise ValueError("media_id is required")
        return self._client.get(f"/{self._version}/{media_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_media(self, media_id: str) -> dict[str, Any]:
        """Delete an uploaded media asset.

        Destructive: the asset is removed and cannot be recovered.
        """
        if not media_id:
            raise ValueError("media_id is required")
        response = self._client.delete(f"/{self._version}/{media_id}")
        return {"media_id": media_id, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_phone_numbers(self, waba_id: str) -> dict[str, Any]:
        """List phone numbers owned by a WhatsApp Business Account."""
        if not waba_id:
            raise ValueError("waba_id is required")
        return self._client.get(f"/{self._version}/{waba_id}/phone_numbers").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_message_templates(
        self,
        waba_id: str,
        *,
        limit: int = _DEFAULT_TEMPLATE_LIMIT,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List message templates for a WABA.

        Best first tool to discover the template names you can pass to
        :meth:`send_template`. Returns compact summaries by default:
        ``template_ref``, ``name``, ``language``, ``category``, ``status``.
        Raw template IDs are omitted by default; pass ``include_ids=True``
        when needed. ``include_metadata=False`` returns the raw Graph response.
        """
        if not waba_id:
            raise ValueError("waba_id is required")
        payload: dict[str, Any] = self._client.get(
            f"/{self._version}/{waba_id}/message_templates",
            params={"limit": limit},
        ).json()
        if not include_metadata:
            return payload

        data: list[Any] = payload.get("data", []) or []
        templates: list[dict[str, Any]] = []
        for index, template in enumerate(data, start=1):
            if not isinstance(template, dict):
                continue
            template_dict = cast("dict[str, Any]", template)
            summary: dict[str, Any] = {
                "template_ref": f"template_{index}",
                "name": template_dict.get("name", ""),
                "language": template_dict.get("language", ""),
                "category": template_dict.get("category", ""),
                "status": template_dict.get("status", ""),
            }
            if include_ids:
                summary["template_id"] = template_dict.get("id", "")
            templates.append(summary)
        return {
            "templates": templates,
            "paging": payload.get("paging"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_message_template(
        self,
        *,
        waba_id: str,
        name: str,
        language: str,
        category: str,
        components: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create a message template (subject to Meta review)."""
        if not waba_id or not name or not language or not category:
            raise ValueError("waba_id, name, language, and category are required")
        if not components:
            raise ValueError("components must be non-empty")
        return self._client.post(
            f"/{self._version}/{waba_id}/message_templates",
            json={
                "name": name,
                "language": language,
                "category": category,
                "components": components,
            },
        ).json()

    # MARK: - Internal

    @staticmethod
    def _resolve_message_id(message: Any) -> str:
        if isinstance(message, dict):
            message_dict = cast("dict[str, Any]", message)
            for key in ("message_id", "id"):
                value: Any = message_dict.get(key)
                if isinstance(value, str) and value:
                    return value
            messages: Any = message_dict.get("messages")
            if isinstance(messages, list) and messages:
                first: Any = cast("list[Any]", messages)[0]
                if isinstance(first, dict):
                    first_dict = cast("dict[str, Any]", first)
                    value = first_dict.get("id")
                    if isinstance(value, str) and value:
                        return value
            raise ValueError("message dict must contain message_id, id, or messages[0].id")
        if isinstance(message, str):
            if not message:
                raise ValueError("message_id is required")
            return message
        raise ValueError("message_id must be a string or message dict")
