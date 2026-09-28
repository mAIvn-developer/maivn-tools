"""Workbook content failures carry actionable, value-free SDK validation rules."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import pytest
from maivn import Agent
from maivn._internal.models import StreamEvent
from maivn._internal.tool_runtime import LocalToolRuntime
from pydantic import ValidationError

from maivn_tools import WorkbooksToolSet
from maivn_tools.connectors.workbooks.models import WorkbookCompositionContent

_SENTINEL = 'SECRET-WORKBOOK-CELL'
_CASES = [
    (
        {'kind': 'matrix', 'values': [[_SENTINEL, 3], [4]]},
        'workbook_matrix_requires_equal_length_rows',
    ),
    (
        {'kind': 'formulas', 'formulas': [['=1', '=2'], ['=3']]},
        'workbook_matrix_requires_equal_length_rows',
    ),
    (
        {'kind': 'matrix', 'values': [_SENTINEL, 3]},
        'workbook_matrix_requires_rows',
    ),
    (
        {'kind': 'row', 'values': [[_SENTINEL, 3]]},
        'workbook_row_requires_flat_values',
    ),
    (
        {'kind': 'formulas', 'formulas': [['']]},
        'workbook_formula_requires_supported_equals_expression_or_null',
    ),
    (
        {'kind': 'formulas', 'formulas': [['=' + _SENTINEL + '()']]},
        'workbook_formula_requires_supported_equals_expression_or_null',
    ),
    (
        {'kind': 'matrix', 'values': [[_SENTINEL]], 'formulas': [['=1']]},
        'workbook_literals_and_formulas_require_separate_compositions',
    ),
    (
        {'kind': 'formulas', 'values': [[_SENTINEL]], 'formulas': [['=1']]},
        'workbook_literals_and_formulas_require_separate_compositions',
    ),
]


@pytest.mark.parametrize(('content', 'rule'), _CASES)
def test_content_errors_preserve_value_error_compatibility_without_values(
    tmp_path: Path, content: dict[str, object], rule: str
) -> None:
    tools = WorkbooksToolSet(tmp_path)
    handle = tools.create_workbook('feedback.xlsx')
    with pytest.raises(ValidationError) as failure:
        tools.compose_artifact(handle, 'invalid', cast('WorkbookCompositionContent', content))
    assert isinstance(failure.value, ValueError)
    assert failure.value.errors(include_input=False)[0]['type'] == rule
    assert _SENTINEL not in str(failure.value)
    assert _SENTINEL not in failure.value.json()
    assert tools.read_workbook(handle)['compositions'] == []


@pytest.mark.parametrize(('content', 'rule'), _CASES)
@pytest.mark.parametrize('private', [False, True])
def test_sdk_outcome_reports_content_repair_rule_without_user_values(
    tmp_path: Path, content: dict[str, object], rule: str, *, private: bool
) -> None:
    tools = WorkbooksToolSet(tmp_path)
    handle = tools.create_workbook('feedback.xlsx')
    agent = Agent(name='Workbook repair feedback', api_key='test-key')
    agent.add_toolset(tools)
    runtime = LocalToolRuntime(
        agent.compile_tools(), private_data={'secret': _SENTINEL} if private else None
    )
    event = StreamEvent(
        position=1,
        event_type='system_tool_start',
        data={
            'payload': {
                'tool_call': {
                    'call_id': 'invalid-content',
                    'spec_ref': {
                        'tool_id': 'WORKBOOKS_compose_artifact',
                        'namespace': 'sdk',
                        'version': 'v1',
                    },
                    'arguments': {
                        'workbook': handle,
                        'composition_id': _SENTINEL,
                        'content': content,
                    },
                    'lineage': {'session_id': 'ses-feedback', 'invocation_id': 'inv-feedback'},
                }
            }
        },
    )
    outcome = asyncio.run(runtime.outcome_for_event(event))
    assert outcome is not None and outcome.status == 'error'
    assert outcome.error.code == 'sdk_tool_validation_error'
    assert rule in outcome.error.message
    assert 'content.' in outcome.error.message
    assert _SENTINEL not in outcome.model_dump_json()
    assert tools.read_workbook(handle)['compositions'] == []


def test_collision_can_be_retried_after_removing_the_conflicting_range(tmp_path: Path) -> None:
    """Identical placement arguments become valid after the workbook changes."""
    tools = WorkbooksToolSet(tmp_path)
    handle = tools.create_workbook('state-repair.xlsx')
    tools.put_sheet(handle, 'sheet', 'Sheet', {'anchor': 'end'})
    composition = tools.compose_artifact(handle, 'value', {'kind': 'scalar', 'value': 42})
    tools.put_range(handle, 'occupied', 'sheet', 'A1', composition, {})
    agent = Agent(name='Workbook state repair', api_key='test-key')
    agent.add_toolset(tools)
    runtime = LocalToolRuntime(agent.compile_tools(), private_data=None)

    def event(call_id: str) -> StreamEvent:
        return StreamEvent(
            position=1,
            event_type='system_tool_start',
            data={
                'payload': {
                    'tool_call': {
                        'call_id': call_id,
                        'spec_ref': {
                            'tool_id': 'WORKBOOKS_put_range',
                            'namespace': 'sdk',
                            'version': 'v1',
                        },
                        'arguments': {
                            'workbook': handle,
                            'range_id': 'incoming',
                            'sheet_id': 'sheet',
                            'start_cell': 'A1',
                            'composition': composition,
                            'format': {},
                        },
                        'lineage': {'session_id': 'ses-state', 'invocation_id': 'inv-state'},
                    }
                }
            },
        )

    refused = asyncio.run(runtime.outcome_for_event(event('initial')))
    assert refused is not None
    assert refused.status == 'error'
    assert refused.error.code == 'sdk_workbook_range_overlap'
    assert refused.error.retryable is True
    assert tools.remove_range(handle, 'occupied')['removed'] is True
    accepted = asyncio.run(runtime.outcome_for_event(event('after-repair')))
    assert accepted is not None
    assert accepted.status == 'ok'
    assert accepted.result['range_id'] == 'incoming'
