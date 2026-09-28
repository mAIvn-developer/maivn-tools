"""Readback summaries report what has actually been placed in a workbook."""

from pathlib import Path
from typing import Any, cast

from maivn_tools import WorkbooksToolSet


def test_readback_distinguishes_placed_formula_cells_from_unplaced_compositions(
    tmp_path: Path,
) -> None:
    """Removing the placement summary would hide the formula cells that will render."""
    tools = WorkbooksToolSet(tmp_path)
    handle = tools.create_workbook('forecast.xlsx')
    tools.put_sheet(handle, 'forecast', 'Forecast', {'anchor': 'end'})
    revenue = tools.compose_artifact(
        handle,
        'revenue',
        {'kind': 'formulas', 'formulas': [['=B2*C2'], ['=B3*C3']]},
    )
    tools.compose_artifact(
        handle,
        'total',
        {'kind': 'formulas', 'formulas': [['=SUM(D2:D3)']]},
    )
    tools.put_range(handle, 'revenue-range', 'forecast', 'D2', revenue, {})

    readback = cast('dict[str, Any]', tools.read_workbook(handle)['readback'])

    assert readback['placed_formula_count'] == 2
    assert readback['placed_formula_addresses'] == [
        {'sheet_id': 'forecast', 'range_id': 'revenue-range', 'address': 'D2'},
        {'sheet_id': 'forecast', 'range_id': 'revenue-range', 'address': 'D3'},
    ]
    assert readback['placed_ranges'] == [
        {
            'sheet_id': 'forecast',
            'sheet_name': 'Forecast',
            'range_id': 'revenue-range',
            'composition_id': 'revenue',
            'start_cell': 'D2',
            'end_cell': 'D3',
            'row_count': 2,
            'column_count': 1,
            'covered_cell_count': 2,
            'formula_count': 2,
        }
    ]
    assert readback['unplaced_composition_count'] == 1
    assert readback['unplaced_compositions'] == [
        {
            'composition_id': 'total',
            'kind': 'formulas',
            'row_count': 1,
            'column_count': 1,
            'formula_count': 1,
        }
    ]
    assert readback['sheets'] == [
        {
            'sheet_id': 'forecast',
            'sheet_name': 'Forecast',
            'placed_range_count': 1,
            'covered_cell_count': 2,
            'formula_count': 2,
            'row_count': 2,
            'column_count': 1,
        }
    ]


def test_readback_bounds_formula_addresses_with_an_explicit_truncation_flag(
    tmp_path: Path,
) -> None:
    """Returning every formula address would duplicate arbitrarily large workbook content."""
    tools = WorkbooksToolSet(tmp_path)
    handle = tools.create_workbook('bounded.xlsx')
    tools.put_sheet(handle, 'sheet', 'Sheet', {'anchor': 'end'})
    formulas = tools.compose_artifact(
        handle,
        'many-formulas',
        {'kind': 'formulas', 'formulas': [['=1'] for _ in range(101)]},
    )
    tools.put_range(handle, 'many-formulas', 'sheet', 'A1', formulas, {})

    readback = cast('dict[str, Any]', tools.read_workbook(handle)['readback'])

    assert readback['placed_formula_count'] == 101
    assert len(readback['placed_formula_addresses']) == 100
    assert readback['placed_formula_addresses'][0]['address'] == 'A1'
    assert readback['placed_formula_addresses'][-1]['address'] == 'A100'
    assert readback['placed_formula_addresses_truncated'] is True
