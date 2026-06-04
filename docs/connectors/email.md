# Email connectors (IMAP + SMTP)

Two complementary connectors cover generic email workflows:

- `IMAPToolSet` — read **and modify** an IMAP mailbox.
- `SMTPToolSet` — outbound delivery and connection validation via SMTP.

Both use stdlib clients (`imaplib`, `smtplib`) and accept a custom
`client_factory` so tests can plug in fakes without opening real network
connections.

> **Agent-ready pattern.** `IMAPToolSet.search_messages` returns
> compact human-readable summaries by default with a stable
> `message_ref` field and the UID kept inline (the UID is the natural
> handle for `fetch_message` / `mark_read` / `delete_message`).
> Write tools (`set_flags`, `mark_read`, `mark_unread`, `copy_message`,
> `move_message`, `delete_message`) accept either a raw UID int, a
> numeric string, or the message-summary dict from `search_messages`.
> The SMTP connector exposes one effective send tool (`send_email`)
> plus `validate_connection` and `send_raw_email`; sending is
> destructive because outbound email cannot be unsent.

## IMAPToolSet

```python
from maivn import Agent
from maivn_tools import IMAPToolSet, register_connector

connector = IMAPToolSet(
    host="imap.example.com",
    username="ops@example.com",
    password=secrets["IMAP_PASSWORD"],
    port=993,
    use_ssl=True,
)
agent = Agent(model="auto")
register_connector(agent, connector)
```

### Tools

| Tool | Permission | Description |
| --- | --- | --- |
| `list_mailboxes(pattern)` | READ | Return mailbox names matching `pattern`. |
| `mailbox_status(mailbox, items)` | READ | `STATUS` counters (`MESSAGES`/`UNSEEN`/`UIDNEXT`/...). |
| `search_messages(mailbox, criteria, limit, include_metadata)` | READ | Search via IMAP `SEARCH`; compact `message_ref` summaries by default. |
| `fetch_message(uid, mailbox)` | READ | Parsed headers, body, and attachment metadata for one UID. Accepts a UID, numeric string, or message dict. |
| `capability()` | READ | Server-advertised IMAP capability tokens. |
| `noop()` | READ | Round-trip NOOP for liveness / refresh. |
| `set_flags(uid, mailbox, add, remove, replace)` | WRITE | Add/remove/replace flags on a UID via STORE. Accepts UID or message dict. |
| `mark_read(uid, mailbox)` | WRITE | Convenience: add `\Seen`. Accepts UID or message dict. |
| `mark_unread(uid, mailbox)` | WRITE | Convenience: remove `\Seen`. Accepts UID or message dict. |
| `copy_message(uid, destination, mailbox)` | WRITE | COPY a UID to another mailbox. Accepts UID or message dict. |
| `move_message(uid, destination, mailbox)` | WRITE | COPY + `\Deleted` + EXPUNGE (works without MOVE). Accepts UID or message dict. |
| `append_message(mailbox, raw_message, flags)` | WRITE | APPEND a raw RFC 822 message. |
| `create_mailbox(name)` | WRITE | Create a new folder. |
| `rename_mailbox(old_name, new_name)` | WRITE | Rename a folder. |
| `subscribe_mailbox(name)` | WRITE | Server-side subscription bookmark. |
| `unsubscribe_mailbox(name)` | WRITE | Remove a subscription bookmark. |
| `delete_message(uid, mailbox)` | DELETE (destructive) | Set `\Deleted` and EXPUNGE. Accepts UID or message dict. |
| `expunge(mailbox)` | DELETE (destructive) | EXPUNGE everything currently flagged `\Deleted`. |
| `delete_mailbox(name)` | DELETE (destructive) | Delete a folder. Server-final. |

`search_messages` accepts any IMAP `SEARCH` criteria (`UNSEEN`,
`FROM "alice@example.com"`, etc.).

### Agent-ready behavior

`search_messages` returns compact summaries by default: each match
gets a stable `message_ref` (`message_1`, `message_2`, ...), `uid`,
`sender`, `subject`, `received_at` (Date header), and `flags`. Summary
mode caps `limit` at 10 because each UID requires a per-message
ENVELOPE fetch — for raw UID lists, pass `include_metadata=False` to
get the legacy wire format (`{"uids": [...]}`). Default `limit` is
25. The UID is intentionally exposed in summary mode because every
follow-up tool needs it.

```python
imap.search_messages(criteria="UNSEEN")
# { "mailbox": "INBOX",
#   "messages": [{"message_ref": "message_1", "uid": 4242,
#                  "sender": "Alice <alice@example>",
#                  "subject": "Q3 plan", "received_at": "...",
#                  "flags": []}], "totalMatched": 7,
#   "requestedLimit": 25, "summaryLimit": 10 }

# Raw UID list, no per-message fetch.
imap.search_messages(criteria="UNSEEN", include_metadata=False)
# { "mailbox": "INBOX", "uids": [4242, 4243, 4244, ...] }
```

`fetch_message`, `set_flags`, `mark_read`, `mark_unread`,
`copy_message`, `move_message`, and `delete_message` all accept either
a raw UID int, a numeric string, or a message dict from
`search_messages` — the UID is extracted automatically.

### Destructive tools

`delete_message`, `expunge`, and `delete_mailbox` are tagged
`destructive=True` and remove messages or folders server-side without
recovery. Filter them out with `exclude_tags=["destructive"]` for
triage-only agents.

### Filtering at registration

```python
# Read-only IMAP for a summarization agent.
agent.add_toolset(IMAPToolSet(...), include_tags=["read"])

# Read + write but never destructive.
agent.add_toolset(IMAPToolSet(...), exclude_tags=["destructive"])
```

## SMTPToolSet

```python
from maivn_tools import SMTPToolSet, register_connector

sender = SMTPToolSet(
    host="smtp.example.com",
    port=587,
    use_ssl=False,
    starttls=True,
    username="ops@example.com",
    password=secrets["SMTP_PASSWORD"],
    sender="ops@example.com",
)
agent = Agent(model="auto")
register_connector(agent, sender)
```

### Tools

| Tool | Permission | Description |
| --- | --- | --- |
| `validate_connection()` | READ | EHLO/login/NOOP/quit; returns server greeting summary. |
| `send_email(to, subject, body_text, body_html, cc, bcc, attachments, sender, reply_to)` | WRITE | Build a MIME message and send via `send_message`. |
| `send_raw_email(raw_message, recipients, sender)` | WRITE | Send a pre-built MIME via `sendmail`. |

`send_email` returns:

```json
{
  "accepted": ["user@example.com"],
  "refused": {"bad@example.com": [550, "User unknown"]},
  "subject": "Hello",
  "to": ["user@example.com"]
}
```

Attachment `content` must be bytes (or a string, which is encoded as UTF-8).

### Agent-ready behavior

The SMTP surface is intentionally narrow: there are no list/search
tools because SMTP is send-only. `validate_connection` is the cheap
read tool for a startup sanity check. Both `send_email` and
`send_raw_email` should be treated as high-impact writes — once an
email leaves the server it cannot be unsent.

### Destructive tools

The connector does not currently tag `send_email` / `send_raw_email`
as `destructive=True` (they remain plain WRITE), but the effect is
irreversible. Always confirm the recipient list with the user before
calling in an interactive loop. If you need to drop send tools at
registration, use `include_tags=["read"]` to keep only
`validate_connection`.

### Configuration

| Argument | Default | Purpose |
| --- | --- | --- |
| `host` | required (default factory) | SMTP server hostname. |
| `port` | `465` | TCP port. Use 587 for STARTTLS. |
| `use_ssl` / `starttls` | `True` / `False` | Mutually exclusive transport flags. |
| `username` / `password` | `""` | Auth credentials. Skip auth by leaving empty. |
| `sender` | required | Default `From` address. |
| `client_factory` | None | Override the SMTP client (used in tests). |
