"""MIME detection helpers with magic-number sniffing and extension fallback.

The helpers prefer content-based detection but fall back to extension hints
when the bytes are inconclusive. They never raise: callers always get a
best-effort answer, with the unknown sentinel
:data:`DEFAULT_MIME_TYPE` returned for opaque blobs.

The detector covers the file types that show up most often in connector
workflows: documents, spreadsheets, presentations, common images, archives,
text, and JSON. Anything else can be plugged in by extending the
``_MAGIC_TABLE``.
"""
# pyright: strict

from __future__ import annotations

import mimetypes
from enum import Enum
from os import PathLike

# MARK: Constants

DEFAULT_MIME_TYPE = "application/octet-stream"


# MARK: Magic-number table


class _MagicEntry:
    __slots__ = ("offset", "magic", "mime")

    def __init__(self, offset: int, magic: bytes, mime: str) -> None:
        self.offset = offset
        self.magic = magic
        self.mime = mime


_MAGIC_TABLE: list[_MagicEntry] = [
    _MagicEntry(0, b"%PDF-", "application/pdf"),
    _MagicEntry(0, b"PK\x03\x04", "application/zip"),
    _MagicEntry(0, b"\x1f\x8b", "application/gzip"),
    _MagicEntry(0, b"BZh", "application/x-bzip2"),
    _MagicEntry(0, b"\x89PNG\r\n\x1a\n", "image/png"),
    _MagicEntry(0, b"GIF87a", "image/gif"),
    _MagicEntry(0, b"GIF89a", "image/gif"),
    _MagicEntry(0, b"\xff\xd8\xff", "image/jpeg"),
    _MagicEntry(0, b"RIFF", "image/webp"),
    _MagicEntry(0, b"<svg", "image/svg+xml"),
    _MagicEntry(0, b"<?xml", "application/xml"),
    _MagicEntry(0, b"{\\rtf", "application/rtf"),
    _MagicEntry(0, b"MZ", "application/x-msdownload"),
    _MagicEntry(0, b"\x7fELF", "application/x-elf"),
    _MagicEntry(0, b"OggS", "audio/ogg"),
    _MagicEntry(0, b"ID3", "audio/mpeg"),
    _MagicEntry(0, b"fLaC", "audio/flac"),
    _MagicEntry(4, b"ftypmp4", "video/mp4"),
    _MagicEntry(4, b"ftypisom", "video/mp4"),
    _MagicEntry(4, b"ftypqt", "video/quicktime"),
]


_OOXML_PARTS: dict[str, str] = {
    "word/document.xml": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    "xl/workbook.xml": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "ppt/presentation.xml": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
}


# MARK: Kind classification


class _Kind(str, Enum):
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"
    PDF = "pdf"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    ARCHIVE = "archive"
    TEXT = "text"
    DATA = "data"
    OTHER = "other"


_KIND_PREFIXES: list[tuple[str, _Kind]] = [
    ("image/", _Kind.IMAGE),
    ("audio/", _Kind.AUDIO),
    ("video/", _Kind.VIDEO),
    ("text/", _Kind.TEXT),
]


_KIND_EXACT: dict[str, _Kind] = {
    "application/pdf": _Kind.PDF,
    "application/zip": _Kind.ARCHIVE,
    "application/gzip": _Kind.ARCHIVE,
    "application/x-bzip2": _Kind.ARCHIVE,
    "application/x-tar": _Kind.ARCHIVE,
    "application/json": _Kind.DATA,
    "application/xml": _Kind.DATA,
    "application/rtf": _Kind.DOCUMENT,
    "application/msword": _Kind.DOCUMENT,
    "application/vnd.ms-excel": _Kind.SPREADSHEET,
    "application/vnd.ms-powerpoint": _Kind.PRESENTATION,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": _Kind.DOCUMENT,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": _Kind.SPREADSHEET,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        _Kind.PRESENTATION
    ),
}


# MARK: Detection helpers


def detect_mime_type(
    data: bytes,
    *,
    filename: str | PathLike[str] | None = None,
) -> str:
    """Detect the MIME type of ``data``, falling back to filename hints.

    The detector inspects the first 64 bytes of ``data`` against a small
    magic-number table and, for ZIP-based containers, sniffs the central
    directory for OOXML signatures. When neither check succeeds it consults
    :func:`mimetypes.guess_type` using the supplied filename. Returns
    :data:`DEFAULT_MIME_TYPE` when nothing matches.
    """
    if data:
        magic_hit = _scan_magic(data)
        if magic_hit is not None:
            if magic_hit == "application/zip":
                return _classify_zip_container(data) or magic_hit
            return magic_hit
    if filename is not None:
        hint = guess_mime_type(filename)
        if hint is not None:
            return hint
    return DEFAULT_MIME_TYPE


def guess_mime_type(filename: str | PathLike[str]) -> str | None:
    """Return the MIME type implied by ``filename``'s extension, if any."""
    guessed, _ = mimetypes.guess_type(str(filename))
    return guessed


def classify_kind(mime: str) -> str:
    """Group ``mime`` into a coarse category for catalogs and routing."""
    if mime in _KIND_EXACT:
        return _KIND_EXACT[mime].value
    for prefix, kind in _KIND_PREFIXES:
        if mime.startswith(prefix):
            return kind.value
    return _Kind.OTHER.value


def _scan_magic(data: bytes) -> str | None:
    head = data[:64]
    for entry in _MAGIC_TABLE:
        if entry.offset + len(entry.magic) > len(head):
            continue
        if head[entry.offset : entry.offset + len(entry.magic)] == entry.magic:
            return entry.mime
    return None


def _classify_zip_container(data: bytes) -> str | None:
    snippet = data[: min(len(data), 65536)]
    for part, mime in _OOXML_PARTS.items():
        if part.encode("ascii") in snippet:
            return mime
    return None
