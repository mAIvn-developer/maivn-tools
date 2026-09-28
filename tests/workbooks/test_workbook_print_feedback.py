"""Print-layout failures must carry safe, state-repairable SDK feedback."""

import asyncio
from pathlib import Path

import pytest
from maivn import Agent
from maivn._internal.models import StreamEvent
from maivn._internal.tool_runtime import LocalToolRuntime

from maivn_tools import WorkbooksToolSet


@pytest.mark.parametrize('private', [False, True])
def test_print_layout_failure_explains_repair_without_cell_values(
    tmp_path: Path, private: bool
) -> None:
    tools = WorkbooksToolSet(tmp_path)
    workbook = tools.create_workbook('print.xlsx')
    tools.put_sheet(
        workbook,
        'sheet',
        'Sheet',
        {'anchor': 'end'},
        print_settings={
            'mode': 'fit_width',
            'orientation': 'portrait',
            'minimum_scale_percent': 100,
        },
    )
    content = tools.compose_artifact(
        workbook,
        'data',
        {
            'kind': 'matrix',
            'values': [['SECRET-WORKBOOK-VALUE', 'Amount'], ['A', 2]],
        },
    )
    tools.put_range(
        workbook,
        'data',
        'sheet',
        'A1',
        content,
        {
            'chart': {'type': 'line', 'title': 'Test', 'anchor': 'F2'},
        },
    )
    agent = Agent(name='Print feedback', api_key='test-key')
    agent.add_toolset(tools)
    runtime = LocalToolRuntime(
        agent.compile_tools(), private_data={'x': 'SECRET-WORKBOOK-VALUE'} if private else None
    )
    event = StreamEvent(
        position=1,
        event_type='system_tool_start',
        data={
            'payload': {
                'tool_call': {
                    'call_id': 'render',
                    'spec_ref': {
                        'tool_id': 'WORKBOOKS_render_workbook',
                        'namespace': 'sdk',
                        'version': 'v1',
                    },
                    'arguments': {'workbook': workbook},
                    'lineage': {'session_id': 'ses-print', 'invocation_id': 'inv-print'},
                }
            }
        },
    )
    outcome = asyncio.run(runtime.outcome_for_event(event))
    assert outcome is not None and outcome.status == 'error'
    assert outcome.error.code == 'sdk_tool_validation_error'
    assert 'workbook_print_requires_landscape_or_actual_size' in outcome.error.message
    assert outcome.error.retryable is True
    assert 'SECRET-WORKBOOK-VALUE' not in outcome.model_dump_json()
    tools.put_sheet(
        workbook, 'sheet', 'Sheet', {'anchor': 'end'}, print_settings={'mode': 'actual_size'}
    )
    assert tools.render_workbook(workbook).size_bytes > 0
