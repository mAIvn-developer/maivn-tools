"""Step-wise document-generation toolset."""

# pyright: strict

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from maivn import tool_output, toolify, toolset
from maivn.artifact_images import resolve_artifact_image
from maivn_contracts.artifacts import GeneratedFile, OrdinaryArtifactRef, PrivateArtifactRef
from pydantic import TypeAdapter

from ..artifacts.revisions import (
    bind_private_receipt,
    expected_private_base,
    resume_private_source,
    immutable_render_path,
    bind_receipt,
    expected_base,
    resume_source,
    snapshot_source,
    source_custody,
    export_source,
    import_source,
)
from ..artifacts.images import ImageReference, admit_image, image_bytes, validate_placement
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ..artifacts.workspace import assert_process_owner, process_lock_for
from .dependencies import CompositionDependencyError, requires_composition
from .models import (
    BlockPosition,
    CompositionContent,
    CompositionReference,
    CompositionState,
    DocumentHandle,
    DocumentBlock,
    DocumentState,
    OneShotBlock,
    OneShotDocument,
)
from .renderer import render_docx_bytes

# Six attempts back off over ~310ms total. Empirically (R5, 2026-08-26): the
# prior 4-attempt/~70ms budget survived a foreign handle held 60ms but lost to
# one held 150ms - scanners and indexers routinely exceed 70ms on larger files.
_ATOMIC_REPLACE_ATTEMPTS = 6
_ATOMIC_REPLACE_INITIAL_DELAY_SECONDS = 0.01


def _replace_with_retry(source: Path, target: Path) -> None:
    """Atomically replace a file, tolerating brief Windows handle locks.

    On Windows, os.replace onto a destination another handle still holds open
    raises PermissionError where POSIX rename succeeds; concurrent document
    handles are a supported pattern, so brief contention is expected here.
    Mirrors the artifacts connector's helper of the same name.
    """
    for attempt in range(_ATOMIC_REPLACE_ATTEMPTS):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == _ATOMIC_REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_ATOMIC_REPLACE_INITIAL_DELAY_SECONDS * (2**attempt))


_CONTENT_ADAPTER: TypeAdapter[CompositionContent] = TypeAdapter(CompositionContent)
_BLOCK_ADAPTER: TypeAdapter[DocumentBlock] = TypeAdapter(DocumentBlock)
_POSITION_ADAPTER: TypeAdapter[BlockPosition] = TypeAdapter(BlockPosition)
_ONE_SHOT_ADAPTER: TypeAdapter[OneShotDocument] = TypeAdapter(OneShotDocument)
_DOCX_MIME_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
_DOCUMENT_HANDLE_OUTPUT = TypeAdapter(DocumentHandle).json_schema()
_COMPOSITION_REFERENCE_OUTPUT = TypeAdapter(CompositionReference).json_schema()
_DOCUMENT_STATE_OUTPUT = TypeAdapter(DocumentState).json_schema()
_GENERATED_FILE_OUTPUT = GeneratedFile.model_json_schema()
_DOCUMENT_ID_PATTERN = re.compile(r'[0-9a-f]{32}')


@toolset(prefix='documents', metadata={'serialize_calls': True})
class DocumentsToolSet:
    """Build deterministic documents in a persisted local workspace."""

    metadata = ProviderMetadata(
        name='documents',
        display_name='Documents',
        version='0.1.0',
        description='Compose, inspect, and deterministically render local document files.',
        auth_modes=(AuthMode.NONE,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        tags=('artifacts', 'documents', 'local'),
    )

    def __init__(self, output_dir: str | os.PathLike[str]) -> None:
        self._output_dir = Path(output_dir).expanduser().resolve()
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._workspace_dir = self._output_dir / '.maivn-documents'
        self._workspace_dir.mkdir(exist_ok=True)
        self._owner_process_id = os.getpid()
        self._manifest_lock = process_lock_for(self._workspace_dir)
        self.connection = None

    def compose_image(
        self,
        doc: DocumentHandle,
        composition_id: str,
        *,
        content_base64: str,
        mime_type: str,
        alt_text: str,
    ) -> CompositionReference:
        """Admit caller-authorized image bytes locally; this is not a model tool.

        Callers must resolve artifact authorization and custody before this call.
        Only the returned reference and safe image metadata enter tool results.
        """
        if not composition_id.strip():
            raise ValueError('composition_id must be a non-empty string')
        with self._manifest_lock:
            manifest = self._load_manifest(doc)
            image = admit_image(
                manifest, content_base64=content_base64, mime_type=mime_type, alt_text=alt_text
            )
            cast('dict[str, object]', manifest['compositions'])[composition_id] = {
                'kind': 'image',
                'image': image,
            }
            self._write_manifest(doc['document_id'], manifest)
        return {'document_id': doc['document_id'], 'composition_id': composition_id}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(_COMPOSITION_REFERENCE_OUTPUT)
    async def compose_artifact_image(
        self,
        doc: DocumentHandle,
        composition_id: str,
        artifact_id: str,
        alt_text: str,
    ) -> CompositionReference:
        """Compose an exact attached image ID through authenticated SDK retrieval.

        Use an image artifact_id supplied by a message attachment or completed
        image generation. The SDK refuses invented IDs and inaccessible images.
        Then call put_block with type='image' and this composition reference.
        Include image_placement with width_inches, height_inches and alignment.
        Composing stores the image; only a placed block appears in the DOCX.
        """
        if not composition_id.strip():
            raise ValueError('composition_id must be a non-empty string')
        image = await resolve_artifact_image(artifact_id)
        with self._manifest_lock:
            manifest = self._load_manifest(doc)
            reference = admit_image(
                manifest,
                content_base64=base64.b64encode(image.content).decode('ascii'),
                mime_type=image.mime_type,
                alt_text=alt_text,
                custody='vault_private' if image.private else 'ordinary',
            )
            cast('dict[str, object]', manifest['compositions'])[composition_id] = {
                'kind': 'image',
                'image': reference,
            }
            self._write_manifest(doc['document_id'], manifest)
        return {'document_id': doc['document_id'], 'composition_id': composition_id}

    def export_generated_file_source(self, generated: GeneratedFile) -> bytes:
        """Export the exact portable source through SDK-controlled artifact custody."""
        return export_source(self._workspace_dir, 'documents', generated)

    def bind_generated_file_receipt(
        self, generated: GeneratedFile, artifact: OrdinaryArtifactRef
    ) -> None:
        """Persist an SDK-verified receipt and its exact rendered source."""
        bind_receipt(self._workspace_dir, 'document_id', generated, artifact)

    def resume_artifact(
        self, artifact: OrdinaryArtifactRef, *, source: bytes | None = None
    ) -> DocumentHandle:
        """Resume the exact published source retained in this output directory.

        The selected artifact is the expected base for the next render. The
        data plane independently authorizes the caller and conversation.
        """
        if source is not None:
            import_source(self._workspace_dir, 'documents', artifact, source)
        return cast('DocumentHandle', resume_source(self._workspace_dir, 'document_id', artifact))

    def bind_private_generated_file_receipt(
        self, generated: GeneratedFile, artifact: PrivateArtifactRef
    ) -> None:
        """Persist the SDK-verified private revision for subsequent renders."""
        bind_private_receipt(self._workspace_dir, 'document_id', generated, artifact)

    def resume_private_artifact(
        self, artifact: PrivateArtifactRef, *, source: bytes
    ) -> DocumentHandle:
        """Resume the exact bytes from private_artifacts.download_source on any host."""
        return cast(
            'DocumentHandle',
            resume_private_source(
                self._workspace_dir, 'documents', 'document_id', artifact, source
            ),
        )

    def sdk_private_workspace(self, arguments: Mapping[str, object]) -> bool:
        """Let the SDK shield readback from this exact locally owned private source."""
        doc = arguments.get('doc')
        if not isinstance(doc, Mapping):
            return False
        with self._manifest_lock:
            return (
                source_custody(self._load_manifest(cast('DocumentHandle', doc))) == 'vault_private'
            )

    def authorized_generated_file_roots(self) -> tuple[Path, ...]:
        """Return the output roots the SDK may admit for this toolset."""
        return (self._output_dir,)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(_DOCUMENT_HANDLE_OUTPUT)
    def create_document(self, filename: str) -> DocumentHandle:
        """Create a persisted document workspace and return its handle."""
        self._safe_output_path(filename)
        document_id = uuid.uuid4().hex
        handle: DocumentHandle = {'document_id': document_id, 'filename': filename}
        manifest: dict[str, object] = {
            'version': 1,
            'document_id': document_id,
            'filename': filename,
            'compositions': {},
            'blocks': [],
        }
        manifest_path = self._workspace_dir / f'{document_id}.json'
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n',
            encoding='utf-8',
        )
        return handle

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(_COMPOSITION_REFERENCE_OUTPUT)
    def compose_artifact(
        self,
        doc: DocumentHandle,
        composition_id: str,
        content: CompositionContent,
    ) -> CompositionReference:
        """Store authored content and return its reference for ``put_block``.

        Call put_block for each paragraph, title, list or table to include it in
        the document. Compositions alone do not appear in the rendered file.
        Compose a heading label separately from the section's body paragraphs;
        otherwise the entire section receives heading typography.
        Keep prose concise, state shared caveats once, and use list content for
        action steps. Preserve all requested facts and any requested detail.
        """
        if not composition_id.strip():
            raise ValueError('composition_id must be a non-empty string')
        validated: CompositionContent = _CONTENT_ADAPTER.validate_python(content)
        self._validate_composition_content(validated)
        with self._manifest_lock:
            manifest = self._load_manifest(doc)
            if validated['kind'] == 'image':
                image_bytes(manifest, cast('ImageReference', validated.get('image')))
            compositions = cast('dict[str, object]', manifest['compositions'])
            compositions[composition_id] = validated
            self._write_manifest(doc['document_id'], manifest)
        return {
            'document_id': doc['document_id'],
            'composition_id': composition_id,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(_DOCUMENT_STATE_OUTPUT)
    def read_document(self, doc: DocumentHandle) -> DocumentState:
        """Inspect composed content and the ordered blocks that will actually render.

        Before rendering, verify every requested paragraph, table and image is
        present in outline. Content listed only in compositions is not placed.
        After numeric edits, review all related totals and qualitative assertions
        such as equal allocations or unchanged trends; revise any that are stale.
        """
        with self._manifest_lock:
            manifest = self._load_manifest(doc)
        compositions = cast('dict[str, CompositionContent]', manifest['compositions'])
        states: list[CompositionState] = [
            {'composition_id': composition_id, 'content': content}
            for composition_id, content in sorted(compositions.items())
        ]
        return {
            'document': {
                'document_id': cast('str', manifest['document_id']),
                'filename': cast('str', manifest['filename']),
            },
            'compositions': states,
            'outline': cast('list[dict[str, object]]', manifest['blocks']),
        }

    @requires_composition('block', reference_key='composition', allow_missing_for=('page_break',))
    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def put_block(
        self,
        doc: DocumentHandle,
        block_id: str,
        block: DocumentBlock,
        position: BlockPosition,
    ) -> dict[str, object]:
        """Idempotently add or revise one positioned block using composed content.

        Use title/heading for a short label only, paragraph for body prose, and
        bullet_list/numbered_list for list items. Place the heading and its body
        as separate blocks; every word in a heading block receives heading style.
        Once composition references are available, submit known placements in
        document order together in one model turn. This SDK toolset runs writes
        one at a time in arrival order; separate turns per block are unnecessary.
        Wait for any preceding call whose returned value is still needed.
        """
        if not block_id:
            raise ValueError('block_id must be a non-empty string')
        validated_block: DocumentBlock = _BLOCK_ADAPTER.validate_python(block)
        validated_position: BlockPosition = _POSITION_ADAPTER.validate_python(position)
        with self._manifest_lock:
            manifest = self._load_manifest(doc)
            self._validate_block_content_kind(manifest, validated_block)
            blocks = cast('list[dict[str, object]]', manifest['blocks'])
            existing_index = next(
                (index for index, entry in enumerate(blocks) if entry.get('block_id') == block_id),
                None,
            )
            created = existing_index is None
            entry: dict[str, object] = {
                'block_id': block_id,
                'block': validated_block,
                'position': validated_position,
            }
            if existing_index is not None:
                existing = blocks[existing_index]
                if existing.get('position') == validated_position:
                    blocks[existing_index] = entry
                    self._write_manifest(doc['document_id'], manifest)
                    return {'document': doc, 'block_id': block_id, 'created': False}
                blocks.pop(existing_index)
            insertion_index = self._insertion_index(blocks, validated_position)
            blocks.insert(insertion_index, entry)
            self._write_manifest(doc['document_id'], manifest)
        return {'document': doc, 'block_id': block_id, 'created': created}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def remove_block(self, doc: DocumentHandle, block_id: str) -> dict[str, object]:
        """Idempotently remove one block while retaining its authored composition."""
        if not block_id:
            raise ValueError('block_id must be a non-empty string')
        with self._manifest_lock:
            manifest = self._load_manifest(doc)
            blocks = cast('list[dict[str, object]]', manifest['blocks'])
            retained = [entry for entry in blocks if entry.get('block_id') != block_id]
            removed = len(retained) != len(blocks)
            manifest['blocks'] = retained
            if removed:
                self._write_manifest(doc['document_id'], manifest)
        return {'document': doc, 'block_id': block_id, 'removed': removed}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(_GENERATED_FILE_OUTPUT)
    def render_document(
        self,
        doc: DocumentHandle,
        *,
        overwrite: bool = False,
        include_bytes: bool = False,
    ) -> GeneratedFile:
        """Render placed blocks to a deterministic DOCX attachment.

        First read_document and verify the outline contains all requested content.
        Unplaced compositions are excluded. Use put_block to insert missing text
        or images. A successful render confirms file creation, not completeness.
        """
        with self._manifest_lock:
            manifest = self._load_manifest(doc)
            for entry in cast('list[dict[str, object]]', manifest['blocks']):
                self._validate_block_content_kind(
                    manifest,
                    cast('DocumentBlock', entry['block']),
                )
            raw = render_docx_bytes(manifest)
            target = self._safe_output_path(str(manifest['filename']))
            if overwrite:
                temporary = self._output_dir / f'.{target.name}.{uuid.uuid4().hex}.tmp'
                temporary.write_bytes(raw)
                _replace_with_retry(temporary, target)
            else:
                with target.open('xb') as stream:
                    stream.write(raw)
            source_revision = snapshot_source(self._workspace_dir, manifest, raw)
            target = immutable_render_path(self._workspace_dir, source_revision, target.name, raw)
        return GeneratedFile(
            kind='generated_file',
            artifact_kind='document',
            filename=str(manifest['filename']),
            path=str(target),
            mime_type=_DOCX_MIME_TYPE,
            size_bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            custody=source_custody(manifest),
            expected_base=expected_base(manifest),
            private_expected_base=expected_private_base(manifest),
            workspace={
                'source_revision': source_revision,
                'document_id': doc['document_id'],
                'filename': doc['filename'],
            },
            content_base64=(base64.b64encode(raw).decode('ascii') if include_bytes else None),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(_GENERATED_FILE_OUTPUT)
    def create_docx(
        self,
        filename: str,
        document: OneShotDocument,
        *,
        overwrite: bool = False,
        include_bytes: bool = False,
    ) -> GeneratedFile:
        """Build a small DOCX through the persisted compose/place/render pipeline."""
        validated: OneShotDocument = _ONE_SHOT_ADAPTER.validate_python(document)
        self._preflight_one_shot(filename, validated, overwrite=overwrite)
        doc = self.create_document(filename)
        try:
            for source in validated['blocks']:
                block_id = source['block_id']
                block_type = source['type']
                if block_type == 'page_break':
                    block = cast('DocumentBlock', {'type': 'page_break'})
                else:
                    composition_id = f'{block_id}-content'
                    content = self._one_shot_content(source)
                    reference = self.compose_artifact(doc, composition_id, content)
                    if block_type == 'heading':
                        block = cast(
                            'DocumentBlock',
                            {
                                'type': 'heading',
                                'level': cast('int', source.get('level')),
                                'composition': reference,
                            },
                        )
                    else:
                        block = cast(
                            'DocumentBlock',
                            {'type': block_type, 'composition': reference},
                        )
                self.put_block(doc, block_id, block, {'anchor': 'end'})
            return self.render_document(doc, overwrite=overwrite, include_bytes=include_bytes)
        except Exception:
            self._discard_workspace(doc)
            raise

    def validate_composition_reference(
        self,
        doc: object,
        reference: object,
        argument_name: str,
    ) -> None:
        required = 'DOCUMENTS_compose_artifact'
        if not isinstance(doc, Mapping):
            raise CompositionDependencyError(
                f"argument '{argument_name}' requires a valid document handle and a reference "
                f'returned by {required}'
            )
        if not isinstance(reference, Mapping):
            raise CompositionDependencyError(
                f"argument '{argument_name}' requires a valid existing composition reference "
                f'returned by {required}'
            )
        document_mapping = cast('Mapping[object, object]', doc)
        reference_mapping = cast('Mapping[object, object]', reference)
        document_id = reference_mapping.get('document_id')
        composition_id = reference_mapping.get('composition_id')
        if document_id != document_mapping.get('document_id') or not isinstance(
            composition_id, str
        ):
            raise CompositionDependencyError(
                f"argument '{argument_name}' requires a valid existing composition reference "
                f'returned by {required}'
            )
        manifest = self._load_manifest(cast('DocumentHandle', doc))
        compositions = cast('dict[str, object]', manifest['compositions'])
        if composition_id not in compositions:
            raise CompositionDependencyError(
                f"argument '{argument_name}' references unknown composition '{composition_id}'; "
                f'call {required} first'
            )

    @staticmethod
    def _insertion_index(
        blocks: list[dict[str, object]],
        position: BlockPosition,
    ) -> int:
        anchor = position['anchor']
        if anchor == 'start':
            return 0
        if anchor == 'end':
            return len(blocks)
        anchor_id = position.get('block_id')
        if not anchor_id:
            raise ValueError(f"position anchor '{anchor}' requires block_id")
        for index, entry in enumerate(blocks):
            if entry.get('block_id') == anchor_id:
                return index if anchor == 'before' else index + 1
        raise ValueError(f"position anchor references unknown block_id '{anchor_id}'")

    @staticmethod
    def _validate_block_content_kind(
        manifest: dict[str, object],
        block: DocumentBlock,
    ) -> None:
        block_type = block['type']
        if block_type == 'image':
            validate_placement(block.get('image_placement'), max_width=6, max_height=8.5)
        if block_type == 'page_break':
            return
        heading_level = block.get('level')
        if block_type == 'heading' and (
            not isinstance(heading_level, int) or not 1 <= heading_level <= 9
        ):
            raise ValueError('heading blocks require level between 1 and 9')
        reference = block.get('composition')
        if reference is None:
            raise CompositionDependencyError(
                "argument 'block.composition' requires a valid existing composition reference "
                'returned by DOCUMENTS_compose_artifact'
            )
        compositions = cast('dict[str, CompositionContent]', manifest['compositions'])
        content = compositions[reference['composition_id']]
        expected_kind = {
            'title': 'text',
            'heading': 'text',
            'paragraph': 'text',
            'bullet_list': 'list',
            'numbered_list': 'list',
            'table': 'table',
            'image': 'image',
        }[block_type]
        if content['kind'] != expected_kind:
            raise ValueError(
                f"block type '{block_type}' requires a {expected_kind} composition, "
                f'got {content["kind"]}'
            )

    @staticmethod
    def _validate_composition_content(content: CompositionContent) -> None:
        if content['kind'] == 'image':
            if not content.get('image'):
                raise ValueError('image compositions require an admitted image reference')
            return
        kind = content['kind']
        if kind == 'text':
            if not isinstance(content.get('text'), str):
                raise ValueError("text compositions require a 'text' string")
            return
        if kind == 'list':
            items = content.get('items')
            if not isinstance(items, list) or not items:
                raise ValueError("list compositions require a non-empty 'items' list")
            return
        rows = content.get('rows')
        if not isinstance(rows, list) or not rows or not rows[0]:
            raise ValueError("table compositions require non-empty 'rows'")
        column_count = len(rows[0])
        if any(len(row) != column_count for row in rows):
            raise ValueError('table composition rows must all have the same number of columns')

    def _load_manifest(self, doc: DocumentHandle) -> dict[str, object]:
        assert_process_owner(self._owner_process_id)
        if _DOCUMENT_ID_PATTERN.fullmatch(doc['document_id']) is None:
            raise ValueError('invalid document handle')
        manifest_path = self._workspace_dir / f'{doc["document_id"]}.json'
        if not manifest_path.is_file():
            raise ValueError(f'unknown document handle: {doc["document_id"]}')
        manifest = cast(
            'dict[str, object]',
            json.loads(manifest_path.read_text(encoding='utf-8')),
        )
        if manifest.get('version') != 1:
            raise ValueError('unsupported manifest version')
        if manifest.get('document_id') != doc['document_id'] or doc['filename'] not in (
            manifest.get('filename'),
            manifest.get('private_handle_filename'),
        ):
            raise ValueError('document handle does not match its persisted workspace')
        return manifest

    def _safe_output_path(self, filename: str) -> Path:
        assert_process_owner(self._owner_process_id)
        target = (self._output_dir / filename).resolve()
        if target.parent != self._output_dir or target.suffix.lower() != '.docx':
            raise ValueError('filename must be a .docx file directly beneath output_dir')
        return target

    def _preflight_one_shot(
        self,
        filename: str,
        document: OneShotDocument,
        *,
        overwrite: bool,
    ) -> None:
        target = self._safe_output_path(filename)
        if target.exists() and not overwrite:
            raise FileExistsError(str(target))
        block_ids = [block['block_id'] for block in document['blocks']]
        if any(not block_id.strip() for block_id in block_ids) or len(set(block_ids)) != len(
            block_ids
        ):
            raise ValueError('one-shot block_id values must be non-empty and unique')
        for block in document['blocks']:
            if block['type'] == 'page_break':
                continue
            self._validate_composition_content(self._one_shot_content(block))
            if block['type'] == 'heading':
                level = block.get('level')
                if not isinstance(level, int) or not 1 <= level <= 9:
                    raise ValueError('one-shot heading blocks require level between 1 and 9')

    @staticmethod
    def _one_shot_content(source: OneShotBlock) -> CompositionContent:
        block_type = source['type']
        if block_type in {'title', 'heading', 'paragraph'}:
            return cast(
                'CompositionContent',
                {'kind': 'text', 'text': source.get('content')},
            )
        if block_type in {'bullet_list', 'numbered_list'}:
            return cast(
                'CompositionContent',
                {'kind': 'list', 'items': source.get('items')},
            )
        return cast(
            'CompositionContent',
            {'kind': 'table', 'rows': source.get('rows')},
        )

    def _discard_workspace(self, doc: DocumentHandle) -> None:
        assert_process_owner(self._owner_process_id)
        with self._manifest_lock:
            (self._workspace_dir / f'{doc["document_id"]}.json').unlink(missing_ok=True)

    def _write_manifest(self, document_id: str, manifest: dict[str, object]) -> None:
        assert_process_owner(self._owner_process_id)
        manifest_path = self._workspace_dir / f'{document_id}.json'
        temporary_path = self._workspace_dir / f'.{document_id}.{uuid.uuid4().hex}.tmp'
        temporary_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n',
            encoding='utf-8',
        )
        _replace_with_retry(temporary_path, manifest_path)
