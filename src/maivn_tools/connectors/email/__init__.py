"""Generic email connectors backed by IMAP and SMTP."""

from __future__ import annotations

from .imap import ImapClient, IMAPToolSet
from .smtp import SmtpClient, SMTPToolSet

__all__ = ["ImapClient", "IMAPToolSet", "SmtpClient", "SMTPToolSet"]
