"""Structured contracts for deterministic PDF generation."""

# pyright: strict

from __future__ import annotations

from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import Field

from ..artifacts.images import ImagePlacement, ImageReference


class PDFDocumentHandle(TypedDict):
    document_id: str
    filename: str


class PDFCompositionReference(TypedDict):
    document_id: str
    composition_id: str


class PDFCompositionContent(TypedDict):
    kind: Literal['text', 'list', 'table', 'image']
    image: NotRequired[ImageReference]
    text: NotRequired[str]
    items: NotRequired[list[str]]
    rows: NotRequired[list[list[str]]]


class PDFCompositionState(TypedDict):
    composition_id: str
    content: PDFCompositionContent


class PDFDocumentState(TypedDict):
    document: PDFDocumentHandle
    compositions: list[PDFCompositionState]
    outline: list[dict[str, object]]


class PDFContentBlock(TypedDict):
    """One placed block referencing a composition.

    A title or heading contains only its short label. Place section prose in
    separate paragraph blocks and list items in separate list blocks. A heading
    styles its entire composition, including any embedded newlines, as a heading.
    """

    type: Literal[
        'title',
        'paragraph',
        'bullet_list',
        'numbered_list',
        'table',
        'image',
    ]
    composition: PDFCompositionReference
    image_placement: NotRequired[ImagePlacement]
    height: NotRequired[float]


class PDFHeadingBlock(TypedDict):
    """A placed heading with an explicit outline level."""

    type: Literal['heading']
    composition: PDFCompositionReference
    level: Annotated[int, Field(ge=1, le=9)]


class PDFLayoutBlock(TypedDict):
    """A reference-free page break or vertical spacer."""

    type: Literal['page_break', 'spacer']
    height: NotRequired[float]


PDFBlock = PDFContentBlock | PDFHeadingBlock | PDFLayoutBlock


class PDFBlockPosition(TypedDict):
    anchor: Literal['start', 'end', 'before', 'after']
    block_id: NotRequired[str]


class PDFOneShotBlock(TypedDict):
    block_id: str
    type: Literal[
        'title',
        'heading',
        'paragraph',
        'bullet_list',
        'numbered_list',
        'table',
        'page_break',
        'spacer',
    ]
    level: NotRequired[int]
    height: NotRequired[float]
    content: NotRequired[str]
    items: NotRequired[list[str]]
    rows: NotRequired[list[list[str]]]


class PDFOneShotDocument(TypedDict):
    blocks: list[PDFOneShotBlock]
