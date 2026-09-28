"""Behavioral tests for the persisted artifact workspace."""

# pyright: strict

from __future__ import annotations

from pathlib import Path

import pytest

import maivn_tools
from maivn_tools.connectors.artifacts import workspace as workspace_module
from maivn_tools.connectors.artifacts.workspace import ManifestWorkspace


def _workspace(tmp_path: Path) -> ManifestWorkspace:
    return ManifestWorkspace(
        tmp_path,
        workspace_name='test-artifacts',
        id_field='artifact_id',
        extension='.bin',
    )


def test_artifact_toolsets_publish_only_their_configured_output_root(tmp_path: Path) -> None:
    documents_root = tmp_path / 'documents'
    pdf_root = tmp_path / 'pdf'
    workbooks_root = tmp_path / 'workbooks'
    presentations_root = tmp_path / 'presentations'

    assert maivn_tools.DocumentsToolSet(documents_root).authorized_generated_file_roots() == (
        documents_root.resolve(),
    )
    assert maivn_tools.PDFToolSet(pdf_root).authorized_generated_file_roots() == (
        pdf_root.resolve(),
    )
    assert maivn_tools.WorkbooksToolSet(workbooks_root).authorized_generated_file_roots() == (
        workbooks_root.resolve(),
    )
    assert maivn_tools.PresentationsToolSet(
        presentations_root
    ).authorized_generated_file_roots() == (presentations_root.resolve(),)


def test_manifest_workspace_refuses_use_after_crossing_a_process_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    handle = workspace.create('proof.bin', {'blocks': []})
    owner_pid = workspace_module.os.getpid()
    monkeypatch.setattr(workspace_module.os, 'getpid', lambda: owner_pid + 1)

    with pytest.raises(RuntimeError, match='single-process-per-workspace'):
        workspace.load(handle)


def test_manifest_write_retries_transient_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    original_replace = Path.replace
    attempts = 0

    def transient_replace(source: Path, target: Path) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            message = 'simulated Windows file lock'
            raise PermissionError(message)
        return original_replace(source, target)

    monkeypatch.setattr(Path, 'replace', transient_replace)

    handle = workspace.create('proof.bin', {'blocks': []})

    assert attempts == 2
    assert workspace.load(handle)['blocks'] == []
    assert list(workspace.workspace_dir.glob('*.tmp')) == []


def test_manifest_write_cleans_temporary_file_after_persistent_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)

    def locked_replace(_source: Path, _target: Path) -> Path:
        message = 'simulated persistent Windows file lock'
        raise PermissionError(message)

    monkeypatch.setattr(Path, 'replace', locked_replace)

    with pytest.raises(PermissionError, match='persistent Windows file lock'):
        workspace.create('proof.bin', {'blocks': []})

    assert list(workspace.workspace_dir.glob('*.tmp')) == []
