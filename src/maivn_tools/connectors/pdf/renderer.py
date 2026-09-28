"""Deterministic ReportLab rendering from a persisted PDF manifest."""

# pyright: strict

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak,
    Image,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import PDFBlock, PDFCompositionContent
from ..artifacts.images import ImagePlacement, ImageReference, contain_size, image_bytes
from ..documents.layout import table_column_widths


@lru_cache(maxsize=1)
def _register_fonts() -> frozenset[int]:
    """Embed ReportLab's distributed fonts so output is independent of host fonts."""
    font_dir = Path(reportlab.__file__).parent / 'fonts'
    regular = TTFont('MaivnVera', str(font_dir / 'Vera.ttf'))
    bold = TTFont('MaivnVeraBold', str(font_dir / 'VeraBd.ttf'))
    pdfmetrics.registerFont(regular)  # pyright: ignore[reportUnknownMemberType]
    pdfmetrics.registerFont(bold)  # pyright: ignore[reportUnknownMemberType]
    return frozenset(regular.face.charToGlyph).intersection(bold.face.charToGlyph)


def _plain_text(value: str, supported: frozenset[int]) -> str:
    missing = sorted(
        {ord(char) for char in value if not char.isspace() and ord(char) not in supported}
    )
    if missing:
        codes = ', '.join(f'U+{code:04X}' for code in missing[:8])
        raise ValueError(f'PDF text contains unsupported font glyphs: {codes}')
    return escape(value).replace('\n', '<br/>')


def _keep_table_heading(flowables: list[object], table: Table, width: float) -> None:
    """Keep a heading with the table's first record, allowing the rest to paginate.

    ReportLab's normal keepWithNext groups the entire table with a heading and
    unnecessarily moves long tables to a fresh page. Reserve only the measured
    heading, header and first data row, then let Table split between records.
    """
    if not flowables or not isinstance(flowables[-1], Paragraph):
        return
    heading = flowables[-1]
    if not heading.style.name.startswith(('Heading', 'Title')):
        return
    table.wrap(width, 1000000)
    # Row heights are calculated by wrap; ReportLab has no public row-height accessor.
    row_heights = cast('list[float]', cast('Any', table)._rowHeights)  # noqa: SLF001
    _, heading_height = heading.wrap(width, 1000000)
    required = (
        heading_height + heading.getSpaceBefore() + heading.getSpaceAfter() + sum(row_heights[:2])
    )
    heading.keepWithNext = False
    flowables.insert(len(flowables) - 1, CondPageBreak(required))


class _DeterministicCanvas(Canvas):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs['invariant'] = 1
        super().__init__(*args, **kwargs)  # pyright: ignore[reportUnknownMemberType]
        self.setTitle('')
        self.setAuthor('')
        self.setSubject('')
        self.setCreator('mAIvn PDF ToolSet')
        self.setProducer('mAIvn PDF ToolSet')


def render_pdf_bytes(manifest: dict[str, object]) -> bytes:
    """Render byte-stable Letter pages with fixed fonts, margins, and metadata."""
    output = io.BytesIO()
    supported = _register_fonts()
    document = SimpleDocTemplate(
        output,
        pagesize=LETTER,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
        title='',
        author='',
        subject='',
        creator='mAIvn PDF ToolSet',
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        'Body',
        parent=styles['BodyText'],
        fontName='MaivnVera',
        fontSize=10.5,
        leading=14,
        spaceAfter=8,
    )
    title = ParagraphStyle(
        'Title',
        parent=body,
        fontName='MaivnVeraBold',
        fontSize=22,
        leading=27,
        alignment=TA_CENTER,
        spaceAfter=18,
        textColor=colors.black,
        keepWithNext=True,
    )
    heading_styles = {
        level: ParagraphStyle(
            f'Heading{level}',
            parent=body,
            fontName='MaivnVeraBold',
            fontSize=max(12, 18 - level),
            leading=max(15, 22 - level),
            spaceBefore=10,
            spaceAfter=6,
            textColor=colors.black,
            keepWithNext=True,
        )
        for level in range(1, 10)
    }
    compositions = cast('dict[str, PDFCompositionContent]', manifest['compositions'])
    flowables: list[object] = []
    for entry in cast('list[dict[str, object]]', manifest['blocks']):
        block = cast('PDFBlock', entry['block'])
        block_type = block['type']
        if block_type == 'page_break':
            flowables.append(PageBreak())
            continue
        if block_type == 'spacer':
            flowables.append(Spacer(1, cast('float', block.get('height', 12))))
            continue
        reference = block.get('composition')
        if reference is None:
            raise ValueError(f"block type '{block_type}' is missing its composition reference")
        content = compositions[reference['composition_id']]
        if block_type == 'image':
            raw = image_bytes(manifest, cast('ImageReference', content.get('image')))
            placement = cast('ImagePlacement', block.get('image_placement'))
            width, height = contain_size(raw, placement['width_inches'], placement['height_inches'])
            picture = Image(io.BytesIO(raw), width=width * inch, height=height * inch)
            picture.hAlign = cast(
                "Literal['LEFT', 'CENTER', 'RIGHT']", placement['alignment'].upper()
            )
            flowables.append(picture)
        elif block_type == 'title':
            flowables.append(
                Paragraph(_plain_text(cast('str', content.get('text')), supported), title)
            )
        elif block_type == 'heading':
            level = cast('int', block.get('level'))
            flowables.append(
                Paragraph(
                    _plain_text(cast('str', content.get('text')), supported), heading_styles[level]
                )
            )
        elif block_type == 'paragraph':
            flowables.append(
                Paragraph(_plain_text(cast('str', content.get('text')), supported), body)
            )
        elif block_type in {'bullet_list', 'numbered_list'}:
            bullet_type = 'bullet' if block_type == 'bullet_list' else '1'
            items = [
                ListItem(Paragraph(_plain_text(item, supported), body), leftIndent=8)
                for item in cast('list[str]', content.get('items'))
            ]
            flowables.append(
                ListFlowable(
                    cast('list[Any]', items),
                    bulletType=bullet_type,
                    leftIndent=22,
                    bulletFontName='MaivnVera',
                    bulletFontSize=10,
                    spaceAfter=8,
                )
            )
        elif block_type == 'table':
            rows = cast('list[list[str]]', content.get('rows'))
            cell_style = ParagraphStyle('Cell', parent=body, fontSize=9, leading=12, spaceAfter=0)
            header_style = ParagraphStyle('CellHeader', parent=cell_style, fontName='MaivnVeraBold')
            cells = [
                [
                    Paragraph(
                        _plain_text(value, supported), header_style if index == 0 else cell_style
                    )
                    for value in row
                ]
                for index, row in enumerate(rows)
            ]
            # SimpleDocTemplate frames reserve six points of padding on either side.
            table = Table(
                cells,
                colWidths=table_column_widths(rows, document.width - 12),
                repeatRows=1,
                hAlign='LEFT',
                splitByRow=1,
                splitInRow=0,
                spaceAfter=8,
            )
            table.setStyle(
                TableStyle(
                    [
                        ('FONTNAME', (0, 0), (-1, 0), 'MaivnVeraBold'),
                        ('FONTNAME', (0, 1), (-1, -1), 'MaivnVera'),
                        ('FONTSIZE', (0, 0), (-1, -1), 9),
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DCE8F2')),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D9D9D9')),
                        (
                            'ROWBACKGROUNDS',
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor('#F5F7FA')],
                        ),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('LEFTPADDING', (0, 0), (-1, -1), 6),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                        ('TOPPADDING', (0, 0), (-1, -1), 5),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                    ]
                )
            )
            _keep_table_heading(flowables, table, document.width - 12)
            flowables.append(table)
    document.build(cast('list[Any]', flowables), canvasmaker=_DeterministicCanvas)
    return output.getvalue()
