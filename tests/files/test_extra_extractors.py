# pyright: strict
from __future__ import annotations

import pytest

from maivn_tools.files import (
    DocxTextExtractor,
    HtmlTextExtractor,
    PdfTextExtractor,
    register_default_extractors,
)
from maivn_tools.files.extractors import _REGISTRY  # type: ignore[attr-defined]


def test_html_extractor_strips_script_and_collapses_blocks() -> None:
    html = (
        b"<html><head><style>.x{}</style></head>"
        b"<body><h1>Title</h1><script>bad()</script>"
        b"<p>Hello&nbsp;world</p><p>Second</p></body></html>"
    )
    result = HtmlTextExtractor().extract(html)
    assert "bad()" not in result.text
    assert ".x{}" not in result.text
    assert "Hello" in result.text and "world" in result.text
    assert "Second" in result.text
    assert result.metadata["source_mime"] == "text/html"


def test_html_extractor_handles_empty_input() -> None:
    result = HtmlTextExtractor().extract(b"")
    assert result.text == ""


def test_html_extractor_supports_html_and_xhtml() -> None:
    extractor = HtmlTextExtractor()
    assert extractor.supports("text/html")
    assert extractor.supports("application/xhtml+xml")
    assert not extractor.supports("text/plain")


def test_pdf_extractor_raises_clear_error_without_dependency() -> None:
    pdf = PdfTextExtractor()
    try:
        import pypdf  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="pdf"):
            pdf.extract(b"%PDF-1.4")


def test_docx_extractor_raises_clear_error_without_dependency() -> None:
    docx = DocxTextExtractor()
    try:
        import docx  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="docx"):
            docx.extract(b"")


def test_register_default_extractors_adds_all_three() -> None:
    snapshot = list(_REGISTRY)
    try:
        register_default_extractors()
        types = {
            type(extractor).__name__
            for extractor in _REGISTRY
            if type(extractor).__name__
            in {"HtmlTextExtractor", "PdfTextExtractor", "DocxTextExtractor"}
        }
        assert types == {"HtmlTextExtractor", "PdfTextExtractor", "DocxTextExtractor"}
    finally:
        _REGISTRY[:] = snapshot
