"""SMTP send connector.

The connector wraps :mod:`smtplib` behind a small protocol so tests can
inject a fake client. The default factory uses :class:`smtplib.SMTP_SSL` on
port 465. Set ``use_ssl=False`` and ``starttls=True`` to use STARTTLS on the
submission port (587).

The single tool exposed by :class:`SMTPToolSet` is ``send_email``. It builds
a multipart MIME message from the supplied recipients, body, and optional
attachments and submits it to the configured server.
"""

# pyright: strict

from __future__ import annotations

import mimetypes
import smtplib
from collections.abc import Callable, Iterable, Mapping
from email.message import EmailMessage
from typing import Any, Protocol

from maivn import toolify, toolset

from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet

# MARK: - Types

# smtplib status replies are ``(code, message)`` pairs; ``sendmail`` and
# ``send_message`` return a mapping of refused recipients to such pairs.
SmtpReply = tuple[int, bytes]
SmtpRefused = dict[str, SmtpReply]


class SmtpClient(Protocol):
    """The subset of :class:`smtplib.SMTP` the connector uses."""

    def starttls(self, *args: Any, **kwargs: Any) -> SmtpReply: ...

    def login(self, user: str, password: str) -> SmtpReply: ...

    def send_message(
        self,
        msg: EmailMessage,
        from_addr: str | None = None,
        to_addrs: Iterable[str] | None = None,
    ) -> SmtpRefused: ...

    def sendmail(
        self,
        from_addr: str,
        to_addrs: Iterable[str],
        msg: bytes | str,
    ) -> SmtpRefused: ...

    def noop(self) -> SmtpReply: ...

    def ehlo(self, name: str | None = None) -> SmtpReply: ...

    def helo(self, name: str | None = None) -> SmtpReply: ...

    def quit(self) -> SmtpReply: ...


SmtpClientFactory = Callable[[], SmtpClient]


@toolset(prefix="smtp")
class SMTPToolSet:
    """An outbound SMTP connector.

    Args:
        host: SMTP server hostname.
        username: Login name. Set to ``""`` to skip authentication.
        password: Login secret. Never logged.
        sender: Default ``From`` address.
        port: TCP port. Defaults to ``465`` (SMTP over SSL).
        use_ssl: Whether to use :class:`smtplib.SMTP_SSL`. Defaults to True.
        starttls: Whether to issue STARTTLS after connecting. Mutually
            exclusive with ``use_ssl``.
        client_factory: Optional factory returning a pre-configured
            :class:`SmtpClient`. Used for tests; when omitted the connector
            builds a fresh client per call.
    """

    # MARK: - Lifecycle

    metadata = ProviderMetadata(
        name="smtp",
        display_name="SMTP",
        version="0.1.0",
        description="Send outbound email via an SMTP server.",
        auth_modes=(AuthMode.BASIC, AuthMode.NONE),
        capabilities=frozenset({ProviderCapability.WRITE}),
        tags=("email", "smtp"),
    )

    def __init__(
        self,
        *,
        host: str = "",
        username: str = "",
        password: str = "",
        sender: str = "",
        port: int = 465,
        use_ssl: bool = True,
        starttls: bool = False,
        client_factory: SmtpClientFactory | None = None,
    ) -> None:
        if use_ssl and starttls:
            raise ValueError("Set exactly one of use_ssl or starttls")
        if client_factory is None:
            if not host:
                raise ValueError("host is required when client_factory is not supplied")
            if not sender:
                raise ValueError("sender is required")

            def _default_factory() -> SmtpClient:
                if use_ssl:
                    return smtplib.SMTP_SSL(host=host, port=port)  # type: ignore[return-value]
                return smtplib.SMTP(host=host, port=port)  # type: ignore[return-value]

            self._client_factory = _default_factory
        else:
            if not sender:
                raise ValueError("sender is required")
            self._client_factory = client_factory
        self._username = username
        self._password = password
        self._sender = sender
        self._starttls = starttls
        self.connection = None

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def validate_connection(self) -> dict[str, Any]:
        """Connect, authenticate (if configured), NOOP, and return server info.

        Use this once at startup to confirm the SMTP credentials are
        working before issuing :meth:`send_email`. Returns ``{"ok": bool,
        "ehlo": ..., "noop": ..., "sender": ..., "authenticated": bool}``.
        """
        client = self._client_factory()
        info: dict[str, Any] = {"ok": False}
        try:
            if self._starttls:
                client.starttls()
            ehlo_result: SmtpReply | None = None
            try:
                ehlo_result = client.ehlo()
            except Exception:  # noqa: BLE001 - fall back to HELO if EHLO unsupported
                try:
                    ehlo_result = client.helo()
                except Exception:  # noqa: BLE001
                    ehlo_result = None
            if self._username:
                client.login(self._username, self._password)
            noop_result: SmtpReply | None = None
            try:
                noop_result = client.noop()
            except Exception:  # noqa: BLE001 - NOOP is optional on some servers
                noop_result = None
            info = {
                "ok": True,
                "ehlo": _summarize_smtp_result(ehlo_result),
                "noop": _summarize_smtp_result(noop_result),
                "sender": self._sender,
                "authenticated": bool(self._username),
            }
        finally:
            try:
                client.quit()
            except Exception:  # noqa: BLE001
                pass
        return info

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def send_raw_email(
        self,
        raw_message: str | bytes,
        recipients: list[str],
        *,
        sender: str | None = None,
    ) -> dict[str, Any]:
        """Send a pre-built MIME message via the SMTP ``MAIL FROM``/``RCPT TO`` flow.

        Use when you already have a fully-formed RFC 822 message (e.g.
        from an IMAP fetch or a templating engine). For ordinary
        composition prefer :meth:`send_email`. Returns ``{"accepted":
        [...], "refused": {...}, "sender": ...}``.
        """
        if not recipients:
            raise ValueError("recipients must contain at least one address")
        if not raw_message:
            raise ValueError("raw_message must not be empty")
        from_addr = sender or self._sender
        if not from_addr:
            raise ValueError("sender is required")
        client = self._client_factory()
        try:
            if self._starttls:
                client.starttls()
            if self._username:
                client.login(self._username, self._password)
            refused = client.sendmail(from_addr, list(recipients), raw_message) or {}
        finally:
            try:
                client.quit()
            except Exception:  # noqa: BLE001
                pass
        return {
            "accepted": [r for r in recipients if r not in refused],
            "refused": dict(refused),
            "sender": from_addr,
        }

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
        attachments: list[Mapping[str, Any]] | None = None,
        sender: str | None = None,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        """Send an email and return the rcpt status reported by the server.

        Supply either ``body_text`` or ``body_html`` (or both for a
        multipart/alternative). Each entry in ``attachments`` must be a
        mapping with ``filename`` and ``content`` (bytes or str) plus an
        optional ``content_type``. Returns ``{"accepted": [...],
        "refused": {...}, "subject": ..., "to": [...]}``. Always confirm
        the recipient list with the user before calling in an
        interactive agent loop.
        """
        if not to:
            raise ValueError("to must contain at least one recipient")
        if body_text is None and body_html is None:
            raise ValueError("body_text or body_html must be supplied")
        message = _build_message(
            to=to,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
            sender=sender or self._sender,
            reply_to=reply_to,
        )
        recipients = list(to) + list(cc or []) + list(bcc or [])
        client = self._client_factory()
        try:
            if self._starttls:
                client.starttls()
            if self._username:
                client.login(self._username, self._password)
            refused = client.send_message(message, to_addrs=recipients) or {}
        finally:
            try:
                client.quit()
            except Exception:  # noqa: BLE001 - cleanup must never raise
                pass
        return {
            "accepted": [r for r in recipients if r not in refused],
            "refused": dict(refused),
            "subject": subject,
            "to": list(to),
        }


# MARK: - Helpers


def _summarize_smtp_result(result: SmtpReply | None) -> dict[str, Any] | None:
    """Coerce smtplib ``(code, msg)`` tuples to JSON-safe dicts."""
    if result is None:
        return None
    code, raw = result
    try:
        msg = raw.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        msg = repr(raw)
    return {"code": code, "message": msg}


def _build_message(
    *,
    to: list[str],
    subject: str,
    body_text: str | None,
    body_html: str | None,
    cc: list[str] | None,
    bcc: list[str] | None,
    attachments: list[Mapping[str, Any]] | None,
    sender: str,
    reply_to: str | None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    if reply_to:
        msg["Reply-To"] = reply_to

    if body_text is None:
        msg.set_content("")
    else:
        msg.set_content(body_text)
    if body_html is not None:
        msg.add_alternative(body_html, subtype="html")

    for attachment in attachments or []:
        filename = str(attachment["filename"])
        content = attachment["content"]
        if isinstance(content, str):
            content = content.encode("utf-8")
        if not isinstance(content, (bytes, bytearray)):
            raise TypeError(f"Attachment {filename!r} content must be bytes or string")
        maintype_subtype = str(attachment.get("content_type") or "")
        if maintype_subtype:
            maintype, _, subtype = maintype_subtype.partition("/")
            if not subtype:
                subtype = "octet-stream"
        else:
            guessed, _ = mimetypes.guess_type(filename)
            if guessed:
                maintype, _, subtype = guessed.partition("/")
            else:
                maintype, subtype = "application", "octet-stream"
        msg.add_attachment(
            bytes(content),
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )
    return msg
