"""Structured contracts for deterministic workbook generation."""

# pyright: strict

from __future__ import annotations

from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import Field

CellValue = str | int | float | bool | None
CellRow = Annotated[list[CellValue], Field(min_length=1)]
CellMatrix = Annotated[list[CellRow], Field(min_length=1)]
FormulaRow = Annotated[list[str | None], Field(min_length=1)]
FormulaMatrix = Annotated[list[FormulaRow], Field(min_length=1)]
ExcelCell = Annotated[str, Field(pattern=r'^[A-Za-z]{1,3}[1-9][0-9]{0,6}$')]
ExcelRange = Annotated[
    str,
    Field(pattern=r'^[A-Za-z]{1,3}[1-9][0-9]{0,6}:[A-Za-z]{1,3}[1-9][0-9]{0,6}$'),
]
ExcelNumberFormat = Literal[
    'General',
    '#,##0',
    '#,##0.00',
    '0.0%',
    '0.00%',
    'yyyy-mm-dd',
    'mmm yyyy',
    '$#,##0.00',
]


class WorkbookHandle(TypedDict):
    workbook_id: str
    filename: str


class WorkbookCompositionReference(TypedDict):
    workbook_id: str
    composition_id: str


class WorkbookCompositionContent(TypedDict):
    kind: Annotated[
        Literal['scalar', 'row', 'matrix', 'formulas'],
        Field(
            description=(
                'scalar uses value; row uses a non-empty values list; matrix uses non-empty '
                'values rows of equal length; formulas uses non-empty formulas rows of equal '
                'length. Omit unused fields or set them to null. Empty cells may be null, '
                'but ranges cannot be empty.'
            )
        ),
    ]
    value: NotRequired[CellValue]
    values: NotRequired[CellRow | CellMatrix | None]
    formulas: NotRequired[
        Annotated[
            FormulaMatrix | None,
            Field(
                description=(
                    'Excel formulas using internal A1 references (including other sheets and $), '
                    'numbers, arithmetic, parentheses, percentages, SUM, AVERAGE, MIN, MAX '
                    'or COUNT. '
                    'External references and other functions are unsupported. Use kind=formulas; '
                    'set formulas to null for other kinds. Strings in values are literal data. '
                    'Calculated results are included for supported, bounded acyclic calculations. '
                    'Editable formulas also recalculate in Excel; cyclic or oversized '
                    'calculations require the client spreadsheet engine.'
                )
            ),
        ]
    ]


class WorkbookCompositionState(TypedDict):
    composition_id: str
    content: WorkbookCompositionContent


class WorkbookFormulaAddress(TypedDict):
    """One formula cell that is present in an actual placed range."""

    sheet_id: str
    range_id: str
    address: ExcelCell


class WorkbookPlacedRangeReadback(TypedDict):
    """A rectangular composition placement, including its actual worksheet extent."""

    sheet_id: str
    sheet_name: str
    range_id: str
    composition_id: str
    start_cell: ExcelCell
    end_cell: ExcelCell
    row_count: int
    column_count: int
    covered_cell_count: int
    formula_count: int


class WorkbookUnplacedCompositionReadback(TypedDict):
    """A saved composition with no current worksheet placement."""

    composition_id: str
    kind: Literal['scalar', 'row', 'matrix', 'formulas']
    row_count: int
    column_count: int
    formula_count: int


class WorkbookSheetReadback(TypedDict):
    """Aggregate placement dimensions for one worksheet."""

    sheet_id: str
    sheet_name: str
    placed_range_count: int
    covered_cell_count: Annotated[
        int,
        Field(
            description='Cells covered by placed range rectangles, including explicit null holes.'
        ),
    ]
    formula_count: int
    row_count: Annotated[
        int,
        Field(description='Rows spanned from the first to last placed range, including gaps.'),
    ]
    column_count: Annotated[
        int,
        Field(description='Columns spanned from the first to last placed range, including gaps.'),
    ]


class WorkbookReadback(TypedDict):
    """Bounded render-readiness detail that does not repeat arbitrary cell values."""

    sheet_count: int
    sheets: Annotated[
        list[WorkbookSheetReadback],
        Field(description='First 50 sheet placement summaries in workbook order.'),
    ]
    sheets_truncated: Annotated[
        bool,
        Field(description='True when sheet_count exceeds the 50 returned sheet summaries.'),
    ]
    placed_range_count: int
    placed_ranges: Annotated[
        list[WorkbookPlacedRangeReadback],
        Field(description='First 100 placed ranges in sheet and placement order.'),
    ]
    placed_ranges_truncated: Annotated[
        bool,
        Field(description='True when placed_range_count exceeds the 100 returned range summaries.'),
    ]
    placed_formula_count: int
    placed_formula_addresses: Annotated[
        list[WorkbookFormulaAddress],
        Field(
            description=(
                'First 100 actual formula cells in placed ranges, without repeating formulas.'
            )
        ),
    ]
    placed_formula_addresses_truncated: Annotated[
        bool,
        Field(
            description='True when placed_formula_count exceeds the 100 returned formula addresses.'
        ),
    ]
    unplaced_composition_count: int
    unplaced_compositions: Annotated[
        list[WorkbookUnplacedCompositionReadback],
        Field(description='First 100 saved compositions that have no current range placement.'),
    ]
    unplaced_compositions_truncated: Annotated[
        bool,
        Field(
            description=(
                'True when unplaced_composition_count exceeds the 100 returned unplaced summaries.'
            )
        ),
    ]


class WorkbookState(TypedDict):
    workbook: WorkbookHandle
    compositions: list[WorkbookCompositionState]
    sheets: list[dict[str, object]]
    readback: Annotated[
        WorkbookReadback,
        Field(
            description=(
                'Bounded placement summary for render readiness. It identifies actual placed '
                'ranges and formula addresses separately from composed but unplaced content. '
                'Counts always cover the whole workbook; a true *_truncated field means that '
                'the corresponding detail list stopped at its documented response limit.'
            )
        ),
    ]
    output_file_exists: NotRequired[bool]


class WorkbookPosition(TypedDict):
    anchor: Literal['start', 'end', 'before', 'after']
    sheet_id: NotRequired[str]


class RangeChart(TypedDict):
    type: Literal['bar', 'line']
    title: str
    anchor: ExcelCell
    series_columns: NotRequired[
        Annotated[
            list[Annotated[int, Field(strict=True, ge=1, le=16384)]] | None,
            Field(
                min_length=1,
                description=(
                    'Optional ordered worksheet column numbers to plot: A=1, B=2, etc. '
                    'For Revenue in column D use [4]. Select only the requested measures. '
                    'Columns must be unique and inside the source rectangle after its first '
                    '(category) column. Omit or use null to plot all source measure columns.'
                ),
            ),
        ]
    ]
    source_range: NotRequired[
        Annotated[
            ExcelRange | None,
            Field(
                description=(
                    'Optional rectangle on the same sheet, including one header row and '
                    'a category column followed by numeric series. Use this to chart formula '
                    'cells placed in separately formatted ranges. Defaults to the attached range.'
                )
            ),
        ]
    ]


class RangeFormat(TypedDict):
    style: NotRequired[Literal['body', 'header_row', 'total', 'input', 'accent'] | None]
    number_format: NotRequired[ExcelNumberFormat | None]
    merge: NotRequired[ExcelRange | None]
    chart: NotRequired[RangeChart | None]


class OneShotRange(TypedDict):
    range_id: str
    start_cell: ExcelCell
    content: WorkbookCompositionContent
    format: NotRequired[RangeFormat]


class SheetPrintSettings(TypedDict):
    mode: Literal['auto', 'fit_width', 'actual_size']
    orientation: NotRequired[Literal['portrait', 'landscape']]
    minimum_scale_percent: NotRequired[int]


class OneShotSheet(TypedDict):
    sheet_id: str
    name: str
    freeze_panes: NotRequired[str]
    print_settings: NotRequired[SheetPrintSettings]
    ranges: list[OneShotRange]


class OneShotWorkbook(TypedDict):
    sheets: list[OneShotSheet]
