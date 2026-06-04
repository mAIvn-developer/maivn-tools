"""Normalized attachment model.

An :class:`Attachment` is the canonical way connector tools surface file or
binary content. The model carries enough metadata for downstream tools and
agents to consume the content directly, fetch it on demand, or persist it.

Three sources are supported:

* :data:`AttachmentSource.INLINE` for small payloads that fit in memory.
* :data:`AttachmentSource.URL` for content reachable over the network. The
  attachment does not pre-fetch the URL; consumers do.
* :data:`AttachmentSource.PATH` for content on the local filesystem.
"""
# pyright: strict

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Any

from .mime import DEFAULT_MIME_TYPE, classify_kind, detect_mime_type, guess_mime_type

# MARK: Source enum


class AttachmentSource(str, Enum):
    """Where the attachment payload lives."""

    INLINE = "inline"
    URL = "url"
    PATH = "path"


# MARK: Attachment model


@dataclass(frozen=True)
class Attachment:
    """A reference to a file or binary blob exposed by a connector.

    Exactly one of ``content``, ``url``, or ``path`` must be supplied. The
    constructor enforces this invariant and derives the matching
    :class:`AttachmentSource` automatically.

    Attributes:
        name: Filename or display name for the attachment.
        mime_type: MIME type. Detected when ``None`` and inline content is
            available; otherwise inferred from ``name``.
        content: Inline bytes. Mutually exclusive with ``url`` and ``path``.
        url: Remote URL. Mutually exclusive with ``content`` and ``path``.
        path: Local filesystem path. Mutually exclusive with ``content`` and
            ``url``.
        size: Size in bytes, when known.
        checksum: Hex SHA-256 checksum, when known.
        extras: Free-form, JSON-serializable extras (provider IDs, headers).
    """

    name: str
    mime_type: str = DEFAULT_MIME_TYPE
    content: bytes | None = None
    url: str | None = None
    path: str | None = None
    size: int | None = None
    checksum: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    source: AttachmentSource = field(init=False)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Attachment.name is required")
        provided = [
            self.content is not None,
            self.url is not None,
            self.path is not None,
        ]
        if sum(provided) != 1:
            raise ValueError("Attachment requires exactly one of 'content', 'url', or 'path'")

        if self.content is not None:
            object.__setattr__(self, "source", AttachmentSource.INLINE)
            if self.mime_type == DEFAULT_MIME_TYPE:
                object.__setattr__(
                    self, "mime_type", detect_mime_type(self.content, filename=self.name)
                )
            if self.size is None:
                object.__setattr__(self, "size", len(self.content))
            if self.checksum is None:
                object.__setattr__(self, "checksum", sha256(self.content).hexdigest())
        elif self.url is not None:
            object.__setattr__(self, "source", AttachmentSource.URL)
            if self.mime_type == DEFAULT_MIME_TYPE:
                guess = guess_mime_type(self.name)
                if guess is not None:
                    object.__setattr__(self, "mime_type", guess)
        else:
            object.__setattr__(self, "source", AttachmentSource.PATH)
            if self.mime_type == DEFAULT_MIME_TYPE:
                guess = guess_mime_type(self.name)
                if guess is not None:
                    object.__setattr__(self, "mime_type", guess)

    @property
    def kind(self) -> str:
        """Return the coarse category for this attachment."""
        return classify_kind(self.mime_type)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the attachment.

        Inline content is omitted so the dictionary can be safely logged.
        Consumers that need the bytes should read :attr:`content` directly.
        """
        return {
            "name": self.name,
            "mime_type": self.mime_type,
            "source": self.source.value,
            "url": self.url,
            "path": self.path,
            "size": self.size,
            "checksum": self.checksum,
            "kind": self.kind,
            "extras": dict(self.extras),
        }
