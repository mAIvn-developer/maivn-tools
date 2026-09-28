"""Reject the empty matrix emitted by the live model before workbook mutation."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from maivn import Agent
from pydantic import TypeAdapter, ValidationError

from maivn_tools import WorkbooksToolSet
from maivn_tools.connectors.workbooks.models import RangeFormat, WorkbookCompositionContent


@pytest.mark.parametrize(
    'content',
    cast(
        'list[dict[str, object]]',
        [
            {'kind': 'matrix', 'values': [], 'formulas': []},
            {'kind': 'matrix', 'values': [[]]},
            {'kind': 'row', 'values': []},
            {'kind': 'formulas', 'formulas': [[]]},
        ],
    ),
)
def test_empty_ranges_fail_typed_argument_validation(content: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(WorkbookCompositionContent).validate_python(content)


def test_model_schema_describes_nonempty_ranges_in_both_workbook_tools(tmp_path: Path) -> None:
    tools = Agent(name='workbook-schema', api_key='test-key').add_toolset(
        WorkbooksToolSet(tmp_path)
    )
    for tool in tools:
        if tool.name not in {'WORKBOOKS_create_xlsx', 'WORKBOOKS_compose_artifact'}:
            continue
        contents = list(_range_contents(tool.input_schema))
        assert contents
        for content in contents:
            for branch in content['values']['anyOf']:
                if branch.get('type') == 'null':
                    continue
                assert branch.get('minItems') == 1
                if branch['items'].get('type') == 'array':
                    assert branch['items'].get('minItems') == 1
            formula_branches = content['formulas']['anyOf']
            formula_matrix = next(item for item in formula_branches if item['type'] == 'array')
            assert formula_matrix.get('minItems') == 1
            assert formula_matrix['items'].get('minItems') == 1


def _range_contents(schema: object) -> Iterator[dict[str, Any]]:
    if isinstance(schema, dict):
        node = cast('dict[str, Any]', schema)
        properties = cast('dict[str, Any]', node.get('properties', {}))
        if {'kind', 'values', 'formulas'} <= properties.keys():
            yield properties
        for value in node.values():
            yield from _range_contents(value)
    elif isinstance(schema, list):
        for value in cast('list[object]', schema):
            yield from _range_contents(value)


def test_valid_matrix_retains_zero_false_and_empty_cells() -> None:
    content = {'kind': 'matrix', 'values': [['Name', 'Value'], ['', 0], [None, False]]}
    assert TypeAdapter(WorkbookCompositionContent).validate_python(content) == content


@pytest.mark.parametrize('anchor', ['', 'A0', '1A', 'A1:B4'])
def test_invalid_chart_anchor_fails_schema_before_openpyxl(anchor: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(RangeFormat).validate_python(
            {'chart': {'type': 'bar', 'title': '', 'anchor': anchor}}
        )


def test_blank_range_start_is_a_value_error_without_workspace_mutation(tmp_path: Path) -> None:
    books = WorkbooksToolSet(tmp_path)
    book = books.create_workbook('coordinates.xlsx')
    books.put_sheet(book, 'main', 'Main', {'anchor': 'end'})
    ref = books.compose_artifact(book, 'one', {'kind': 'scalar', 'value': 1})
    with pytest.raises(ValueError, match='invalid worksheet coordinate'):
        books.put_range(book, 'one', 'main', '', ref, {})
    assert books.read_workbook(book)['sheets'][0]['ranges'] == []


@pytest.mark.parametrize('merge', ['', 'none', 'A0:B4', 'A1:BOGUS'])
def test_invalid_merge_is_rejected_before_workbook_mutation(merge: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(RangeFormat).validate_python({'merge': merge})


def test_optional_format_fields_can_be_explicitly_null_for_strict_models(tmp_path: Path) -> None:
    books = WorkbooksToolSet(tmp_path)
    book = books.create_workbook('no-formatting.xlsx')
    books.put_sheet(book, 'main', 'Main', {'anchor': 'end'})
    ref = books.compose_artifact(book, 'one', {'kind': 'scalar', 'value': 3900})
    formatting = TypeAdapter(RangeFormat).validate_python(
        {'style': None, 'number_format': None, 'merge': None, 'chart': None}
    )
    books.put_range(book, 'one', 'main', 'A1', ref, formatting)
    generated = books.render_workbook(book)
    assert Path(generated.path).is_file()
