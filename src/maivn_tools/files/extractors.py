"""Pluggable text-extractor interfaces.

The Tier 0 kernel ships with a single, dependency-free extractor that handles
plain UTF-8 text. PDF, DOCX, HTML, XLSX, and OCR extractors are intentionally
left optional and dependency-gated; downstream packages can register their
implementations via :func:`register_extractor` without forcing every
``maivn-tools`` consumer to install heavy optional dependencies.

Usage:

.. code-block:: python

    result = extractor_for("text/plain").extract(b"hello")
    print(result.text)
"""
# pyright: strict

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .mime import DEFAULT_MIME_TYPE

# MARK: Result model


@dataclass(frozen=True)
class ExtractionResult:
    """Output of a :class:`TextExtractor`.

    Attributes:
        text: Extracted text. Empty when the source is not textual.
        mime_type: Effective MIME type after extraction.
        metadata: Free-form, JSON-serializable extractor metadata
            (page counts, language hints, OCR confidence, etc.).
    """

    text: str
    mime_type: str = DEFAULT_MIME_TYPE
    metadata: dict[str, Any] = field(default_factory=dict)


# MARK: Extractor interface


class TextExtractor(ABC):
    """Abstract text extractor."""

    mime_types: tuple[str, ...] = ()
    """MIME types this extractor declares support for."""

    @abstractmethod
    def extract(
        self,
        data: bytes,
        *,
        mime_type: str | None = None,
        filename: str | None = None,
    ) -> ExtractionResult:
        """Return an :class:`ExtractionResult` for ``data``."""

    def supports(self, mime_type: str) -> bool:
        """Return True when this extractor declares support for ``mime_type``."""
        return mime_type in self.mime_types


class UTF8TextExtractor(TextExtractor):
    """Dependency-free extractor for plain text MIME types."""

    mime_types = (
        "text/plain",
        "text/markdown",
        "text/csv",
        "text/tab-separated-values",
        "application/json",
        "application/xml",
        "text/xml",
    )

    def extract(
        self,
        data: bytes,
        *,
        mime_type: str | None = None,
        filename: str | None = None,
    ) -> ExtractionResult:
        text = data.decode("utf-8", errors="replace")
        return ExtractionResult(
            text=text,
            mime_type=mime_type or "text/plain",
            metadata={"byte_count": len(data)},
        )


# MARK: Registry

_REGISTRY: list[TextExtractor] = [UTF8TextExtractor()]


def register_extractor(extractor: object) -> None:
    """Register ``extractor`` so :func:`extractor_for` can dispatch to it.

    Later registrations win when multiple extractors claim the same MIME
    type, so downstream packages can override the default UTF-8 extractor
    for specific types if needed.
    """
    if not isinstance(extractor, TextExtractor):
        raise TypeError("register_extractor requires a TextExtractor instance")
    _REGISTRY.append(extractor)


def extractor_for(mime_type: str) -> TextExtractor:
    """Return the most recently registered extractor that supports ``mime_type``.

    Raises:
        LookupError: When no registered extractor claims ``mime_type``.
    """
    for extractor in reversed(_REGISTRY):
        if extractor.supports(mime_type):
            return extractor
    raise LookupError(f"No registered extractor handles MIME type {mime_type!r}")
