# pyright: reportPrivateUsage=false
"""Private source readback stays local while the model can reuse opaque selectors."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from pathlib import Path
from types import MethodType
from typing import Any, cast

import httpx
import pytest
from maivn import Agent
from maivn._internal.client import _stream_with_local_tools
from maivn._internal.models import StreamEvent
from maivn._internal.tool_runtime import LocalToolRuntime
from maivn._internal.transport.http import HttpJsonClient
from maivn.artifact_images import ResolvedArtifactImage

import maivn_tools
from tests.artifacts.test_image_composition import image_content
from tests.artifacts.test_revision_sources import _private_receipt


def _event(name: str, arguments: dict[str, object], call_id: str) -> StreamEvent:
    return StreamEvent(
        position=1,
        event_type='system_tool_start',
        data={
            'payload': {
                'tool_call': {
                    'call_id': call_id,
                    'spec_ref': {'tool_id': name, 'namespace': 'sdk', 'version': 'v1'},
                    'arguments': arguments,
                    'lineage': {'session_id': 'ses-private', 'invocation_id': 'inv-private'},
                }
            }
        },
    )


@pytest.mark.parametrize('kind', ['documents', 'pdf', 'presentations', 'workbooks'])
def test_fresh_private_source_outcome_hides_cells_and_filename_but_remains_editable(
    tmp_path: Path,
    kind: str,
) -> None:
    factory, extension, noun, argument = {
        'documents': (maivn_tools.DocumentsToolSet, 'docx', 'document', 'doc'),
        'pdf': (maivn_tools.PDFToolSet, 'pdf', 'document', 'doc'),
        'presentations': (maivn_tools.PresentationsToolSet, 'pptx', 'presentation', 'presentation'),
        'workbooks': (maivn_tools.WorkbooksToolSet, 'xlsx', 'workbook', 'workbook'),
    }[kind]
    secret = 'synthetic-private@example.com'
    filename = f'confidential-payroll-details.{extension}'
    original = cast('Any', factory(tmp_path / 'original'))
    handle = getattr(original, f'create_{noun}')(filename)
    content = (
        {'kind': 'matrix', 'values': [[secret, 73492.25]]}
        if kind == 'workbooks'
        else {'kind': 'table', 'rows': [[secret, 'Confidential budget']]}
    )
    private_id = 'af14b845-3a6b-4d7f-8ead-08f81d6cc045'
    composition = original.compose_artifact(handle, private_id, content)
    if kind == 'presentations':
        original.put_slide(handle, 'slide', {'anchor': 'end'})
        original.put_element(
            handle,
            'slide',
            'table',
            {'type': 'table', 'composition': composition, 'x': 1, 'y': 1, 'width': 8, 'height': 4},
        )
    elif kind == 'workbooks':
        original.put_sheet(handle, 'sheet', 'Private payroll', {'anchor': 'end'})
        original.put_range(handle, 'table', 'sheet', 'A1', composition, {})
    else:
        original.put_block(
            handle, 'table', {'type': 'table', 'composition': composition}, {'anchor': 'end'}
        )
    generated = getattr(original, f'render_{noun}')(handle)
    source = original.export_generated_file_source(generated)
    fresh = cast('Any', factory(tmp_path / 'fresh'))
    restored = fresh.resume_private_artifact(_private_receipt(generated), source=source)
    assert filename not in json.dumps(restored)
    rerendered = getattr(fresh, f'render_{noun}')(restored)
    assert rerendered.filename == filename
    assert rerendered.custody == 'vault_private'
    agent = Agent(name='Fresh private source', api_key='test-key')
    agent.add_toolset(fresh)
    runtime = LocalToolRuntime(agent.compile_tools(), private_data=None)
    posted: list[dict[str, Any]] = []

    def receive(request: httpx.Request) -> httpx.Response:
        posted.append(json.loads(request.content))
        return httpx.Response(200, json={})

    async def run() -> None:
        async def events() -> AsyncIterator[StreamEvent]:
            yield _event(f'{kind.upper()}_read_{noun}', {argument: restored}, 'read-call')

        http = HttpJsonClient(
            base_url='https://testserver',
            api_key='key',
            timeout_seconds=1,
            transport=httpx.MockTransport(receive),
        )
        async for _ in _stream_with_local_tools(
            events=events(), tool_runtime=runtime, tool_http=http, session_id='ses-private'
        ):
            pass
        wire = json.dumps(posted)
        assert secret not in wire and filename not in wire and '73492.25' not in wire
        assert private_id not in wire
        state = posted[0]['outcomes'][0]['result']
        assert '{_{user_sdk_source_' in wire
        private_handle = state[noun]
        entry = state['compositions'][0]
        changed = await runtime.outcome_for_event(
            _event(
                f'{kind.upper()}_compose_artifact',
                {
                    argument: private_handle,
                    'composition_id': entry['composition_id'],
                    'content': entry['content'],
                },
                'reuse-call',
            )
        )
        assert changed is not None and changed.status == 'ok'
        actual = getattr(fresh, f'read_{noun}')(restored)
        assert actual['compositions'][0]['content'] == content
        other_handle = getattr(fresh, f'create_{noun}')(f'other.{extension}')
        foreign_workspace = await runtime.outcome_for_event(
            _event(
                f'{kind.upper()}_compose_artifact',
                {argument: other_handle, 'composition_id': 'copied', 'content': entry['content']},
                'foreign-workspace-call',
            )
        )
        assert foreign_workspace is not None and foreign_workspace.status == 'error'
        other_runtime = LocalToolRuntime(agent.compile_tools(), private_data=None)
        refused = await other_runtime.outcome_for_event(
            _event(f'{kind.upper()}_read_{noun}', {argument: private_handle}, 'foreign-call')
        )
        assert refused is not None and refused.status == 'error'
        assert secret not in refused.model_dump_json()
        for forged in ('{_{user_sdk_source_not-a-uuid}_}', 'prefix {_{user_sdk_source_}_}'):
            rejected = await runtime.outcome_for_event(
                _event(
                    f'{kind.upper()}_compose_artifact',
                    {
                        argument: restored,
                        'composition_id': 'forged',
                        'content': (
                            {'kind': 'scalar', 'value': forged}
                            if kind == 'workbooks'
                            else {'kind': 'text', 'text': forged}
                        ),
                    },
                    'malformed-source-token',
                )
            )
            assert rejected is not None and rejected.status == 'error'
            assert forged not in rejected.model_dump_json()

    asyncio.run(run())


@pytest.mark.parametrize('fail_read', [False, True])
def test_private_image_promotion_before_queued_read_never_exposes_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_read: bool,
) -> None:

    tools = maivn_tools.DocumentsToolSet(tmp_path)
    handle = tools.create_document('private-invoice.docx')
    tools.compose_artifact(
        handle, 'body', {'kind': 'text', 'text': 'synthetic-private@example.com'}
    )
    generated = tools.render_document(handle)
    reference = _private_receipt(generated).model_copy(
        update={'kind': 'image', 'mime_type': 'image/png'}
    )
    raw = base64.b64decode(cast('dict[str, str]', image_content()['image'])['content_base64'])

    async def scenario() -> None:
        started, release = asyncio.Event(), asyncio.Event()

        async def resolve(artifact_id: str) -> ResolvedArtifactImage:
            assert artifact_id == reference.artifact_id
            started.set()
            await release.wait()
            return ResolvedArtifactImage(raw, reference, 'image/png', private=True)

        monkeypatch.setattr(
            'maivn_tools.connectors.documents.toolset.resolve_artifact_image', resolve
        )
        if fail_read:

            def read(self: object, doc: object) -> object:
                message = 'synthetic-private@example.com'
                raise ValueError(message)

            monkeypatch.setattr(tools, 'read_document', MethodType(read, tools))
        agent = Agent(name='promotion', api_key='test-key')
        agent.add_toolset(tools)
        if fail_read:
            agent.add_tool(tools.read_document, name='READ', metadata={'serialize_calls': True})
        runtime = LocalToolRuntime(agent.compile_tools(), private_data=None)
        first = asyncio.create_task(
            runtime.outcome_for_event(
                _event(
                    'DOCUMENTS_compose_artifact_image',
                    {
                        'doc': handle,
                        'composition_id': 'image',
                        'artifact_id': reference.artifact_id,
                        'alt_text': 'Private image',
                    },
                    'compose',
                )
            )
        )
        await asyncio.wait_for(started.wait(), 2)
        second = asyncio.create_task(
            runtime.outcome_for_event(
                _event('READ' if fail_read else 'DOCUMENTS_read_document', {'doc': handle}, 'read')
            )
        )
        await asyncio.sleep(0)
        release.set()
        outcomes = await asyncio.gather(first, second)
        assert outcomes[0] is not None and outcomes[0].status == 'ok'
        assert outcomes[1] is not None
        assert 'synthetic-private@example.com' not in outcomes[1].model_dump_json()
        assert 'private-invoice.docx' not in outcomes[1].model_dump_json()

    asyncio.run(scenario())


@pytest.mark.parametrize('private', [False, True])
def test_private_missing_composition_has_actionable_value_free_feedback(
    tmp_path: Path, *, private: bool
) -> None:
    tools = maivn_tools.PresentationsToolSet(tmp_path / 'first')
    handle = tools.create_presentation('private-payroll.pptx')
    tools.put_slide(handle, 'slide', {'anchor': 'end'})
    generated = tools.render_presentation(handle)
    fresh = maivn_tools.PresentationsToolSet(tmp_path / 'fresh')
    if private:
        restored = fresh.resume_private_artifact(
            _private_receipt(generated), source=tools.export_generated_file_source(generated)
        )
    else:
        fresh = tools
        restored = handle
    agent = Agent(name='Private composition repair', api_key='test-key')
    agent.add_toolset(fresh)
    runtime = LocalToolRuntime(agent.compile_tools(), private_data=None)
    outcome = asyncio.run(
        runtime.outcome_for_event(
            _event(
                'PRESENTATIONS_put_element',
                {
                    'presentation': restored,
                    'slide_id': 'slide',
                    'element_id': 'body',
                    'element': {
                        'type': 'text',
                        'composition': {
                            'presentation_id': restored['presentation_id'],
                            'composition_id': 'synthetic-private@example.com',
                        },
                        'x': 1,
                        'y': 1,
                        'width': 8,
                        'height': 4,
                    },
                },
                'missing-composition',
            )
        )
    )
    assert outcome is not None and outcome.status == 'error'
    if not private:
        assert outcome.error.code == 'sdk_composition_reference_error'
        assert 'compose_artifact' in outcome.error.message
        assert 'synthetic-private@example.com' in outcome.error.message
        return
    assert outcome.error.code == 'sdk_composition_reference_error'
    assert 'compose_artifact' in outcome.error.message
    assert 'synthetic-private@example.com' not in outcome.model_dump_json()
    assert 'private-payroll.pptx' not in outcome.model_dump_json()


def test_private_workbook_overlap_returns_value_free_recovery_guidance(tmp_path: Path) -> None:
    tools = maivn_tools.WorkbooksToolSet(tmp_path / 'first')
    handle = tools.create_workbook('private-budget.xlsx')
    composition = tools.compose_artifact(handle, 'value', {'kind': 'scalar', 'value': 3})
    tools.put_sheet(handle, 'sheet', 'Sheet', {'anchor': 'end'})
    tools.put_range(handle, 'private-existing-range', 'sheet', 'A1', composition, {})
    generated = tools.render_workbook(handle)
    fresh = maivn_tools.WorkbooksToolSet(tmp_path / 'fresh')
    restored = fresh.resume_private_artifact(
        _private_receipt(generated), source=tools.export_generated_file_source(generated)
    )
    reference = {'workbook_id': restored['workbook_id'], 'composition_id': 'value'}
    agent = Agent(name='Private range repair', api_key='test-key')
    agent.add_toolset(fresh)
    runtime = LocalToolRuntime(agent.compile_tools(), private_data=None)
    outcome = asyncio.run(
        runtime.outcome_for_event(
            _event(
                'WORKBOOKS_put_range',
                {
                    'workbook': restored,
                    'range_id': 'new-range',
                    'sheet_id': 'sheet',
                    'start_cell': 'A1',
                    'composition': reference,
                    'format': {},
                },
                'overlap',
            )
        )
    )
    assert outcome is not None and outcome.status == 'error'
    assert outcome.error.code == 'sdk_workbook_range_overlap'
    assert 'range_id' in outcome.error.message and 'start_cell' in outcome.error.message
    assert 'private-existing-range' not in outcome.model_dump_json()
    assert 'private-budget.xlsx' not in outcome.model_dump_json()
