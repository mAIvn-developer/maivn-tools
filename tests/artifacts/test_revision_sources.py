from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any, cast

import pytest
from maivn_contracts.artifacts import GeneratedFile, OrdinaryArtifactRef, PrivateArtifactRef

import maivn_tools


def _receipt(generated: GeneratedFile, *, revision: int = 1) -> OrdinaryArtifactRef:
    preview = {
        'document': {'kind': 'document', 'page_count': 1},
        'image': {'kind': 'image', 'width_pixels': 256, 'height_pixels': 256},
        'presentation': {'kind': 'presentation', 'slide_count': 1},
        'spreadsheet': {'kind': 'spreadsheet', 'sheet_count': 1},
    }[generated.artifact_kind]
    return OrdinaryArtifactRef.model_validate(
        {
            'artifact_id': f'artifact_{revision}',
            'logical_output_id': 'report',
            'revision': revision,
            'kind': generated.artifact_kind,
            'mime_type': generated.mime_type,
            'created_at': '2026-09-05T12:00:00Z',
            'effective_retention': {
                'policy_snapshot_id': 'policy',
                'retention_class': 'artifact_30d',
                'expires_at': '2026-10-05T12:00:00Z',
            },
            'custody': 'ordinary',
            'state': 'available',
            'display_filename': generated.filename,
            'size_bytes': generated.size_bytes,
            'sha256': generated.sha256,
            'producer': {
                'producer_class': 'external_tool',
                'producer_id': 'sdk_local_tool',
                'root_invocation_id': f'root_{revision}',
                'session_id': f'session_{revision}',
                'call_id': f'call_{revision}',
            },
            'validation_receipt': {
                'receipt_id': f'receipt_{revision}',
                'status': 'validated',
                'validator_profile': f'tool_file_{generated.artifact_kind}',
                'validator_version': '1',
            },
            'safe_preview': preview,
            'retrieval_action': {'relation': 'artifact.download_authorization'},
            'supersedes_artifact_id': f'artifact_{revision - 1}' if revision > 1 else None,
        }
    )


@pytest.mark.parametrize('kind', ['documents', 'pdf', 'presentations', 'workbooks'])
def test_exact_published_source_survives_fresh_toolset_and_later_edits(
    tmp_path: Path,
    kind: str,
) -> None:
    factory, extension, noun = {
        'documents': (maivn_tools.DocumentsToolSet, 'docx', 'document'),
        'pdf': (maivn_tools.PDFToolSet, 'pdf', 'document'),
        'presentations': (maivn_tools.PresentationsToolSet, 'pptx', 'presentation'),
        'workbooks': (maivn_tools.WorkbooksToolSet, 'xlsx', 'workbook'),
    }[kind]
    tools = cast('Any', factory(tmp_path))
    handle = getattr(tools, f'create_{noun}')(f'report.{extension}')
    if kind == 'presentations':
        tools.put_slide(handle, 'slide', {'anchor': 'end'})
    elif kind == 'workbooks':
        tools.put_sheet(handle, 'sheet', 'Summary', {'anchor': 'end'})
        content = tools.compose_artifact(handle, 'initial', {'kind': 'scalar', 'value': 'Initial'})
        tools.put_range(handle, 'initial', 'sheet', 'A1', content, {})
    first = cast('GeneratedFile', getattr(tools, f'render_{noun}')(handle))
    original = Path(first.path).read_bytes()
    receipt = _receipt(first)
    tools.bind_generated_file_receipt(first, receipt)
    tools.bind_generated_file_receipt(first, receipt)  # Exact intake retry.
    archive = tools.export_generated_file_source(first)
    restarted = cast('Any', factory(tmp_path / 'new-host'))
    resumed = restarted.resume_artifact(receipt, source=archive)
    assert resumed != handle
    if kind == 'workbooks':
        restarted.put_sheet(resumed, 'second', 'Second', {'anchor': 'end'})
    elif kind == 'presentations':
        restarted.put_slide(resumed, 'second', {'anchor': 'end'})
    else:
        composition = restarted.compose_artifact(
            resumed, 'body', {'kind': 'text', 'text': 'Revised'}
        )
        restarted.put_block(
            resumed, 'body', {'type': 'paragraph', 'composition': composition}, {'anchor': 'end'}
        )
    second = cast('GeneratedFile', getattr(restarted, f'render_{noun}')(resumed, overwrite=True))
    assert second.expected_base == receipt
    assert Path(second.path).read_bytes() != original
    restarted.bind_generated_file_receipt(second, _receipt(second, revision=2))
    old_source = restarted.resume_artifact(receipt)
    old_render = cast(
        'GeneratedFile', getattr(restarted, f'render_{noun}')(old_source, overwrite=True)
    )
    assert old_render.expected_base == receipt
    assert Path(old_render.path).read_bytes() == original
    with pytest.raises(ValueError, match='source'):
        restarted.resume_artifact(receipt.model_copy(update={'sha256': '0' * 64}))


def _private_receipt(generated: GeneratedFile, revision: int = 1) -> PrivateArtifactRef:
    ordinary = _receipt(generated, revision=revision).model_dump(mode='json')
    return PrivateArtifactRef.model_validate(
        {
            **{
                key: ordinary[key]
                for key in (
                    'artifact_id',
                    'logical_output_id',
                    'revision',
                    'kind',
                    'mime_type',
                    'created_at',
                    'effective_retention',
                    'supersedes_artifact_id',
                )
            },
            'custody': 'vault_private',
            'state': 'available_in_vault',
            'display_label': {
                'document': 'Private document',
                'image': 'Private image',
                'presentation': 'Private presentation',
                'spreadsheet': 'Private spreadsheet',
            }[generated.artifact_kind],
            'creation_receipt_id': f'vault-receipt-{revision}',
            'producer': {
                'producer_class': 'vault',
                'producer_id': 'vault',
                'root_invocation_id': f'root_{revision}',
            },
            'retrieval_action': {'relation': 'artifact.vault_download_authorization'},
        }
    )


@pytest.mark.parametrize('kind', ['documents', 'pdf', 'presentations', 'workbooks'])
def test_private_source_restores_on_fresh_host_with_exact_private_base(
    tmp_path: Path, kind: str
) -> None:
    factory, extension, noun = {
        'documents': (maivn_tools.DocumentsToolSet, 'docx', 'document'),
        'pdf': (maivn_tools.PDFToolSet, 'pdf', 'document'),
        'presentations': (maivn_tools.PresentationsToolSet, 'pptx', 'presentation'),
        'workbooks': (maivn_tools.WorkbooksToolSet, 'xlsx', 'workbook'),
    }[kind]
    tools = cast('Any', factory(tmp_path / 'original-host'))
    handle = getattr(tools, f'create_{noun}')(f'report.{extension}')
    if kind == 'presentations':
        tools.put_slide(handle, 'slide', {'anchor': 'end'})
    elif kind == 'workbooks':
        tools.put_sheet(handle, 'sheet', 'Summary', {'anchor': 'end'})
        content = tools.compose_artifact(handle, 'initial', {'kind': 'scalar', 'value': 'Initial'})
        tools.put_range(handle, 'initial', 'sheet', 'A1', content, {})
    first = cast('GeneratedFile', getattr(tools, f'render_{noun}')(handle))
    ref = _private_receipt(first)
    tools.bind_private_generated_file_receipt(first, ref)
    source = tools.export_generated_file_source(first)
    fresh = cast('Any', factory(tmp_path / 'fresh-host'))
    restored = fresh.resume_private_artifact(ref, source=source)
    second = cast('GeneratedFile', getattr(fresh, f'render_{noun}')(restored))
    assert second.expected_base is None
    assert second.private_expected_base == ref
    assert Path(second.path).read_bytes() == Path(first.path).read_bytes()
    with pytest.raises(ValueError, match='receipt'):
        fresh.bind_private_generated_file_receipt(second, _private_receipt(second, revision=3))
    second_ref = _private_receipt(second, revision=2)
    fresh.bind_private_generated_file_receipt(second, second_ref)
    fresh.bind_private_generated_file_receipt(second, second_ref)
    third = cast('GeneratedFile', getattr(fresh, f'render_{noun}')(restored, overwrite=True))
    assert third.private_expected_base == second_ref
    third_ref = _private_receipt(third, revision=3)
    fresh.bind_private_generated_file_receipt(third, third_ref)
    fresh.bind_private_generated_file_receipt(second, second_ref)
    after_retry = cast('GeneratedFile', getattr(fresh, f'render_{noun}')(restored, overwrite=True))
    assert after_retry.private_expected_base == third_ref
    old = fresh.resume_private_artifact(ref, source=source)
    old_render = cast('GeneratedFile', getattr(fresh, f'render_{noun}')(old, overwrite=True))
    assert old_render.private_expected_base == ref


def test_later_same_filename_render_cannot_replace_bytes_waiting_for_intake(tmp_path: Path) -> None:
    tools = maivn_tools.DocumentsToolSet(tmp_path)
    handle = tools.create_document('report.docx')
    first = tools.render_document(handle)
    waiting, resume = Event(), Event()

    def slow_intake() -> tuple[bytes, bytes]:
        waiting.set()
        assert resume.wait(timeout=5)
        return Path(first.path).read_bytes(), tools.export_generated_file_source(first)

    with ThreadPoolExecutor(max_workers=1) as executor:
        upload = executor.submit(slow_intake)
        assert waiting.wait(timeout=5)
        composition = tools.compose_artifact(
            handle, 'body', {'kind': 'text', 'text': 'Later revision'}
        )
        tools.put_block(
            handle, 'body', {'type': 'paragraph', 'composition': composition}, {'anchor': 'end'}
        )
        second = tools.render_document(handle, overwrite=True)
        resume.set()
        first_bytes, first_source = upload.result(timeout=5)
    assert first.path != second.path
    assert hashlib.sha256(first_bytes).hexdigest() == first.sha256
    assert json.loads(first_source)['output_sha256'] == first.sha256
    assert first_bytes != Path(second.path).read_bytes()


def test_private_revision_can_skip_failed_drafts_but_keeps_exact_predecessor(
    tmp_path: Path,
) -> None:
    tools = maivn_tools.DocumentsToolSet(tmp_path)
    handle = tools.create_document('report.docx')
    first = tools.render_document(handle)
    base = _private_receipt(first)
    tools.bind_private_generated_file_receipt(first, base)
    second = tools.render_document(handle, overwrite=True)
    skipped = _private_receipt(second, revision=3).model_copy(
        update={'supersedes_artifact_id': base.artifact_id}
    )
    tools.bind_private_generated_file_receipt(second, skipped)
    after = tools.render_document(handle, overwrite=True)
    assert after.private_expected_base == skipped
