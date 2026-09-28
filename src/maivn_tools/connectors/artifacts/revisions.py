"""Exact ordinary receipts bound to immutable, locally persisted composition sources."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Literal, cast

from maivn_contracts.artifacts import GeneratedFile, OrdinaryArtifactRef, PrivateArtifactRef

from .workspace import process_lock_for

_TOKEN = re.compile(r'[0-9a-f]{64}')
_MAX_SOURCE_BYTES = 52_428_800


def _encoded(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def _write(path: Path, value: object) -> None:
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        temporary.write_bytes(_encoded(value))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def expected_base(manifest: dict[str, object]) -> OrdinaryArtifactRef | None:
    value = manifest.get('published_artifact')
    return OrdinaryArtifactRef.model_validate(value) if value is not None else None


def snapshot_source(workspace_dir: Path, manifest: dict[str, object], raw: bytes) -> str:
    """Freeze the exact source used to render these bytes before returning a file."""
    snapshot = {'manifest': manifest, 'sha256': hashlib.sha256(raw).hexdigest()}
    content = _encoded(snapshot)
    token = hashlib.sha256(content).hexdigest()
    directory = workspace_dir / 'sources'
    directory.mkdir(exist_ok=True)
    path = directory / f'{token}.json'
    if not path.exists():
        _write(path, snapshot)
    return token


def _read_snapshot(workspace_dir: Path, token: object) -> dict[str, object]:
    if not isinstance(token, str) or _TOKEN.fullmatch(token) is None:
        raise ValueError('invalid source snapshot')
    content = (workspace_dir / 'sources' / f'{token}.json').read_bytes()
    if hashlib.sha256(content).hexdigest() != token:
        raise ValueError('source snapshot integrity mismatch')
    return cast('dict[str, object]', json.loads(content))


def export_source(workspace_dir: Path, workspace_type: str, generated: GeneratedFile) -> bytes:
    """Export portable editable sources through the SDK custody boundary."""
    token = generated.workspace.get('source_revision') if generated.workspace else None
    snapshot = _read_snapshot(workspace_dir, token)
    if snapshot['sha256'] != generated.sha256:
        raise ValueError('source does not match the generated output')
    package = _encoded(
        {
            'format': 'maivn-source-archive-v1',
            'workspace_type': workspace_type,
            'manifest': snapshot['manifest'],
            'output_sha256': generated.sha256,
        }
    )
    if len(package) > _MAX_SOURCE_BYTES:
        raise ValueError('source archive exceeds the custody limit')
    return package


def import_source(
    workspace_dir: Path, workspace_type: str, artifact: OrdinaryArtifactRef, source: bytes
) -> None:
    """Cache an exact authorized package; filenames never select a source."""
    if not source or len(source) > _MAX_SOURCE_BYTES:
        raise ValueError('invalid source archive size')
    package = cast('dict[str, object]', json.loads(source))
    manifest = package.get('manifest')
    if (
        set(package) != {'format', 'workspace_type', 'manifest', 'output_sha256'}
        or package['format'] != 'maivn-source-archive-v1'
        or package['workspace_type'] != workspace_type
        or package['output_sha256'] != artifact.sha256
        or not isinstance(manifest, dict)
        or cast('dict[str, object]', manifest).get('filename') != artifact.display_filename
    ):
        raise ValueError('source does not match the selected artifact')
    snapshot = {'manifest': cast('dict[str, object]', manifest), 'sha256': artifact.sha256}
    token = hashlib.sha256(_encoded(snapshot)).hexdigest()
    directory = workspace_dir / 'sources'
    directory.mkdir(exist_ok=True)
    with process_lock_for(workspace_dir):
        _write(directory / f'{token}.json', snapshot)
        artifact_key = hashlib.sha256(artifact.artifact_id.encode()).hexdigest()
        _write(
            directory / f'receipt-{artifact_key}.json',
            {
                'artifact': artifact.model_dump(mode='json'),
                'source_revision': token,
            },
        )


def bind_receipt(
    workspace_dir: Path,
    id_field: str,
    generated: GeneratedFile,
    artifact: OrdinaryArtifactRef,
) -> None:
    """Record a verified intake receipt without making the local workspace an authority."""
    with process_lock_for(workspace_dir):
        token = generated.workspace.get('source_revision') if generated.workspace else None
        snapshot = _read_snapshot(workspace_dir, token)
        manifest = cast('dict[str, object]', snapshot['manifest'])
        if (
            snapshot['sha256'] != generated.sha256
            or artifact.sha256 != generated.sha256
            or artifact.size_bytes != generated.size_bytes
            or artifact.mime_type != generated.mime_type
            or artifact.kind != generated.artifact_kind
            or artifact.display_filename != generated.filename
            or manifest.get('filename') != generated.filename
            or expected_base(manifest) != generated.expected_base
        ):
            raise ValueError('source receipt mismatch')
        artifact_key = hashlib.sha256(artifact.artifact_id.encode()).hexdigest()
        receipt_path = workspace_dir / 'sources' / f'receipt-{artifact_key}.json'
        binding = {'artifact': artifact.model_dump(mode='json'), 'source_revision': token}
        if receipt_path.exists() and json.loads(receipt_path.read_bytes()) != binding:
            raise ValueError('source receipt conflict')
        _write(receipt_path, binding)
        source_id = manifest.get(id_field)
        if not isinstance(source_id, str) or re.fullmatch(r'[0-9a-f]{32}', source_id) is None:
            raise ValueError('invalid source handle')
        current_path = workspace_dir / f'{source_id}.json'
        current = cast('dict[str, object]', json.loads(current_path.read_bytes()))
        current_base = expected_base(current)
        if current_base == artifact or (
            current_base is not None
            and current_base.logical_output_id == artifact.logical_output_id
            and current_base.revision > artifact.revision
        ):
            # A delayed exact receipt must never rewind the current workspace base.
            return
        if current_base != generated.expected_base:
            raise ValueError('source receipt cannot replace a later revision')
        current['published_artifact'] = artifact.model_dump(mode='json')
        _write(current_path, current)


def resume_source(
    workspace_dir: Path, id_field: str, artifact: OrdinaryArtifactRef
) -> dict[str, str]:
    """Clone the exact published source; the server authorizes any subsequent revision."""
    with process_lock_for(workspace_dir):
        artifact_key = hashlib.sha256(artifact.artifact_id.encode()).hexdigest()
        try:
            binding = cast(
                'dict[str, object]',
                json.loads(
                    (workspace_dir / 'sources' / f'receipt-{artifact_key}.json').read_bytes()
                ),
            )
            if OrdinaryArtifactRef.model_validate(binding['artifact']) != artifact:
                raise ValueError('source does not match the selected artifact')
            snapshot = _read_snapshot(workspace_dir, binding['source_revision'])
        except OSError:
            raise ValueError('published source is unavailable in this workspace') from None
        manifest = cast('dict[str, object]', snapshot['manifest'])
        if snapshot['sha256'] != artifact.sha256:
            raise ValueError('source does not match the selected artifact')
        source_id = uuid.uuid4().hex
        _rebind_compositions(manifest, id_field, source_id)
        manifest[id_field] = source_id
        manifest['published_artifact'] = artifact.model_dump(mode='json')
        _write(workspace_dir / f'{source_id}.json', manifest)
        return {id_field: source_id, 'filename': str(manifest['filename'])}


def _rebind_compositions(value: object, id_field: str, source_id: str) -> None:
    if isinstance(value, dict):
        mapping = cast('dict[str, object]', value)
        if id_field in mapping and 'composition_id' in mapping:
            mapping[id_field] = source_id
        for child in mapping.values():
            _rebind_compositions(child, id_field, source_id)
    elif isinstance(value, list):
        for child in cast('list[object]', value):
            _rebind_compositions(child, id_field, source_id)


def expected_private_base(manifest: dict[str, object]) -> PrivateArtifactRef | None:
    value = manifest.get('published_private_artifact')
    return PrivateArtifactRef.model_validate(value) if value is not None else None


def immutable_render_path(workspace_dir: Path, token: str, filename: str, raw: bytes) -> Path:
    """Retain exact render bytes while another call updates the user-facing filename."""
    directory = workspace_dir / 'renders' / token
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('render snapshot integrity mismatch')
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return path


def bind_private_receipt(
    workspace_dir: Path, id_field: str, generated: GeneratedFile, artifact: PrivateArtifactRef
) -> None:
    """Bind the exact SDK-verified private receipt to its immutable local source."""
    with process_lock_for(workspace_dir):
        token = generated.workspace.get('source_revision') if generated.workspace else None
        snapshot = _read_snapshot(workspace_dir, token)
        manifest = cast('dict[str, object]', snapshot['manifest'])
        base = generated.private_expected_base
        if (
            snapshot['sha256'] != generated.sha256
            or generated.expected_base is not None
            or artifact.kind != generated.artifact_kind
            or artifact.mime_type != generated.mime_type
            or expected_private_base(manifest) != base
            or (
                base is not None
                and (
                    artifact.logical_output_id != base.logical_output_id
                    or artifact.revision <= base.revision
                    or artifact.supersedes_artifact_id != base.artifact_id
                )
            )
            or (
                base is None
                and (artifact.revision != 1 or artifact.supersedes_artifact_id is not None)
            )
        ):
            raise ValueError('private source receipt mismatch')
        source_id = manifest.get(id_field)
        if not isinstance(source_id, str) or re.fullmatch(r'[0-9a-f]{32}', source_id) is None:
            raise ValueError('invalid source handle')
        current_path = workspace_dir / f'{source_id}.json'
        current = cast('dict[str, object]', json.loads(current_path.read_bytes()))
        current_base = expected_private_base(current)
        if current_base == artifact or (
            current_base is not None
            and current_base.logical_output_id == artifact.logical_output_id
            and current_base.revision > artifact.revision
        ):
            # A delayed exact receipt must never rewind the current workspace base.
            return
        if current_base != base:
            raise ValueError('private source receipt cannot replace a later revision')
        current['published_private_artifact'] = artifact.model_dump(mode='json')
        _write(current_path, current)


def resume_private_source(
    workspace_dir: Path,
    workspace_type: str,
    id_field: str,
    artifact: PrivateArtifactRef,
    source: bytes,
) -> dict[str, str]:
    """Restore bytes obtained by exact-ref Vault source retrieval into a fresh workspace.

    The caller supplies the authenticated source response; this local parser grants
    no server authority. The next publication carries the exact private base for CAS.
    """
    if not source or len(source) > _MAX_SOURCE_BYTES:
        raise ValueError('invalid source archive size')
    package = cast('dict[str, object]', json.loads(source))
    manifest = package.get('manifest')
    digest = package.get('output_sha256')
    if (
        set(package) != {'format', 'workspace_type', 'manifest', 'output_sha256'}
        or package['format'] != 'maivn-source-archive-v1'
        or package['workspace_type'] != workspace_type
        or not isinstance(digest, str)
        or _TOKEN.fullmatch(digest) is None
        or not isinstance(manifest, dict)
    ):
        raise ValueError('invalid private source archive')
    manifest = cast('dict[str, object]', manifest)
    with process_lock_for(workspace_dir):
        source_id = uuid.uuid4().hex
        _rebind_compositions(manifest, id_field, source_id)
        manifest[id_field] = source_id
        manifest.pop('published_artifact', None)
        manifest['published_private_artifact'] = artifact.model_dump(mode='json')
        safe_filename = f'private-{source_id}{Path(str(manifest["filename"])).suffix}'
        manifest['private_handle_filename'] = safe_filename
        _write(workspace_dir / f'{source_id}.json', manifest)
        return {id_field: source_id, 'filename': safe_filename}


def source_custody(manifest: dict[str, object]) -> Literal['ordinary', 'vault_private']:
    """Preserve private inputs across later handle-only render calls and source restoration."""
    return (
        'vault_private'
        if (
            manifest.get('source_custody') == 'vault_private'
            or expected_private_base(manifest) is not None
        )
        else 'ordinary'
    )
