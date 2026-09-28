from pathlib import Path

import pytest
from pypdf import PdfReader

from evals.artifact_quality_documents import build_fixture, inspect_pdf
from maivn_tools import PDFToolSet


def test_pdf_report_wraps_long_tables_inside_the_page_and_repeats_headers(tmp_path: Path) -> None:
    tools = PDFToolSet(tmp_path)
    handle = build_fixture(tools, 'report.pdf')
    result = tools.render_document(handle)
    evidence = inspect_pdf(Path(result.path))
    assert evidence['text_starts_within_page']
    assert evidence['table_records_complete']
    assert evidence['table_headers_repeat']
    pages = [page.extract_text() or '' for page in PdfReader(result.path).pages]
    assert any('Delivery work packages' in page and 'WP-01' in page for page in pages)
    assert 'WP-01' in pages[0]
    assert all(page.count('Acceptance evidence') == 1 for page in pages if 'WP-' in page)


def test_pdf_keeps_literal_text(tmp_path: Path) -> None:
    tools = PDFToolSet(tmp_path)
    doc = tools.create_document('literal.pdf')
    text = 'Approval requires <owner> & cost < 125000; Café € ± \u2013.'
    ref = tools.compose_artifact(doc, 'body', {'kind': 'text', 'text': text})
    tools.put_block(doc, 'body', {'type': 'paragraph', 'composition': ref}, {'anchor': 'end'})
    assert text in PdfReader(tools.render_document(doc).path).pages[0].extract_text()


def test_pdf_rejects_missing_glyphs(tmp_path: Path) -> None:
    tools = PDFToolSet(tmp_path)
    doc = tools.create_document('unsupported.pdf')
    ref = tools.compose_artifact(doc, 'body', {'kind': 'text', 'text': '中文'})
    tools.put_block(doc, 'body', {'type': 'paragraph', 'composition': ref}, {'anchor': 'end'})
    with pytest.raises(ValueError, match=r'unsupported.*U\+'):
        tools.render_document(doc, overwrite=True)
