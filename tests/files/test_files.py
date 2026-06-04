# pyright: strict
from __future__ import annotations

import pytest

from maivn_tools.files import (
    Attachment,
    AttachmentSource,
    ExtractionResult,
    TextExtractor,
    TransferOutcome,
    TransferProgress,
    TransferStatus,
    classify_kind,
    detect_mime_type,
    extractor_for,
    guess_mime_type,
    register_extractor,
)


def test_detect_mime_type_magic_numbers() -> None:
    assert detect_mime_type(b"%PDF-1.4\n%...") == "application/pdf"
    assert detect_mime_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert detect_mime_type(b"GIF89a...") == "image/gif"
    assert detect_mime_type(b"\xff\xd8\xff\xe0jpg") == "image/jpeg"


def test_detect_mime_type_falls_back_to_extension() -> None:
    assert detect_mime_type(b"", filename="notes.md") == "text/markdown"
    assert detect_mime_type(b"random", filename="data.unknown") == "application/octet-stream"


def test_detect_mime_type_zip_container_ooxml() -> None:
    body = b"PK\x03\x04" + (b"\x00" * 100) + b"word/document.xml" + (b"\x00" * 10)
    assert detect_mime_type(body) == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_detect_mime_type_zip_without_ooxml_marker() -> None:
    assert detect_mime_type(b"PK\x03\x04" + b"\x00" * 50) == "application/zip"


def test_guess_mime_type_and_classify_kind() -> None:
    assert guess_mime_type("a.json") == "application/json"
    assert classify_kind("image/png") == "image"
    assert classify_kind("application/pdf") == "pdf"
    assert classify_kind("application/zip") == "archive"
    assert classify_kind("application/vnd.example.weird") == "other"


def test_attachment_requires_exactly_one_source() -> None:
    with pytest.raises(ValueError):
        Attachment(name="a")
    with pytest.raises(ValueError):
        Attachment(name="a", content=b"x", url="https://x")


def test_attachment_inline_derives_metadata() -> None:
    inline = Attachment(name="hello.txt", content=b"hello")
    assert inline.source is AttachmentSource.INLINE
    assert inline.mime_type == "text/plain"
    assert inline.size == 5
    assert inline.checksum is not None
    assert inline.kind == "text"
    payload = inline.to_dict()
    assert "content" not in payload
    assert payload["source"] == "inline"


def test_attachment_url_and_path_sources() -> None:
    remote = Attachment(name="x.png", url="https://example.com/x.png")
    assert remote.source is AttachmentSource.URL
    assert remote.mime_type == "image/png"

    local = Attachment(name="x.json", path="/tmp/x.json")
    assert local.source is AttachmentSource.PATH
    assert local.mime_type == "application/json"


def test_text_extractor_registry_dispatches_to_latest() -> None:
    default = extractor_for("text/plain")
    result = default.extract(b"hello")
    assert isinstance(result, ExtractionResult)
    assert result.text == "hello"

    class CustomExtractor(TextExtractor):
        mime_types = ("text/plain",)

        def extract(
            self,
            data: bytes,
            *,
            mime_type: str | None = None,
            filename: str | None = None,
        ) -> ExtractionResult:
            return ExtractionResult(text="custom", mime_type="text/plain")

    register_extractor(CustomExtractor())
    assert extractor_for("text/plain").extract(b"x").text == "custom"


def test_text_extractor_register_validates_type() -> None:
    with pytest.raises(TypeError):
        register_extractor("not an extractor")  # type: ignore[arg-type]


def test_extractor_for_raises_for_unknown_mime() -> None:
    with pytest.raises(LookupError):
        extractor_for("application/x-totally-made-up")


def test_transfer_progress_fraction_safe() -> None:
    assert TransferProgress(transferred=50, total=200).fraction == 0.25
    assert TransferProgress(transferred=10, total=0).fraction is None
    assert TransferProgress(transferred=10).fraction is None


def test_transfer_outcome_is_terminal() -> None:
    outcome = TransferOutcome(status=TransferStatus.SUCCEEDED)
    assert outcome.is_terminal
    assert TransferOutcome(status=TransferStatus.RUNNING).is_terminal is False
