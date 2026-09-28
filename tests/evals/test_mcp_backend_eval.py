# pyright: strict
from __future__ import annotations

import asyncio

from evals.mcp_backend_eval import run_mcp_backend_eval


def test_mcp_backend_eval_dispatches_contract_tool_call() -> None:
    result = asyncio.run(run_mcp_backend_eval())

    assert result.registration.backend.kind == 'mcp'
    assert result.tool_call.call_id == 'call-1'
    assert result.outcome_result == {
        'server': 'github',
        'tool': 'GITHUB_list_issues',
        'arguments': {'repo': 'maivn-platform'},
    }
