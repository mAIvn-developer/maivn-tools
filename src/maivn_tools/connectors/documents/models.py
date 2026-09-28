"""Structured contracts for document generation tools."""

# pyright: strict

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from ..artifacts.images import ImagePlacement, ImageReference


class DocumentHandle(TypedDict):
    """Stable reference to one persisted document workspace."""

    document_id: str
    filename: str


class CompositionReference(TypedDict):
    """Reference returned by ``DOCUMENTS_compose_artifact``."""

    document_id: str
    composition_id: str


class CompositionContent(TypedDict):
    """Authored prose, list items, or rectangular table data."""

    kind: Literal['text', 'list', 'table', 'image']
    image: NotRequired[ImageReference]
    text: NotRequired[str]
    items: NotRequired[list[str]]
    rows: NotRequired[list[list[str]]]


class DocumentContentBlock(TypedDict):
    """Place prose, a short title, list, or table from an existing composition."""

    type: Literal['title', 'paragraph', 'bullet_list', 'numbered_list', 'table']
    composition: CompositionReference


class DocumentHeadingBlock(TypedDict):
    """Place a short heading label separately from its section's body prose."""

    type: Literal['heading']
    composition: CompositionReference
    level: Literal[1, 2, 3, 4, 5, 6, 7, 8, 9]


class DocumentImageBlock(TypedDict):
    """Place an admitted image with explicit dimensions and alignment."""

    type: Literal['image']
    composition: CompositionReference
    image_placement: ImagePlacement


class DocumentPageBreak(TypedDict):
    """Start a new page without a content reference."""

    type: Literal['page_break']


DocumentBlock = DocumentContentBlock | DocumentHeadingBlock | DocumentImageBlock | DocumentPageBreak


class BlockPosition(TypedDict):
    anchor: Literal['start', 'end', 'before', 'after']
    block_id: NotRequired[str]


class CompositionState(TypedDict):
    """One inspectable authored composition in a document workspace."""

    composition_id: str
    content: CompositionContent


class DocumentState(TypedDict):
    """Current inspectable document workspace state."""

    document: DocumentHandle
    compositions: list[CompositionState]
    outline: list[dict[str, object]]


class OneShotBlock(TypedDict):
    block_id: str
    type: Literal[
        'title',
        'heading',
        'paragraph',
        'bullet_list',
        'numbered_list',
        'table',
        'page_break',
    ]
    level: NotRequired[int]
    content: NotRequired[str]
    items: NotRequired[list[str]]
    rows: NotRequired[list[list[str]]]


class OneShotDocument(TypedDict):
    """Small-document input consumed by the ``create_docx`` convenience tool."""

    blocks: list[OneShotBlock]
