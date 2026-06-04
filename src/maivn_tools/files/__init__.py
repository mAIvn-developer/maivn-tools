"""File and document primitives shared across connectors."""

from __future__ import annotations

from .attachments import Attachment, AttachmentSource
from .extra_extractors import (
    DocxTextExtractor,
    HtmlTextExtractor,
    PdfTextExtractor,
    register_default_extractors,
)
from .extractors import (
    ExtractionResult,
    TextExtractor,
    UTF8TextExtractor,
    extractor_for,
    register_extractor,
)
from .mime import (
    DEFAULT_MIME_TYPE,
    classify_kind,
    detect_mime_type,
    guess_mime_type,
)
from .transfers import (
    TransferOutcome,
    TransferProgress,
    TransferStatus,
)

__all__ = [
    "Attachment",
    "AttachmentSource",
    "DEFAULT_MIME_TYPE",
    "DocxTextExtractor",
    "ExtractionResult",
    "HtmlTextExtractor",
    "PdfTextExtractor",
    "TextExtractor",
    "TransferOutcome",
    "TransferProgress",
    "TransferStatus",
    "UTF8TextExtractor",
    "classify_kind",
    "detect_mime_type",
    "extractor_for",
    "guess_mime_type",
    "register_default_extractors",
    "register_extractor",
]
