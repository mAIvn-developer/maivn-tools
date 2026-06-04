# pyright: strict
from __future__ import annotations

from collections.abc import Iterable
from email.message import EmailMessage
from typing import Any, cast

import pytest

from maivn_tools.connectors.email import IMAPToolSet, SMTPToolSet
from maivn_tools.connectors.email.imap import ImapClient, ImapClientFactory
from maivn_tools.connectors.email.smtp import SmtpClient, SmtpClientFactory


class FakeImapClient:
    def __init__(self) -> None:
        self.login_args: tuple[str, str] | None = None
        self.logged_out = False
        self.selected: tuple[str, bool] | None = None
        self.store_calls: list[tuple[str, str, str]] = []
        self.copy_args: tuple[str, str] | None = None
        self.append_args: tuple[str, str, Any, bytes] | None = None
        self.expunged = False
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.renamed: tuple[str, str] | None = None
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []

    def login(self, user: str, password: str) -> Any:
        self.login_args = (user, password)
        return ("OK", [b"Logged in"])

    def logout(self) -> Any:
        self.logged_out = True
        return ("BYE", [])

    def list(self, directory: str = "", pattern: str = "*") -> Any:
        return ("OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Sent"'])

    def select(self, mailbox: str = "INBOX", readonly: bool = True) -> Any:
        self.selected = (mailbox, readonly)
        return ("OK", [b"1"])

    def search(self, charset: str | None, *criteria: str) -> Any:
        return ("OK", [b"1 2 3"])

    def fetch(self, message_set: str, message_parts: str) -> Any:
        rfc822 = (
            b"From: Alice <alice@example.test>\r\n"
            b"To: bob@example.test\r\n"
            b"Subject: Test\r\n"
            b"MIME-Version: 1.0\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
            b"Hello world\r\n"
        )
        return ("OK", [(b"1 (RFC822 {%d}" % len(rfc822), rfc822)])

    def status(self, mailbox: str, names: str) -> Any:
        return (
            "OK",
            [b"INBOX (MESSAGES 12 RECENT 1 UNSEEN 3 UIDNEXT 100 UIDVALIDITY 7)"],
        )

    def store(self, message_set: str, command: str, flags: str) -> Any:
        self.store_calls.append((message_set, command, flags))
        return ("OK", [b""])

    def copy(self, message_set: str, new_mailbox: str) -> Any:
        self.copy_args = (message_set, new_mailbox)
        return ("OK", [b""])

    def append(self, mailbox: str, flags: str, date_time: Any, message: bytes) -> Any:
        self.append_args = (mailbox, flags, date_time, message)
        return ("OK", [b""])

    def expunge(self) -> Any:
        self.expunged = True
        return ("OK", [b""])

    def create(self, mailbox: str) -> Any:
        self.created.append(mailbox)
        return ("OK", [b""])

    def delete(self, mailbox: str) -> Any:
        self.deleted.append(mailbox)
        return ("OK", [b""])

    def rename(self, oldmailbox: str, newmailbox: str) -> Any:
        self.renamed = (oldmailbox, newmailbox)
        return ("OK", [b""])

    def subscribe(self, mailbox: str) -> Any:
        self.subscribed.append(mailbox)
        return ("OK", [b""])

    def unsubscribe(self, mailbox: str) -> Any:
        self.unsubscribed.append(mailbox)
        return ("OK", [b""])

    def close(self) -> Any:
        return ("OK", [b""])

    def noop(self) -> Any:
        return ("OK", [b"NOOP done"])

    def capability(self) -> Any:
        return ("OK", [b"IMAP4REV1 IDLE MOVE"])


def _imap_factory(client: FakeImapClient) -> ImapClientFactory:
    def factory() -> ImapClient:
        return cast(ImapClient, client)

    return factory


def test_imap_connector_requires_credentials_or_factory() -> None:
    with pytest.raises(ValueError):
        IMAPToolSet(host="", username="", password="")


def test_imap_list_mailboxes_parses_response() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    mailboxes = connector.list_mailboxes()
    assert mailboxes == ["INBOX", "Sent"]
    assert fake.logged_out is True


def test_imap_search_returns_raw_uids_when_metadata_disabled() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    result = connector.search_messages(criteria="ALL", limit=2, include_metadata=False)
    assert result == {"mailbox": "INBOX", "uids": [1, 2]}
    assert fake.selected == ("INBOX", True)


def test_imap_search_returns_summaries_by_default() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    result = connector.search_messages(criteria="ALL", limit=2)
    assert result["mailbox"] == "INBOX"
    assert result["totalMatched"] == 3
    assert len(result["messages"]) == 2
    first = result["messages"][0]
    assert first["message_ref"] == "message_1"
    assert first["uid"] == 1
    assert first["sender"] == "Alice <alice@example.test>"
    assert first["subject"] == "Test"


def test_imap_search_validates_limit() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    with pytest.raises(ValueError):
        connector.search_messages(limit=0)


def test_imap_search_caps_summary_limit() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    result = connector.search_messages(criteria="ALL", limit=50)
    # totalMatched returns the 3 UIDs from search, but summaries cap at 10
    assert result["requestedLimit"] == 50
    assert result["summaryLimit"] == 10


def test_imap_search_empty_results() -> None:
    class EmptyClient(FakeImapClient):
        def search(self, charset: str | None, *criteria: str) -> Any:
            return ("OK", [None])

    fake = EmptyClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    result = connector.search_messages(criteria="ALL")
    assert result == {"mailbox": "INBOX", "messages": []}
    raw_result = connector.search_messages(criteria="ALL", include_metadata=False)
    assert raw_result == {"mailbox": "INBOX", "uids": []}


def test_imap_fetch_message_parses_headers_and_body() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    summary = connector.fetch_message(uid=1)
    assert summary["subject"] == "Test"
    assert summary["from_address"] == "alice@example.test"
    assert summary["from_name"] == "Alice"
    assert summary["body_text"].strip() == "Hello world"
    assert summary["body_html"] is None
    assert summary["attachments"] == []


class FakeSmtpClient:
    def __init__(self) -> None:
        self.started_tls = False
        self.login_args: tuple[str, str] | None = None
        self.sent: list[tuple[EmailMessage, list[str]]] = []
        self.quit_called = False
        self.refused: dict[str, tuple[int, bytes]] = {}

    def starttls(self, *args: Any, **kwargs: Any) -> Any:
        self.started_tls = True

    def login(self, user: str, password: str) -> Any:
        self.login_args = (user, password)

    def send_message(
        self,
        msg: EmailMessage,
        from_addr: str | None = None,
        to_addrs: Iterable[str] | None = None,
    ) -> Any:
        self.sent.append((msg, list(to_addrs or [])))
        return dict(self.refused)

    def sendmail(
        self,
        from_addr: str,
        to_addrs: Iterable[str],
        msg: bytes | str,
    ) -> Any:
        return dict(self.refused)

    def noop(self) -> Any:
        return (250, b"OK")

    def ehlo(self, name: str | None = None) -> Any:
        return (250, b"server-hello")

    def helo(self, name: str | None = None) -> Any:
        return (250, b"helo")

    def quit(self) -> Any:
        self.quit_called = True


def _smtp_factory(client: FakeSmtpClient) -> SmtpClientFactory:
    def factory() -> SmtpClient:
        return cast(SmtpClient, client)

    return factory


def test_smtp_sender_requires_sender_with_custom_factory() -> None:
    with pytest.raises(ValueError):
        SMTPToolSet(client_factory=_smtp_factory(FakeSmtpClient()), sender="")


def test_smtp_sender_rejects_both_ssl_and_starttls() -> None:
    with pytest.raises(ValueError):
        SMTPToolSet(host="x", sender="me@x", use_ssl=True, starttls=True)


def test_smtp_sender_requires_host_with_default_factory() -> None:
    with pytest.raises(ValueError):
        SMTPToolSet(sender="me@x")


def test_smtp_send_email_builds_message_and_uses_starttls() -> None:
    fake = FakeSmtpClient()
    sender = SMTPToolSet(
        client_factory=_smtp_factory(fake),
        sender="me@example.test",
        username="me",
        password="pw",
        starttls=True,
        use_ssl=False,
    )
    # @toolify-marked: PermissionSet rides along in metadata when registered;
    # the bare method here is just the implementation.
    result = sender.send_email(
        to=["bob@example.test"],
        subject="Hi",
        body_text="Hello",
        body_html="<p>Hello</p>",
        cc=["cc@example.test"],
        bcc=["bcc@example.test"],
        attachments=[{"filename": "a.txt", "content": "data", "content_type": "text/plain"}],
        reply_to="reply@example.test",
    )
    assert fake.started_tls is True
    assert fake.login_args == ("me", "pw")
    assert fake.quit_called is True
    assert fake.sent, "expected message to be sent"
    message, recipients = fake.sent[0]
    assert recipients == ["bob@example.test", "cc@example.test", "bcc@example.test"]
    assert message["From"] == "me@example.test"
    assert message["Reply-To"] == "reply@example.test"
    assert message["Subject"] == "Hi"
    assert any(part.get_filename() == "a.txt" for part in message.walk())
    assert result["accepted"] == [
        "bob@example.test",
        "cc@example.test",
        "bcc@example.test",
    ]
    assert result["refused"] == {}


def test_smtp_send_email_reports_refused_recipients() -> None:
    fake = FakeSmtpClient()
    fake.refused = {"bob@example.test": (550, b"User unknown")}
    sender = SMTPToolSet(
        client_factory=_smtp_factory(fake),
        sender="me@example.test",
    )
    result = sender.send_email(to=["bob@example.test"], subject="Hi", body_text="Hello")
    assert result["accepted"] == []
    assert "bob@example.test" in result["refused"]


def test_smtp_send_email_validates_inputs() -> None:
    fake = FakeSmtpClient()
    sender = SMTPToolSet(client_factory=_smtp_factory(fake), sender="me@example.test")
    with pytest.raises(ValueError):
        sender.send_email(to=[], subject="x", body_text="hello")
    with pytest.raises(ValueError):
        sender.send_email(to=["bob@example.test"], subject="x")


def test_smtp_send_email_rejects_non_bytes_attachment() -> None:
    fake = FakeSmtpClient()
    sender = SMTPToolSet(client_factory=_smtp_factory(fake), sender="me@example.test")
    with pytest.raises(TypeError):
        sender.send_email(
            to=["bob@example.test"],
            subject="x",
            body_text="hi",
            attachments=[{"filename": "a.txt", "content": 123}],
        )


class _ValidatingSmtpClient(FakeSmtpClient):
    def __init__(self) -> None:
        super().__init__()
        self.noop_called = False
        self.ehlo_called = False
        self.sendmail_args: tuple[str, list[str], bytes | str] | None = None

    def ehlo(self, name: str | None = None) -> Any:
        self.ehlo_called = True
        return (250, b"server-hello")

    def helo(self, name: str | None = None) -> Any:  # pragma: no cover
        return (250, b"helo")

    def noop(self) -> Any:
        self.noop_called = True
        return (250, b"OK")

    def sendmail(self, from_addr: str, to_addrs: Any, msg: bytes | str) -> Any:
        self.sendmail_args = (from_addr, list(to_addrs), msg)
        return dict(self.refused)


def test_smtp_validate_connection_returns_ok_summary() -> None:
    fake = _ValidatingSmtpClient()
    sender = SMTPToolSet(
        client_factory=_smtp_factory(fake),
        sender="me@example.test",
        username="me",
        password="pw",
        starttls=True,
        use_ssl=False,
    )
    result = sender.validate_connection()
    assert result["ok"] is True
    assert result["authenticated"] is True
    assert fake.ehlo_called is True
    assert fake.noop_called is True
    assert fake.quit_called is True


def test_smtp_send_raw_email_passes_payload_through() -> None:
    fake = _ValidatingSmtpClient()
    sender = SMTPToolSet(client_factory=_smtp_factory(fake), sender="me@example.test")
    raw = b"Subject: Hi\r\n\r\nHello"
    result = sender.send_raw_email(raw, recipients=["bob@example.test"])
    assert fake.sendmail_args is not None
    assert fake.sendmail_args[0] == "me@example.test"
    assert fake.sendmail_args[1] == ["bob@example.test"]
    assert fake.sendmail_args[2] == raw
    assert result["accepted"] == ["bob@example.test"]


def test_smtp_send_raw_email_validates_inputs() -> None:
    fake = _ValidatingSmtpClient()
    sender = SMTPToolSet(client_factory=_smtp_factory(fake), sender="me@example.test")
    with pytest.raises(ValueError):
        sender.send_raw_email(b"", recipients=["a@b.c"])
    with pytest.raises(ValueError):
        sender.send_raw_email(b"hi", recipients=[])


def test_imap_mailbox_status_parses_counters() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    info = connector.mailbox_status(mailbox="INBOX")
    assert info["mailbox"] == "INBOX"
    assert info["counters"]["MESSAGES"] == 12
    assert info["counters"]["UNSEEN"] == 3


def test_imap_mailbox_status_validates_items() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    with pytest.raises(ValueError):
        connector.mailbox_status(items=["BAD;ITEM"])


def test_imap_capability_returns_words() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    caps = connector.capability()
    assert "IMAP4REV1" in caps


def test_imap_noop_returns_status() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    result = connector.noop()
    assert result["status"] == "OK"


def test_imap_set_flags_requires_one_of_args() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    with pytest.raises(ValueError):
        connector.set_flags(uid=1)


def test_imap_set_flags_rejects_replace_with_add() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    with pytest.raises(ValueError):
        connector.set_flags(uid=1, replace=[r"\Seen"], add=[r"\Flagged"])


def test_imap_set_flags_issues_store_commands() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    connector.set_flags(uid=42, add=[r"\Seen"], remove=[r"\Flagged"])
    commands = [call[1] for call in fake.store_calls]
    assert "+FLAGS" in commands
    assert "-FLAGS" in commands


def test_imap_mark_read_and_unread_delegate_to_set_flags() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    connector.mark_read(uid=1)
    connector.mark_unread(uid=1)
    assert fake.store_calls[0][1] == "+FLAGS"
    assert fake.store_calls[1][1] == "-FLAGS"


def test_imap_copy_and_move_message() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    connector.copy_message(uid=1, destination="Archive")
    assert fake.copy_args == ("1", "Archive")

    fake2 = FakeImapClient()
    connector2 = IMAPToolSet(client_factory=_imap_factory(fake2))
    connector2.move_message(uid=2, destination="Archive")
    assert fake2.copy_args == ("2", "Archive")
    assert fake2.expunged is True
    assert any(call[1] == "+FLAGS" for call in fake2.store_calls)


def test_imap_append_message_writes_payload() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    info = connector.append_message("INBOX", b"raw", flags=[r"\Seen"])
    assert fake.append_args is not None
    assert fake.append_args[0] == "INBOX"
    assert fake.append_args[3] == b"raw"
    assert info["bytes"] == 3


def test_imap_append_message_validates_empty_payload() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    with pytest.raises(ValueError):
        connector.append_message("INBOX", b"")


def test_imap_create_rename_delete_mailbox() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    connector.create_mailbox("Project")
    connector.rename_mailbox("Project", "Project-Archive")
    connector.delete_mailbox("Project-Archive")
    assert fake.created == ["Project"]
    assert fake.renamed == ("Project", "Project-Archive")
    assert fake.deleted == ["Project-Archive"]


def test_imap_create_mailbox_rejects_empty_name() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    with pytest.raises(ValueError):
        connector.create_mailbox("")


def test_imap_subscribe_unsubscribe() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    connector.subscribe_mailbox("News")
    connector.unsubscribe_mailbox("News")
    assert fake.subscribed == ["News"]
    assert fake.unsubscribed == ["News"]


def test_imap_delete_message_and_expunge() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    connector.delete_message(uid=7)
    assert fake.expunged is True
    assert any(call[1] == "+FLAGS" for call in fake.store_calls)

    fake2 = FakeImapClient()
    connector2 = IMAPToolSet(client_factory=_imap_factory(fake2))
    connector2.expunge(mailbox="Trash")
    assert fake2.selected == ("Trash", False)
    assert fake2.expunged is True


def test_imap_delete_message_is_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    for method in (connector.delete_message, connector.expunge, connector.delete_mailbox):
        opts = get_toolify_options(method)
        assert opts is not None and opts.destructive is True


def test_imap_uid_extractor_accepts_dict_from_search() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    # Simulate passing a message dict from search_messages output.
    message = {"message_ref": "message_1", "uid": 42, "subject": "Hi"}
    connector.mark_read(uid=message)
    assert fake.store_calls[0][0] == "42"
    assert fake.store_calls[0][1] == "+FLAGS"


def test_imap_uid_extractor_accepts_numeric_string() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    connector.mark_read(uid="123")
    assert fake.store_calls[0][0] == "123"


def test_imap_uid_extractor_rejects_invalid_input() -> None:
    fake = FakeImapClient()
    connector = IMAPToolSet(client_factory=_imap_factory(fake))
    with pytest.raises(ValueError):
        connector.mark_read(uid={"no_uid_here": True})
    with pytest.raises(ValueError):
        connector.mark_read(uid="not-a-number")
