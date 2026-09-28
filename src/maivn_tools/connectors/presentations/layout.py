"""Conservative layout estimates; final pagination requires an Office renderer."""

from __future__ import annotations

import math
import re
from typing import TypedDict, cast

from .models import LIST_INDENT_INCHES, PresentationCompositionContent, PresentationElement


class LayoutIssue(TypedDict):
    slide_id: str
    element_id: str
    code: str
    message: str


def inspect_layout(manifest: dict[str, object]) -> list[LayoutIssue]:
    """Identify text likely to clip and intersecting element bounds."""
    issues: list[LayoutIssue] = []
    compositions = cast('dict[str, PresentationCompositionContent]', manifest['compositions'])
    for slide in cast('list[dict[str, object]]', manifest['slides']):
        entries = cast('list[dict[str, object]]', slide['elements'])
        for index, entry in enumerate(entries):
            element = cast('PresentationElement', entry['element'])
            content = compositions[element['composition']['composition_id']]
            if element['type'] in {'title', 'text', 'list'}:
                font_size = element.get('font_size', 36 if element['type'] == 'title' else 20)
                # Match renderer margins; estimate glyph width at half a font em.
                indent = LIST_INDENT_INCHES if element['type'] == 'list' else 0
                columns = max(1, int((element['width'] - 0.16 - indent) * 72 / (font_size * 0.5)))
                items = (
                    content.get('items', [])
                    if element['type'] == 'list'
                    else [content.get('text', '')]
                )
                # Advisory only: code examples and deliberate line breaks are valid.
                # Preserve authored text, but let the model review suspicious prose
                # before rendering instead of calling it clean based on bounds alone.
                text_warnings: list[tuple[str, str]] = []
                if any(
                    re.search(r'\\(?:u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|\$)', item) for item in items
                ):
                    text_warnings.append(
                        (
                            'text_literal_escape',
                            'Text contains literal Unicode or currency escapes. Check the intended '
                            'visible characters; keep escapes only when showing them deliberately.',
                        )
                    )
                if element['type'] == 'text' and any(
                    re.search(r'\w[ \t]*[\r\n]+[ \t]*\w', item) for item in items
                ):
                    text_warnings.append(
                        (
                            'text_hard_break',
                            'Body text contains a hard line break. Check that it does not split a '
                            'sentence or replace punctuation. Preserve intentional line breaks.',
                        )
                    )
                for code, message in text_warnings:
                    issues.append(
                        {
                            'slide_id': cast('str', slide['slide_id']),
                            'element_id': cast('str', entry['element_id']),
                            'code': code,
                            'message': message,
                        }
                    )
                lines = sum(
                    max(1, math.ceil(len(line) / columns))
                    for item in items
                    for line in item.split('\n')
                )
                needed = lines * font_size * 1.2 + (
                    8 * len(items) if element['type'] == 'list' else 0
                )
                available = (element['height'] - 0.08) * 72
                if needed > available:
                    issues.append(
                        {
                            'slide_id': cast('str', slide['slide_id']),
                            'element_id': cast('str', entry['element_id']),
                            'code': 'text_overflow',
                            'message': 'Text may overflow. Increase height/width, shorten text, '
                            'or reduce font_size; verify with an Office renderer.',
                        }
                    )
            elif element['type'] == 'table':
                rows = content.get('rows', [])
                if rows and rows[0]:
                    font_size = element.get('font_size', 14)
                    columns = max(
                        1,
                        int((element['width'] / len(rows[0]) - 0.12) * 72 / (font_size * 0.5)),
                    )
                    available = (element['height'] / len(rows) - 0.08) * 72
                    crowded = [
                        str(row_index + 1)
                        for row_index, row in enumerate(rows)
                        if any(
                            sum(max(1, math.ceil(len(line) / columns)) for line in cell.split('\n'))
                            * font_size
                            * 1.2
                            > available
                            for cell in row
                        )
                    ]
                    if crowded:
                        issues.append(
                            {
                                'slide_id': cast('str', slide['slide_id']),
                                'element_id': cast('str', entry['element_id']),
                                'code': 'table_text_overflow',
                                'message': f'Table rows {", ".join(crowded)} may overflow. '
                                'Increase table height/width, shorten cells, or split the table; '
                                'verify with an Office renderer.',
                            }
                        )
            for earlier in entries[:index]:
                other = cast('PresentationElement', earlier['element'])
                if (
                    element['x'] < other['x'] + other['width']
                    and other['x'] < element['x'] + element['width']
                    and element['y'] < other['y'] + other['height']
                    and other['y'] < element['y'] + element['height']
                ):
                    issues.append(
                        {
                            'slide_id': cast('str', slide['slide_id']),
                            'element_id': cast('str', entry['element_id']),
                            'code': 'element_overlap',
                            'message': f'Bounds intersect {earlier["element_id"]}; move or resize '
                            'if this layering is unintended.',
                        }
                    )
    return issues
