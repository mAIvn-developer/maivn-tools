"""Twilio Programmable Messaging + Verify REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast
from urllib.parse import quote, urlencode

from maivn import toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="twilio")
class TwilioToolSet:
    """A connector for Twilio's REST API.

    Args:
        account_sid: Twilio account SID.
        auth_token: Twilio auth token.
    """

    metadata = ProviderMetadata(
        name="twilio",
        display_name="Twilio",
        version="0.1.0",
        description="Messaging (SMS/MMS), Verify, Voice, and lookups.",
        auth_modes=(AuthMode.BASIC,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://www.twilio.com/docs/usage/api",
        homepage_url="https://www.twilio.com/",
        tags=("messaging", "auth", "verification"),
    )

    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        base_url: str = "https://api.twilio.com",
        verify_url: str = "https://verify.twilio.com",
        lookup_url: str = "https://lookups.twilio.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not account_sid or not auth_token:
            raise ValueError("account_sid and auth_token are required")
        self.connection = connection
        self._account_sid = account_sid
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BasicAuth(account_sid, auth_token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )
        self._verify_client = HttpClient(
            base_url=verify_url.rstrip("/"),
            auth=BasicAuth(account_sid, auth_token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )
        self._lookup_client = HttpClient(
            base_url=lookup_url.rstrip("/"),
            auth=BasicAuth(account_sid, auth_token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _form_post(
        self,
        client: HttpClient,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return client.post(
            path,
            data=urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ).json()

    # MARK: - Summary helpers

    @staticmethod
    def _message_summary(
        message: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "message_ref": f"message_{index}",
            "from": message.get("from", ""),
            "to": message.get("to", ""),
            "status": message.get("status", ""),
            "direction": message.get("direction", ""),
            "body": message.get("body", ""),
            "date_sent": message.get("date_sent", ""),
            "price": message.get("price", ""),
        }
        if include_ids:
            summary["message_sid"] = message.get("sid", "")
        return summary

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def send_message(
        self,
        *,
        to: str,
        body: str | None = None,
        from_: str | None = None,
        messaging_service_sid: str | None = None,
        media_url: list[str] | None = None,
    ) -> dict[str, Any]:
        """Send an SMS or MMS to a phone number.

        Destructive — this triggers a real billable message to a real
        phone number. Always confirm the recipient (``to``) and content
        (``body``) with the user before calling. Returns the Twilio
        message resource (``sid``, ``status``, ``date_created``).
        """
        if not to:
            raise ValueError("to is required")
        if not body and not media_url:
            raise ValueError("body or media_url is required")
        if not from_ and not messaging_service_sid:
            raise ValueError("from_ or messaging_service_sid is required")
        payload: dict[str, Any] = {"To": to}
        if body is not None:
            payload["Body"] = body
        if from_ is not None:
            payload["From"] = from_
        if messaging_service_sid is not None:
            payload["MessagingServiceSid"] = messaging_service_sid
        if media_url is not None:
            payload["MediaUrl"] = media_url
        return self._form_post(
            self._client,
            f"/2010-04-01/Accounts/{self._account_sid}/Messages.json",
            payload,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_messages(
        self,
        *,
        date_sent: str | None = None,
        from_: str | None = None,
        to: str | None = None,
        page_size: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List recent messages.

        Returns ``{"messages": [...]}`` with ``message_ref``, ``from``,
        ``to``, ``status``, ``direction``, ``body``, ``date_sent``,
        ``price``. Raw ``message_sid`` is omitted by default.
        """
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        params: dict[str, Any] = {"PageSize": page_size}
        if date_sent is not None:
            params["DateSent"] = date_sent
        if from_ is not None:
            params["From"] = from_
        if to is not None:
            params["To"] = to
        raw = self._client.get(
            f"/2010-04-01/Accounts/{self._account_sid}/Messages.json",
            params=params,
        ).json()
        payload: dict[str, Any] = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
        messages_field: object = payload.get("messages", [])
        messages_list: list[Any] = (
            cast("list[Any]", messages_field) if isinstance(messages_field, list) else []
        )
        raw_messages: list[dict[str, Any]] = [
            cast("dict[str, Any]", m) for m in messages_list if isinstance(m, dict)
        ]
        summaries = [
            self._message_summary(message, index=index, include_ids=include_ids)
            for index, message in enumerate(raw_messages, start=1)
        ]
        result: dict[str, Any] = {"messages": summaries}
        for key in ("next_page_uri", "previous_page_uri", "page"):
            if key in payload:
                result[key] = payload[key]
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_message(self, message_sid: str) -> dict[str, Any]:
        """Return a single message by SID.

        Returns the raw Twilio message resource — full body, status,
        delivery timestamps, and price.
        """
        if not message_sid:
            raise ValueError("message_sid is required")
        return self._client.get(
            f"/2010-04-01/Accounts/{self._account_sid}/Messages/{message_sid}.json"
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def start_verification(
        self,
        *,
        service_sid: str,
        to: str,
        channel: str = "sms",
        custom_message: str | None = None,
    ) -> dict[str, Any]:
        """Send a Verify OTP to a recipient.

        Destructive — sends a real billable OTP to a real phone/email.
        Confirm the recipient with the user before calling.
        ``channel`` is sms / call / email / whatsapp.
        """
        if not service_sid or not to:
            raise ValueError("service_sid and to are required")
        if channel not in {"sms", "call", "email", "whatsapp"}:
            raise ValueError("channel must be sms/call/email/whatsapp")
        payload: dict[str, Any] = {"To": to, "Channel": channel}
        if custom_message is not None:
            payload["CustomMessage"] = custom_message
        return self._form_post(
            self._verify_client,
            f"/v2/Services/{service_sid}/Verifications",
            payload,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def check_verification(
        self,
        *,
        service_sid: str,
        to: str,
        code: str,
    ) -> dict[str, Any]:
        """Verify the OTP code the user submitted.

        Returns the Twilio verification-check resource. ``status`` will
        be ``approved`` on success.
        """
        if not service_sid or not to or not code:
            raise ValueError("service_sid, to, and code are required")
        return self._form_post(
            self._verify_client,
            f"/v2/Services/{service_sid}/VerificationCheck",
            {"To": to, "Code": code},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def make_call(
        self,
        *,
        to: str,
        from_: str,
        url: str | None = None,
        twiml: str | None = None,
    ) -> dict[str, Any]:
        """Place an outbound call (Twilio Voice).

        Destructive — places a real billable phone call. Confirm the
        recipient with the user before calling. Provide exactly one of
        ``url`` (TwiML over HTTP) or ``twiml`` (inline TwiML).
        """
        if not to or not from_:
            raise ValueError("to and from_ are required")
        if (url is None) == (twiml is None):
            raise ValueError("Provide exactly one of url or twiml")
        payload: dict[str, Any] = {"To": to, "From": from_}
        if url is not None:
            payload["Url"] = url
        if twiml is not None:
            payload["Twiml"] = twiml
        return self._form_post(
            self._client,
            f"/2010-04-01/Accounts/{self._account_sid}/Calls.json",
            payload,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def lookup_phone_number(
        self,
        phone_number: str,
        *,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Look up phone-number metadata via Lookup v2.

        Returns the raw Twilio lookup payload — carrier, line type, country.
        Useful for validating a number before send_message or make_call.
        """
        if not phone_number:
            raise ValueError("phone_number is required")
        params: dict[str, Any] = {}
        if fields is not None:
            params["Fields"] = ",".join(fields)
        return self._lookup_client.get(
            f"/v2/PhoneNumbers/{quote(phone_number, safe='+')}",
            params=params or None,
        ).json()
