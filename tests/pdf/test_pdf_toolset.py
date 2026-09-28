# pyright: strict
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import pytest
from maivn import Agent
from maivn._internal.compat.decorators import (
    ARGUMENT_PRODUCER_REQUIREMENTS_ATTR,
)
from pydantic import TypeAdapter, ValidationError
from pypdf import PdfReader

import maivn_tools
from maivn_tools.connectors.pdf.models import PDFBlock, PDFDocumentHandle, PDFHeadingBlock


def test_pdf_tools_publish_state_and_composition_dependency_contracts(tmp_path: Path) -> None:
    tools = Agent(name='pdf-contract', api_key='test-key').add_toolset(
        maivn_tools.PDFToolSet(tmp_path)
    )
    by_name = {tool.name: tool for tool in tools}

    read_schema = by_name['PDF_read_document'].output_schema
    assert isinstance(read_schema, dict)
    assert read_schema['required'] == ['document', 'compositions', 'outline']
    placement_schema = by_name['PDF_put_block'].input_schema
    definitions = placement_schema['$defs']
    assert 'composition' in definitions['PDFContentBlock']['required']
    assert definitions['PDFHeadingBlock']['required'] == ['type', 'composition', 'level']
    assert definitions['PDFHeadingBlock']['properties']['level']['minimum'] == 1
    assert definitions['PDFHeadingBlock']['properties']['level']['maximum'] == 9
    assert definitions['PDFLayoutBlock']['properties']['type']['enum'] == ['page_break', 'spacer']
    assert placement_schema['properties']['block']['anyOf'] == [
        {'$ref': '#/$defs/PDFContentBlock'},
        {'$ref': '#/$defs/PDFHeadingBlock'},
        {'$ref': '#/$defs/PDFLayoutBlock'},
    ]
    assert not getattr(
        by_name['PDF_put_block'].target,
        ARGUMENT_PRODUCER_REQUIREMENTS_ATTR,
        (),
    )


def _build_pdf(toolset: maivn_tools.PDFToolSet, filename: str) -> PDFDocumentHandle:
    doc = toolset.create_document(filename)
    title = toolset.compose_artifact(doc, 'title', {'kind': 'text', 'text': 'Artifact Toolsets'})
    body = toolset.compose_artifact(
        doc,
        'body',
        {'kind': 'text', 'text': 'The model plans; the local toolset builds.'},
    )
    items = toolset.compose_artifact(
        doc, 'items', {'kind': 'list', 'items': ['Compose', 'Inspect', 'Render']}
    )
    toolset.put_block(doc, 'title', {'type': 'title', 'composition': title}, {'anchor': 'end'})
    toolset.put_block(doc, 'body', {'type': 'paragraph', 'composition': body}, {'anchor': 'end'})
    toolset.put_block(
        doc, 'items', {'type': 'bullet_list', 'composition': items}, {'anchor': 'end'}
    )
    return doc


def test_pdf_stepwise_chain_is_retry_safe_inspectable_and_deterministic(tmp_path: Path) -> None:
    left = maivn_tools.PDFToolSet(tmp_path / 'left')
    right = maivn_tools.PDFToolSet(tmp_path / 'right')
    left_doc = _build_pdf(left, 'proof.pdf')
    right_doc = _build_pdf(right, 'proof.pdf')

    revised = left.compose_artifact(left_doc, 'body', {'kind': 'text', 'text': 'Revised locally.'})
    left.put_block(
        left_doc, 'body', {'type': 'paragraph', 'composition': revised}, {'anchor': 'end'}
    )
    left.compose_artifact(
        left_doc,
        'body',
        {'kind': 'text', 'text': 'The model plans; the local toolset builds.'},
    )
    left.put_block(
        left_doc, 'body', {'type': 'paragraph', 'composition': revised}, {'anchor': 'end'}
    )

    state = cast('dict[str, Any]', left.read_document(left_doc))
    assert [entry['block_id'] for entry in state['outline']] == ['title', 'body', 'items']
    assert len([item for item in state['compositions'] if item['composition_id'] == 'body']) == 1

    left_file = left.render_document(left_doc)
    right_file = right.render_document(right_doc)
    assert left_file.sha256 == right_file.sha256
    assert Path(left_file.path).read_bytes() == Path(right_file.path).read_bytes()
    reader = PdfReader(left_file.path)
    assert len(reader.pages) == 1
    assert 'Artifact Toolsets' in (reader.pages[0].extract_text() or '')


def test_pdf_refuses_inline_content_traversal_and_overwrite(tmp_path: Path) -> None:
    pdf = maivn_tools.PDFToolSet(tmp_path)
    doc = pdf.create_document('proof.pdf')
    with pytest.raises(maivn_tools.CompositionDependencyError, match='PDF_compose_artifact'):
        pdf.put_block(
            doc,
            'body',
            {'type': 'paragraph', 'composition': 'inline'},  # type: ignore[typeddict-item]
            {'anchor': 'end'},
        )
    with pytest.raises(ValueError, match='directly beneath output_dir'):
        pdf.create_document('../escape.pdf')
    pdf.render_document(doc)
    with pytest.raises(FileExistsError):
        pdf.render_document(doc)


def test_pdf_concurrent_handles_and_one_shot_use_the_same_workspace_core(tmp_path: Path) -> None:
    pdf = maivn_tools.PDFToolSet(tmp_path)

    def create_handle(_: int) -> PDFDocumentHandle:
        return pdf.create_document('same.pdf')

    with ThreadPoolExecutor(max_workers=4) as executor:
        handles = list(executor.map(create_handle, range(8)))
    assert len({handle['document_id'] for handle in handles}) == 8

    generated = pdf.create_pdf(
        'small.pdf',
        {'blocks': [{'block_id': 'body', 'type': 'paragraph', 'content': 'One-shot'}]},
    )
    assert generated.workspace is not None
    state = cast(
        'dict[str, Any]',
        pdf.read_document(cast('PDFDocumentHandle', generated.workspace)),
    )
    assert state['compositions'][0]['content']['text'] == 'One-shot'


@pytest.mark.parametrize('kind', ['title', 'heading', 'paragraph', 'bullet_list', 'table', 'image'])
def test_pdf_content_schema_requires_composition(kind: str) -> None:
    """Content placements cannot advertise the invalid shape seen in live model output."""
    adapter: TypeAdapter[PDFBlock] = TypeAdapter(PDFBlock)
    with pytest.raises(ValidationError):
        adapter.validate_python({'type': kind, 'level': 1, 'height': 90})
    valid: dict[str, Any] = {
        'type': kind,
        'composition': {'document_id': 'document', 'composition_id': 'content'},
    }
    if kind == 'heading':
        valid['level'] = 1
    validated = adapter.validate_python(valid)
    assert 'composition' in validated
    assert validated['composition']['composition_id'] == 'content'


def test_pdf_heading_schema_requires_bounded_level() -> None:
    adapter: TypeAdapter[PDFBlock] = TypeAdapter(PDFBlock)
    heading = {
        'type': 'heading',
        'composition': {'document_id': 'document', 'composition_id': 'heading'},
    }
    for level in (None, 0, 10):
        candidate = {**heading, **({'level': level} if level is not None else {})}
        with pytest.raises(ValidationError):
            adapter.validate_python(candidate)
    for level in (1, 9):
        validated = cast('PDFHeadingBlock', adapter.validate_python({**heading, 'level': level}))
        assert validated['level'] == level


@pytest.mark.parametrize('kind', ['page_break', 'spacer'])
def test_pdf_layout_schema_retains_reference_free_blocks(kind: str) -> None:
    assert TypeAdapter(PDFBlock).validate_python({'type': kind})['type'] == kind
