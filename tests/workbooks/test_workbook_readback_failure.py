"""Regression for a formula composition whose placement was rejected."""

from pathlib import Path

import pytest

from maivn_tools import WorkbooksToolSet


def test_rejected_formula_placement_is_not_reported_as_rendered(tmp_path: Path) -> None:
    tools = WorkbooksToolSet(tmp_path)
    workbook = tools.create_workbook('rejected-placement.xlsx')
    tools.put_sheet(workbook, 'sheet', 'Sheet', {'anchor': 'end'})
    labels = tools.compose_artifact(
        workbook, 'labels', {'kind': 'matrix', 'values': [['Value', 'Total'], [3, None]]}
    )
    formulas = tools.compose_artifact(
        workbook, 'formulas', {'kind': 'formulas', 'formulas': [[None, None], [None, '=A2*2']]}
    )
    tools.put_range(workbook, 'labels-range', 'sheet', 'A1', labels, {})
    with pytest.raises(ValueError, match='overlap'):
        tools.put_range(workbook, 'formula-range', 'sheet', 'A1', formulas, {})

    state = tools.read_workbook(workbook)
    assert len(state['compositions']) == 2
    assert state['readback']['placed_formula_count'] == 0
    assert state['readback']['placed_formula_addresses'] == []
    assert state['readback']['unplaced_compositions'][0]['composition_id'] == 'formulas'
    assert state['readback']['unplaced_compositions'][0]['formula_count'] == 1

    # Repair the state, then retry the originally rejected placement.
    tools.remove_range(workbook, 'labels-range')
    tools.put_range(workbook, 'formula-range', 'sheet', 'A1', formulas, {})
    repaired = tools.read_workbook(workbook)['readback']
    assert repaired['placed_formula_count'] == 1
    assert repaired['placed_formula_addresses'][0]['address'] == 'B2'
    assert {item['composition_id'] for item in repaired['unplaced_compositions']} == {'labels'}
