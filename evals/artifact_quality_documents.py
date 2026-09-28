"""Public-toolset report fixtures and machine-checkable document quality evidence."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from docx import Document
from pypdf import PdfReader

from maivn_tools import DocumentsToolSet, PDFToolSet

UNICODE_SAMPLE = 'Café expansion in Montréal costs €125,000 ± 5% \u2013 approved scope.'
INITIAL_DECISION = 'Approve the staged launch with a budget of $125,000.'
REVISED_DECISION = 'Approve the staged launch with a budget of $118,000.'
ROW_COUNT = 28


def expected_table_rows() -> list[list[str]]:
    """Define the fixture records independently of any rendered output."""
    return [
        ['Package', 'Acceptance evidence', 'Owner'],
        *[
            [
                f'WP-{index:02d}',
                'Regional readiness review confirms training completion, support coverage, '
                'handoff records and escalation contacts before the release decision.',
                ['Operations', 'Delivery', 'Service'][index % 3],
            ]
            for index in range(1, ROW_COUNT + 1)
        ],
    ]


def build_fixture(tools: Any, filename: str) -> Any:
    doc = tools.create_document(filename)

    def put(key: str, kind: str, content: dict[str, object], **extra: object) -> None:
        reference = tools.compose_artifact(doc, key, content)
        tools.put_block(
            doc, key, {'type': kind, 'composition': reference, **extra}, {'anchor': 'end'}
        )

    put('title', 'title', {'kind': 'text', 'text': 'Regional service expansion proposal'})
    put('decision', 'paragraph', {'kind': 'text', 'text': INITIAL_DECISION})
    put('overview', 'heading', {'kind': 'text', 'text': 'Decision and delivery scope'}, level=1)
    put('unicode', 'paragraph', {'kind': 'text', 'text': UNICODE_SAMPLE})
    for index in range(3):
        put(
            f'context-{index}',
            'paragraph',
            {
                'kind': 'text',
                'text': (
                    'The proposal extends existing service coverage through three regional teams. '
                    'Each team completes training and validates the support process before launch. '
                    'Operations will review readiness weekly and release funding after the '
                    'acceptance checks are complete. The table records comparable work packages, '
                    'their evidence requirements and accountable owners.'
                ),
            },
        )
    put('delivery', 'heading', {'kind': 'text', 'text': 'Delivery work packages'}, level=1)
    put('packages', 'table', {'kind': 'table', 'rows': expected_table_rows()})
    put('next', 'heading', {'kind': 'text', 'text': 'Next steps and ownership'}, level=1)
    put(
        'actions',
        'numbered_list',
        {
            'kind': 'list',
            'items': [
                'Confirm regional owners.',
                'Review the acceptance records.',
                'Record the funding decision and publish the launch schedule.',
            ],
        },
    )
    return doc


def inspect_docx(path: Path) -> dict[str, object]:
    document = Document(str(path))
    text = '\n'.join(paragraph.text for paragraph in document.paragraphs)
    tables = document.tables
    headers_repeat = bool(tables) and len(
        document.element.xpath('./w:body/w:tbl/w:tr[1]/w:trPr/w:tblHeader')
    ) == len(tables)
    return {
        'unicode_preserved': UNICODE_SAMPLE in text,
        'table_records_complete': [
            [[cell.text for cell in row.cells] for row in table.rows] for table in tables
        ]
        == [expected_table_rows()],
        'table_headers_repeat': headers_repeat,
        'revised_decision': REVISED_DECISION in text,
        'initial_decision': INITIAL_DECISION in text,
    }


def _pdf_records_complete(text: str) -> bool:
    """Compare ordered record text across page breaks, ignoring only whitespace/headers."""
    normalized = ' '.join(text.split())
    _, start, tail = normalized.partition('Delivery work packages')
    table_text, end, _ = tail.partition('Next steps and ownership')
    if not start or not end:
        return False
    rows = expected_table_rows()
    header = ' '.join(rows[0])
    actual = ' '.join(table_text.replace(header, ' ').split())
    expected = ' '.join(' '.join(row) for row in rows[1:])
    return actual == expected


def inspect_pdf(path: Path) -> dict[str, object]:
    reader = PdfReader(path)
    texts = [page.extract_text() or '' for page in reader.pages]
    text = '\n'.join(texts)
    starts: list[float] = []
    page_width = float(reader.pages[0].mediabox.width)

    def visit(value: str, cm: list[float], tm: list[float], _: object, __: float) -> None:
        if value.strip():
            starts.append(float(cm[4]) + float(tm[4]))

    for page in reader.pages:
        page.extract_text(visitor_text=visit)
    return {
        'page_count': len(reader.pages),
        'unicode_preserved': UNICODE_SAMPLE in text,
        'table_records_complete': _pdf_records_complete(text),
        'table_headers_repeat': all(
            'Acceptance evidence' in item for item in texts if 'WP-' in item
        ),
        'text_starts_within_page': all(0 <= start < page_width for start in starts),
        'revised_decision': REVISED_DECISION in text,
        'initial_decision': INITIAL_DECISION in text,
    }


def run(output_dir: Path) -> dict[str, object]:
    """Create paired report revisions; visual review is a separate required gate."""
    output_dir.mkdir(parents=True, exist_ok=True)
    formats: dict[str, object] = {}
    for extension, factory, inspector in (
        ('docx', DocumentsToolSet, inspect_docx),
        ('pdf', PDFToolSet, inspect_pdf),
    ):
        tools = factory(output_dir / extension / 'workspace')
        doc = build_fixture(tools, f'proposal.{extension}')
        initial = tools.render_document(doc, overwrite=True)
        initial_path = output_dir / f'proposal-initial.{extension}'
        shutil.copyfile(initial.path, initial_path)
        initial_hash = hashlib.sha256(initial_path.read_bytes()).hexdigest()
        tools.compose_artifact(doc, 'decision', {'kind': 'text', 'text': REVISED_DECISION})
        revised = tools.render_document(doc, overwrite=True)
        revised_path = output_dir / f'proposal-revised.{extension}'
        shutil.copyfile(revised.path, revised_path)
        repeated = tools.render_document(doc, overwrite=True)
        if extension == 'docx':
            initial_document, revised_document = Document(initial.path), Document(revised.path)
            formatting_preserved = (
                initial_document.styles.element.xml == revised_document.styles.element.xml
                and [table.xml for table in initial_document.element.xpath('./w:body/w:tbl')]
                == [table.xml for table in revised_document.element.xpath('./w:body/w:tbl')]
            )
            initial_text = '\n'.join(item.text for item in initial_document.paragraphs)
            revised_text = '\n'.join(item.text for item in revised_document.paragraphs)
        else:
            initial_reader, revised_reader = PdfReader(initial.path), PdfReader(revised.path)
            initial_text = '\n'.join(page.extract_text() or '' for page in initial_reader.pages)
            revised_text = '\n'.join(page.extract_text() or '' for page in revised_reader.pages)
            formatting_preserved = len(initial_reader.pages) == len(revised_reader.pages)
        formats[extension] = {
            'paths': {'initial': str(initial_path), 'revised': str(revised_path)},
            'initial': inspector(initial_path),
            'revised': inspector(revised_path),
            'checks': {
                'revision_changed_bytes': initial.sha256 != revised.sha256,
                'initial_preserved': initial_hash
                == hashlib.sha256(Path(initial.path).read_bytes()).hexdigest(),
                'deterministic_revision': revised.sha256 == repeated.sha256,
                'revision_content_preserved': (
                    initial_text.replace(INITIAL_DECISION, REVISED_DECISION) == revised_text
                ),
                'revision_layout_structure_preserved': formatting_preserved,
            },
        }
    evidence: dict[str, object] = {
        'formats': formats,
        'limitations': [
            'Machine checks cannot establish visual quality. Render and inspect every page.',
            'The PDF font covers Western European text; other scripts require a supported font.',
            'Text starts detect gross overflow; glyph bounds and overlap need visual inspection.',
            'PDF rows taller than a page are not split; divide oversized records before rendering.',
            'PDF revision layout checks page count; final page images still require comparison.',
        ],
    }
    (output_dir / 'evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    return evidence
