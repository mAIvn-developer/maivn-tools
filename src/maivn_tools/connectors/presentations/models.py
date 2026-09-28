"""Structured contracts for deterministic presentation generation."""

# pyright: strict

from __future__ import annotations

from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import Field

from ..artifacts.images import ImageReference

LIST_INDENT_INCHES = 0.25

SlideX = Annotated[
    float,
    Field(description='Left edge in inches. x >= 0 and x + width <= 13.333 inches.'),
]
SlideY = Annotated[
    float,
    Field(description='Top edge in inches. y >= 0 and y + height <= 7.5 inches.'),
]
SlideWidth = Annotated[
    float,
    Field(description='Positive width in inches. x + width <= 13.333 inches; e.g. 11.9.'),
]
SlideHeight = Annotated[
    float,
    Field(description='Positive height in inches. y + height <= 7.5 inches; e.g. 0.8 for a title.'),
]
FontSize = Annotated[float, Field(description='Font size in points, from 6 to 96.')]


class PresentationHandle(TypedDict):
    presentation_id: str
    filename: str


class PresentationCompositionReference(TypedDict):
    presentation_id: str
    composition_id: str


class ChartSeries(TypedDict):
    name: str
    values: list[float]


class PresentationCompositionContent(TypedDict):
    kind: Literal['text', 'list', 'table', 'chart', 'image']
    image: NotRequired[ImageReference]
    text: NotRequired[str]
    items: NotRequired[list[str]]
    rows: NotRequired[list[list[str]]]
    categories: NotRequired[list[str]]
    series: NotRequired[list[ChartSeries]]


class PresentationCompositionState(TypedDict):
    composition_id: str
    content: PresentationCompositionContent


class PresentationState(TypedDict):
    presentation: PresentationHandle
    compositions: list[PresentationCompositionState]
    slides: list[dict[str, object]]


class PresentationPosition(TypedDict):
    anchor: Literal['start', 'end', 'before', 'after']
    item_id: NotRequired[str]


class PresentationElement(TypedDict):
    type: Literal['title', 'text', 'list', 'table', 'chart', 'image']
    composition: PresentationCompositionReference
    x: SlideX
    y: SlideY
    width: SlideWidth
    height: SlideHeight
    style: NotRequired[Literal['default', 'accent', 'muted']]
    font_size: NotRequired[FontSize]
    font_family: NotRequired[str]
    alignment: NotRequired[Literal['left', 'center', 'right']]


class OneShotElement(TypedDict):
    element_id: str
    type: Literal['title', 'text', 'list', 'table', 'chart']
    content: PresentationCompositionContent
    x: SlideX
    y: SlideY
    width: SlideWidth
    height: SlideHeight
    style: NotRequired[Literal['default', 'accent', 'muted']]
    font_size: NotRequired[FontSize]
    font_family: NotRequired[str]
    alignment: NotRequired[Literal['left', 'center', 'right']]


class OneShotSlide(TypedDict):
    slide_id: str
    layout: NotRequired[Literal['blank']]
    elements: list[OneShotElement]


class OneShotPresentation(TypedDict):
    slides: list[OneShotSlide]
