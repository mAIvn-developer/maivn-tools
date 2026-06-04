"""IMAP mailbox connector.

The connector wraps :mod:`imaplib` behind a small protocol so tests can
inject a fake client. By default it uses :class:`imaplib.IMAP4_SSL` and
authenticates with username / password credentials.

Read tools include mailbox enumeration, status, search, and fetch. Write
tools cover flag changes, copy/move/append, and mailbox CRUD. Destructive
tools (delete message, expunge, delete mailbox) are tagged so hosts can
filter them out with ``exclude_tags=["destructive"]``.
"""

# pyright: strict

from __future__ import annotations

import email
import imaplib
from collections.abc import Callable, Sequence
from email.message import Message
from email.utils import parseaddr
from typing import Any, Protocol, cast

from maivn import toolify, toolset

from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet

# MARK: - Constants

_DEFAULT_SEARCH_LIMIT = 25
_METADATA_SUMMARY_MAX = 10

# An IMAP command returns ``(status, data)`` where ``data`` is a sequence of
# heterogeneous parts (bytes lines, ``(descriptor, body)`` tuples, or
# ``None``). The element type is ``object`` so callers must narrow via the
# isinstance guards below rather than leaking ``Any``. ``Sequence`` (covariant)
# lets the concrete :mod:`imaplib` return types satisfy this protocol.
ImapResponse = tuple[str, Sequence[object]]


# MARK: - Client protocol


class ImapClient(Protocol):
    """The subset of :class:`imaplib.IMAP4` the connector uses."""

    def login(self, user: str, password: str) -> ImapResponse: ...

    def logout(self) -> ImapResponse: ...

    def list(self, directory: str = "", pattern: str = "*") -> ImapResponse: ...

    def select(self, mailbox: str = "INBOX", readonly: bool = True) -> ImapResponse: ...

    def search(self, charset: str | None, *criteria: str) -> ImapResponse: ...

    def fetch(self, message_set: str, message_parts: str) -> ImapResponse: ...

    def status(self, mailbox: str, names: str) -> ImapResponse: ...

    def create(self, mailbox: str) -> ImapResponse: ...

    def delete(self, mailbox: str) -> ImapResponse: ...

    def rename(self, oldmailbox: str, newmailbox: str) -> ImapResponse: ...

    def subscribe(self, mailbox: str) -> ImapResponse: ...

    def unsubscribe(self, mailbox: str) -> ImapResponse: ...

    def store(self, message_set: str, command: str, flags: str) -> ImapResponse: ...

    def copy(self, message_set: str, new_mailbox: str) -> ImapResponse: ...

    def append(
        self,
        mailbox: str,
        flags: str,
        # ``Any`` matches imaplib's private ``_TimeLike | None`` stub; the
        # connector only ever passes ``None`` here.
        date_time: Any,
        message: bytes,
    ) -> ImapResponse: ...

    def expunge(self) -> ImapResponse: ...

    def close(self) -> ImapResponse: ...

    def noop(self) -> ImapResponse: ...

    def capability(self) -> ImapResponse: ...


ImapClientFactory = Callable[[], ImapClient]


@toolset(prefix="imap")
class IMAPToolSet:
    """A read-only IMAP connector.

    Args:
        host: IMAP server hostname.
        username: Login name.
        password: Login secret. Never logged.
        port: TCP port. Defaults to ``993`` (IMAP4 over SSL).
        use_ssl: Whether to use :class:`imaplib.IMAP4_SSL`. Defaults to True.
        client_factory: Optional factory returning a pre-configured
            :class:`ImapClient`. Used for tests; when omitted the connector
            builds an ``IMAP4_SSL`` (or ``IMAP4``) client per call.
    """

    metadata = ProviderMetadata(
        name="imap",
        display_name="IMAP mailbox",
        version="0.1.0",
        description="Read and modify an IMAP mailbox.",
        auth_modes=(AuthMode.BASIC,),
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
            }
        ),
        tags=("email", "imap"),
    )

    def __init__(
        self,
        *,
        host: str = "",
        username: str = "",
        password: str = "",
        port: int = 993,
        use_ssl: bool = True,
        client_factory: ImapClientFactory | None = None,
    ) -> None:
        if client_factory is None:
            if not host or not username:
                raise ValueError("host, username, and password are required")
            self._client_factory: ImapClientFactory = lambda: (
                imaplib.IMAP4_SSL(host=host, port=port)
                if use_ssl
                else imaplib.IMAP4(host=host, port=port)
            )
        else:
            self._client_factory = client_factory
        self._username = username
        self._password = password
        self.connection = None

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_mailboxes(self, pattern: str = "*") -> list[str]:
        """Return mailbox names matching ``pattern``.

        Mailbox names (e.g. ``"INBOX"``, ``"Archive/Projects"``) are the
        natural reference for follow-up tools like
        :meth:`search_messages`, :meth:`mailbox_status`, and
        :meth:`copy_message`.
        """
        client = self._open()
        try:
            status, raw = client.list(pattern=pattern)
            if status != "OK":
                raise RuntimeError(f"IMAP LIST failed: {status}")
            mailboxes: list[str] = []
            for entry in raw or []:
                if entry is None:
                    continue
                if isinstance(entry, bytes):
                    text = entry.decode("utf-8", errors="replace")
                elif isinstance(entry, str):
                    text = entry
                else:
                    text = str(entry)
                mailboxes.append(_parse_mailbox(text))
            return mailboxes
        finally:
            _safe_logout(client)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_messages(
        self,
        mailbox: str = "INBOX",
        criteria: str = "ALL",
        *,
        limit: int = _DEFAULT_SEARCH_LIMIT,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """Search a mailbox using IMAP search criteria.

        Best first tool for IMAP triage. By default, returns compact
        human-readable summaries: each message gets a stable
        ``message_ref`` (``message_1``, ``message_2``, ...), ``uid``,
        ``sender``, ``subject``, ``received_at`` (Date header), and
        ``flags``. Summary mode caps ``limit`` at 10 (one ENVELOPE fetch
        per UID) to stay fast. UIDs are kept in the result because
        follow-up tools (:meth:`fetch_message`, :meth:`mark_read`,
        :meth:`delete_message`) need them. Set ``include_metadata=False``
        to receive just a list of UIDs (the old wire format) with no
        per-message fetches.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        client = self._open()
        try:
            client.select(mailbox=mailbox, readonly=True)
            status, raw = client.search(None, criteria)
            if status != "OK":
                raise RuntimeError(f"IMAP SEARCH failed: {status}")
            if not raw or raw[0] is None:
                if include_metadata:
                    return {"mailbox": mailbox, "messages": []}
                return {"mailbox": mailbox, "uids": []}
            raw_payload = raw[0]
            if isinstance(raw_payload, bytes):
                payload = raw_payload.decode("ascii")
            elif isinstance(raw_payload, str):
                payload = raw_payload
            else:
                payload = str(raw_payload)
            ids = [int(part) for part in payload.split() if part]
            if not include_metadata:
                return {"mailbox": mailbox, "uids": ids[:limit]}
            capped = min(limit, _METADATA_SUMMARY_MAX)
            selected = ids[:capped]
            summaries: list[dict[str, Any]] = []
            for index, uid in enumerate(selected, start=1):
                envelope = _fetch_envelope(client, uid)
                summaries.append(_envelope_summary(envelope, uid=uid, index=index))
            result: dict[str, Any] = {
                "mailbox": mailbox,
                "messages": summaries,
                "totalMatched": len(ids),
            }
            if limit != capped:
                result["requestedLimit"] = limit
                result["summaryLimit"] = _METADATA_SUMMARY_MAX
            return result
        finally:
            _safe_logout(client)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def fetch_message(self, uid: Any, mailbox: str = "INBOX") -> dict[str, Any]:
        """Fetch a single message and return its parsed headers / body.

        ``uid`` accepts an integer UID, a numeric string, or a message
        dict from :meth:`search_messages` (the ``uid`` field is extracted
        automatically). Returns the full parsed message: ``subject``,
        ``from_name``, ``from_address``, ``to``, ``cc``, ``date``,
        ``headers``, ``body_text``, ``body_html``, ``attachments``.
        """
        resolved = _extract_uid(uid)
        client = self._open()
        try:
            client.select(mailbox=mailbox, readonly=True)
            status, raw = client.fetch(str(resolved), "(RFC822)")
            if status != "OK":
                raise RuntimeError(f"IMAP FETCH failed: {status}")
            payload = _extract_rfc822(raw)
            if payload is None:
                raise LookupError(f"Message {resolved} not found in {mailbox!r}")
            message = email.message_from_bytes(payload)
            return _summarize_message(resolved, message)
        finally:
            _safe_logout(client)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def mailbox_status(
        self,
        mailbox: str = "INBOX",
        items: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return STATUS counters (MESSAGES/RECENT/UNSEEN/UIDNEXT/UIDVALIDITY).

        Useful for quick inbox health checks (how many unseen messages?).
        """
        names = items or ["MESSAGES", "RECENT", "UNSEEN", "UIDNEXT", "UIDVALIDITY"]
        for name in names:
            if not name.replace("-", "").isalpha():
                raise ValueError(f"Invalid status item: {name!r}")
        client = self._open()
        try:
            joined = "(" + " ".join(names) + ")"
            status, raw = client.status(mailbox, joined)
            if status != "OK":
                raise RuntimeError(f"IMAP STATUS failed: {status}")
            return _parse_status(raw, mailbox=mailbox)
        finally:
            _safe_logout(client)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def capability(self) -> list[str]:
        """Return the server-advertised IMAP capabilities."""
        client = self._open()
        try:
            status, raw = client.capability()
            if status != "OK":
                raise RuntimeError(f"IMAP CAPABILITY failed: {status}")
            return _decode_word_list(raw)
        finally:
            _safe_logout(client)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def noop(self) -> dict[str, Any]:
        """Issue NOOP to verify connectivity and refresh server state."""
        client = self._open()
        try:
            status, raw = client.noop()
            return {"status": status, "info": _decode_word_list(raw)}
        finally:
            _safe_logout(client)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def set_flags(
        self,
        uid: Any,
        *,
        mailbox: str = "INBOX",
        add: list[str] | None = None,
        remove: list[str] | None = None,
        replace: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add, remove, or replace IMAP flags on a single UID via STORE.

        ``uid`` accepts an integer, a numeric string, or a message dict
        from :meth:`search_messages`.
        """
        if not (add or remove or replace):
            raise ValueError("Supply at least one of add, remove, or replace")
        if replace is not None and (add or remove):
            raise ValueError("replace is mutually exclusive with add/remove")
        resolved = _extract_uid(uid)
        client = self._open()
        try:
            client.select(mailbox=mailbox, readonly=False)
            applied: list[dict[str, Any]] = []
            if replace is not None:
                applied.append(_store(client, resolved, "FLAGS", replace))
            if add:
                applied.append(_store(client, resolved, "+FLAGS", add))
            if remove:
                applied.append(_store(client, resolved, "-FLAGS", remove))
            return {"uid": resolved, "mailbox": mailbox, "applied": applied}
        finally:
            _safe_logout(client)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def mark_read(self, uid: Any, mailbox: str = "INBOX") -> dict[str, Any]:
        """Convenience: add the ``\\Seen`` flag.

        ``uid`` accepts an integer, numeric string, or message dict.
        """
        return self.set_flags(uid, mailbox=mailbox, add=[r"\Seen"])

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def mark_unread(self, uid: Any, mailbox: str = "INBOX") -> dict[str, Any]:
        """Convenience: remove the ``\\Seen`` flag.

        ``uid`` accepts an integer, numeric string, or message dict.
        """
        return self.set_flags(uid, mailbox=mailbox, remove=[r"\Seen"])

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def copy_message(
        self,
        uid: Any,
        destination: str,
        *,
        mailbox: str = "INBOX",
    ) -> dict[str, Any]:
        """Copy a UID from ``mailbox`` to ``destination`` via COPY.

        ``uid`` accepts an integer, numeric string, or message dict.
        """
        resolved = _extract_uid(uid)
        client = self._open()
        try:
            client.select(mailbox=mailbox, readonly=False)
            status, raw = client.copy(str(resolved), destination)
            if status != "OK":
                raise RuntimeError(f"IMAP COPY failed: {status}")
            return {
                "uid": resolved,
                "from": mailbox,
                "to": destination,
                "info": _decode_word_list(raw),
            }
        finally:
            _safe_logout(client)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def move_message(
        self,
        uid: Any,
        destination: str,
        *,
        mailbox: str = "INBOX",
    ) -> dict[str, Any]:
        """Move a UID using COPY + ``\\Deleted`` flag + EXPUNGE (works without MOVE).

        ``uid`` accepts an integer, numeric string, or message dict.
        """
        resolved = _extract_uid(uid)
        client = self._open()
        try:
            client.select(mailbox=mailbox, readonly=False)
            status, raw = client.copy(str(resolved), destination)
            if status != "OK":
                raise RuntimeError(f"IMAP COPY failed: {status}")
            _store(client, resolved, "+FLAGS", [r"\Deleted"])
            expunge_status, _ = client.expunge()
            if expunge_status != "OK":
                raise RuntimeError(f"IMAP EXPUNGE failed: {expunge_status}")
            return {
                "uid": resolved,
                "from": mailbox,
                "to": destination,
                "info": _decode_word_list(raw),
            }
        finally:
            _safe_logout(client)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def append_message(
        self,
        mailbox: str,
        raw_message: bytes | str,
        *,
        flags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Append a message to ``mailbox`` via the APPEND command.

        ``raw_message`` is a full RFC 822 message (headers and body).
        """
        if not raw_message:
            raise ValueError("raw_message must not be empty")
        if isinstance(raw_message, str):
            payload = raw_message.encode("utf-8")
        else:
            payload = bytes(raw_message)
        client = self._open()
        try:
            flag_str = " ".join(flags) if flags else ""
            status, raw = client.append(mailbox, flag_str, None, payload)
            if status != "OK":
                raise RuntimeError(f"IMAP APPEND failed: {status}")
            return {"mailbox": mailbox, "bytes": len(payload), "info": _decode_word_list(raw)}
        finally:
            _safe_logout(client)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_mailbox(self, name: str) -> dict[str, Any]:
        """Create a new IMAP mailbox/folder."""
        if not name:
            raise ValueError("name must be a non-empty string")
        client = self._open()
        try:
            status, raw = client.create(name)
            if status != "OK":
                raise RuntimeError(f"IMAP CREATE failed: {status}")
            return {"name": name, "info": _decode_word_list(raw)}
        finally:
            _safe_logout(client)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def rename_mailbox(self, old_name: str, new_name: str) -> dict[str, Any]:
        """Rename an existing IMAP mailbox."""
        if not old_name or not new_name:
            raise ValueError("old_name and new_name must be non-empty")
        client = self._open()
        try:
            status, raw = client.rename(old_name, new_name)
            if status != "OK":
                raise RuntimeError(f"IMAP RENAME failed: {status}")
            return {"from": old_name, "to": new_name, "info": _decode_word_list(raw)}
        finally:
            _safe_logout(client)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def subscribe_mailbox(self, name: str) -> dict[str, Any]:
        """Subscribe to a mailbox (server-side bookmark)."""
        if not name:
            raise ValueError("name must be a non-empty string")
        client = self._open()
        try:
            status, raw = client.subscribe(name)
            if status != "OK":
                raise RuntimeError(f"IMAP SUBSCRIBE failed: {status}")
            return {"name": name, "info": _decode_word_list(raw)}
        finally:
            _safe_logout(client)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def unsubscribe_mailbox(self, name: str) -> dict[str, Any]:
        """Remove a mailbox subscription."""
        if not name:
            raise ValueError("name must be a non-empty string")
        client = self._open()
        try:
            status, raw = client.unsubscribe(name)
            if status != "OK":
                raise RuntimeError(f"IMAP UNSUBSCRIBE failed: {status}")
            return {"name": name, "info": _decode_word_list(raw)}
        finally:
            _safe_logout(client)

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_message(self, uid: Any, mailbox: str = "INBOX") -> dict[str, Any]:
        """Mark a UID with ``\\Deleted`` and EXPUNGE the mailbox.

        ``uid`` accepts an integer, numeric string, or message dict from
        :meth:`search_messages`. Destructive — confirm with the user
        first.
        """
        resolved = _extract_uid(uid)
        client = self._open()
        try:
            client.select(mailbox=mailbox, readonly=False)
            _store(client, resolved, "+FLAGS", [r"\Deleted"])
            status, raw = client.expunge()
            if status != "OK":
                raise RuntimeError(f"IMAP EXPUNGE failed: {status}")
            return {"uid": resolved, "mailbox": mailbox, "info": _decode_word_list(raw)}
        finally:
            _safe_logout(client)

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def expunge(self, mailbox: str = "INBOX") -> dict[str, Any]:
        """Permanently remove all messages flagged ``\\Deleted`` in ``mailbox``.

        Destructive — confirm with the user first.
        """
        client = self._open()
        try:
            client.select(mailbox=mailbox, readonly=False)
            status, raw = client.expunge()
            if status != "OK":
                raise RuntimeError(f"IMAP EXPUNGE failed: {status}")
            return {"mailbox": mailbox, "info": _decode_word_list(raw)}
        finally:
            _safe_logout(client)

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_mailbox(self, name: str) -> dict[str, Any]:
        """Delete a mailbox/folder. The action is server-final.

        Destructive — confirm with the user first.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        client = self._open()
        try:
            status, raw = client.delete(name)
            if status != "OK":
                raise RuntimeError(f"IMAP DELETE failed: {status}")
            return {"name": name, "info": _decode_word_list(raw)}
        finally:
            _safe_logout(client)

    # MARK: - Internal

    def _open(self) -> ImapClient:
        client = self._client_factory()
        if self._username:
            client.login(self._username, self._password)
        return client


def _extract_uid(candidate: Any) -> int:
    """Extract an IMAP UID from an int, numeric string, or message dict."""
    if isinstance(candidate, bool):  # bool is an int subclass — reject early
        raise ValueError("uid must be an integer or message dict")
    if isinstance(candidate, int):
        return candidate
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("uid must be a non-empty string")
        try:
            return int(candidate)
        except ValueError as exc:
            raise ValueError(f"uid must be numeric, got {candidate!r}") from exc
    if isinstance(candidate, dict):
        mapping = cast(dict[object, object], candidate)
        for key in ("uid", "id"):
            value = mapping.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
            if isinstance(value, str) and value:
                try:
                    return int(value)
                except ValueError:
                    continue
        raise ValueError("message dict must contain a numeric 'uid' or 'id'")
    if isinstance(candidate, list):
        for entry in cast(list[object], candidate):
            try:
                return _extract_uid(entry)
            except ValueError:
                continue
        raise ValueError("no valid uid found in list")
    raise ValueError("uid must be an integer, numeric string, or message dict")


def _safe_logout(client: ImapClient) -> None:
    try:
        client.logout()
    except Exception:  # noqa: BLE001 - cleanup must never raise
        pass


def _store(client: ImapClient, uid: int, command: str, flags: list[str]) -> dict[str, Any]:
    flag_str = "(" + " ".join(flags) + ")"
    status, raw = client.store(str(uid), command, flag_str)
    if status != "OK":
        raise RuntimeError(f"IMAP STORE {command} failed: {status}")
    return {"command": command, "flags": list(flags), "info": _decode_word_list(raw)}


def _decode_word_list(raw: Sequence[object]) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for entry in raw:
        if entry is None:
            continue
        if isinstance(entry, (bytes, bytearray)):
            text = bytes(entry).decode("utf-8", errors="replace")
        else:
            text = str(entry)
        out.extend(text.split())
    return out


def _parse_status(raw: Sequence[object], *, mailbox: str) -> dict[str, Any]:
    counters: dict[str, int] = {}
    if not raw:
        return {"mailbox": mailbox, "counters": counters}
    for entry in raw:
        if isinstance(entry, (bytes, bytearray)):
            text = bytes(entry).decode("utf-8", errors="replace")
        else:
            text = str(entry)
        start = text.find("(")
        end = text.rfind(")")
        if start == -1 or end == -1 or end <= start:
            continue
        body = text[start + 1 : end].split()
        for i in range(0, len(body) - 1, 2):
            try:
                counters[body[i].upper()] = int(body[i + 1])
            except ValueError:
                counters[body[i].upper()] = -1  # unparseable
    return {"mailbox": mailbox, "counters": counters}


def _parse_mailbox(entry: str) -> str:
    # Entries look like: '(\HasNoChildren) "/" "INBOX"'
    if '"' in entry:
        return entry.rsplit('"', 2)[-2]
    return entry.split()[-1]


def _extract_rfc822(raw: Sequence[object]) -> bytes | None:
    if not raw:
        return None
    for part in raw:
        if isinstance(part, tuple):
            fields = cast(tuple[object, ...], part)
            if len(fields) >= 2:
                body = fields[1]
                if isinstance(body, (bytes, bytearray)):
                    return bytes(body)
                if isinstance(body, str):
                    return body.encode("utf-8")
    return None


def _fetch_envelope(client: ImapClient, uid: int) -> Message | None:
    """Fetch the envelope/headers of one UID for summary mode.

    We ask for the bare RFC822 headers instead of ENVELOPE so we can
    reuse the standard :mod:`email` parser and avoid relying on
    server-specific envelope formatting. Returns the parsed
    :class:`email.message.Message` (without body) or None on miss.
    """
    status, raw = client.fetch(str(uid), "(BODY.PEEK[HEADER] FLAGS)")
    if status != "OK":
        raise RuntimeError(f"IMAP FETCH (header) failed: {status}")
    if not raw:
        return None
    header_bytes: bytes | None = None
    flags_text: str | None = None
    for part in raw:
        if isinstance(part, tuple) and len(cast(tuple[object, ...], part)) >= 2:
            fields = cast(tuple[object, ...], part)
            descriptor = fields[0]
            body = fields[1]
            if isinstance(descriptor, (bytes, bytearray)):
                descriptor_text = bytes(descriptor).decode("utf-8", errors="replace")
            else:
                descriptor_text = str(descriptor)
            if isinstance(body, (bytes, bytearray)):
                header_bytes = bytes(body)
            elif isinstance(body, str):
                header_bytes = body.encode("utf-8")
            if "FLAGS" in descriptor_text:
                flags_text = descriptor_text
        elif isinstance(part, (bytes, bytearray)) and flags_text is None:
            text = bytes(part).decode("utf-8", errors="replace")
            if "FLAGS" in text:
                flags_text = text
    if header_bytes is None:
        return None
    message = email.message_from_bytes(header_bytes)
    if flags_text:
        message["X-Imap-Flags"] = _parse_flags(flags_text)
    return message


def _parse_flags(text: str) -> str:
    """Extract a flags string like ``\\Seen \\Answered`` from a FLAGS descriptor."""
    start = text.find("FLAGS")
    if start == -1:
        return ""
    open_paren = text.find("(", start)
    close_paren = text.find(")", open_paren)
    if open_paren == -1 or close_paren == -1:
        return ""
    return text[open_paren + 1 : close_paren].strip()


def _envelope_summary(
    message: Message | None,
    *,
    uid: int,
    index: int,
) -> dict[str, Any]:
    if message is None:
        return {
            "message_ref": f"message_{index}",
            "uid": uid,
            "sender": "",
            "subject": "",
            "received_at": "",
            "flags": [],
        }
    from_name, from_addr = parseaddr(message.get("From", ""))
    sender = ""
    if from_name and from_addr:
        sender = f"{from_name} <{from_addr}>"
    else:
        sender = from_addr or from_name or ""
    # ``Message.get`` is typed as returning ``Any``; widen to ``object`` so the
    # defensive str guard below is type-meaningful instead of being flagged as
    # always-true.
    flags_value: object = cast(object, message.get("X-Imap-Flags")) or ""
    flags = [f for f in flags_value.split() if f] if isinstance(flags_value, str) else []
    return {
        "message_ref": f"message_{index}",
        "uid": uid,
        "sender": sender,
        "subject": message.get("Subject", "") or "",
        "received_at": message.get("Date", "") or "",
        "flags": flags,
    }


def _summarize_message(uid: int, message: Message) -> dict[str, Any]:
    headers = {key: value for key, value in message.items()}
    from_name, from_addr = parseaddr(message.get("From", ""))
    body = _flatten_body(message)
    return {
        "uid": uid,
        "subject": message.get("Subject"),
        "from_name": from_name or None,
        "from_address": from_addr or None,
        "to": message.get("To"),
        "cc": message.get("Cc"),
        "date": message.get("Date"),
        "headers": headers,
        "body_text": body.get("text"),
        "body_html": body.get("html"),
        "attachments": body.get("attachments", []),
    }


def _flatten_body(message: Message) -> dict[str, Any]:
    text: str | None = None
    html: str | None = None
    attachments: list[dict[str, Any]] = []
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = part.get_content_disposition()
            if disposition == "attachment" or part.get_filename():
                attachments.append(
                    {
                        "filename": part.get_filename(),
                        "content_type": content_type,
                        "size": _payload_size(part),
                    }
                )
                continue
            if content_type == "text/plain" and text is None:
                text = _decode_payload(part)
            elif content_type == "text/html" and html is None:
                html = _decode_payload(part)
    else:
        content_type = message.get_content_type()
        if content_type == "text/plain":
            text = _decode_payload(message)
        elif content_type == "text/html":
            html = _decode_payload(message)
        else:
            text = _decode_payload(message)
    return {"text": text, "html": html, "attachments": attachments}


def _decode_payload(part: Message) -> str | None:
    payload = part.get_payload(decode=True)
    if payload is None:
        return None
    charset = part.get_content_charset() or "utf-8"
    if isinstance(payload, bytes):
        return payload.decode(charset, errors="replace")
    return str(payload)


def _payload_size(part: Message) -> int | None:
    payload = part.get_payload(decode=True)
    if payload is None:
        return None
    return len(payload) if isinstance(payload, (bytes, bytearray)) else None
