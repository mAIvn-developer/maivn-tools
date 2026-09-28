"""Step-wise deterministic PDF generation toolset."""

# pyright: strict

from __future__ import annotations

import base64
import hashlib
import os
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

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
from ..artifacts import ManifestWorkspace
from ..documents.dependencies import CompositionDependencyError, requires_composition
from .models import (
    PDFBlock,
    PDFBlockPosition,
    PDFCompositionContent,
    PDFContentBlock,
    PDFHeadingBlock,
    PDFCompositionReference,
    PDFCompositionState,
    PDFDocumentHandle,
    PDFDocumentState,
    PDFOneShotBlock,
    PDFOneShotDocument,
)
from .renderer import render_pdf_bytes

if TYPE_CHECKING:
    from pathlib import Path

_CONTENT = TypeAdapter(PDFCompositionContent)
_BLOCK: TypeAdapter[PDFBlock] = TypeAdapter(PDFBlock)
_POSITION = TypeAdapter(PDFBlockPosition)
_ONE_SHOT = TypeAdapter(PDFOneShotDocument)
_HANDLE_SCHEMA = TypeAdapter(PDFDocumentHandle).json_schema()
_REFERENCE_SCHEMA = TypeAdapter(PDFCompositionReference).json_schema()
_STATE_SCHEMA = TypeAdapter(PDFDocumentState).json_schema()
_GENERATED_SCHEMA = GeneratedFile.model_json_schema()
_PDF_MIME = 'application/pdf'


@toolset(prefix='pdf', metadata={'serialize_calls': True})
class PDFToolSet:
    metadata = ProviderMetadata(
        name='pdf',
        display_name='PDF',
        version='0.1.0',
        description='Compose, inspect, and deterministically render local PDF files.',
        auth_modes=(AuthMode.NONE,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        tags=('artifacts', 'pdf', 'local'),
    )

    def __init__(self, output_dir: str | os.PathLike[str]) -> None:
        self._workspace = ManifestWorkspace(
            output_dir,
            workspace_name='pdf',
            id_field='document_id',
            extension='.pdf',
        )
        self.connection = None

    def compose_image(
        self,
        doc: PDFDocumentHandle,
        composition_id: str,
        *,
        content_base64: str,
        mime_type: str,
        alt_text: str,
    ) -> PDFCompositionReference:
        """Admit caller-authorized image bytes locally; this is not a model tool.

        Callers must resolve artifact authorization and custody before this call.
        Only the returned reference and safe image metadata enter tool results.
        """
        if not composition_id.strip():
            raise ValueError('composition_id must be a non-empty string')
        with self._workspace.lock:
            manifest = self._workspace.load(doc)
            image = admit_image(
                manifest, content_base64=content_base64, mime_type=mime_type, alt_text=alt_text
            )
            cast('dict[str, object]', manifest['compositions'])[composition_id] = {
                'kind': 'image',
                'image': image,
            }
            self._workspace.write(doc['document_id'], manifest)
        return {'document_id': doc['document_id'], 'composition_id': composition_id}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(_REFERENCE_SCHEMA)
    async def compose_artifact_image(
        self,
        doc: PDFDocumentHandle,
        composition_id: str,
        artifact_id: str,
        alt_text: str,
    ) -> PDFCompositionReference:
        """Compose an exact attached image ID through authenticated SDK retrieval.

        Use an image artifact_id supplied by a message attachment or completed
        image generation. The SDK refuses invented IDs and inaccessible images.
        Then put_block with type='image' and this reference to include it in the PDF.
        Include image_placement with width_inches, height_inches and alignment.
        """
        if not composition_id.strip():
            raise ValueError('composition_id must be a non-empty string')
        image = await resolve_artifact_image(artifact_id)
        with self._workspace.lock:
            manifest = self._workspace.load(doc)
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
            self._workspace.write(doc['document_id'], manifest)
        return {'document_id': doc['document_id'], 'composition_id': composition_id}

    def export_generated_file_source(self, generated: GeneratedFile) -> bytes:
        """Export the exact portable source through SDK-controlled artifact custody."""
        return export_source(self._workspace.workspace_dir, 'pdf', generated)

    def bind_generated_file_receipt(
        self, generated: GeneratedFile, artifact: OrdinaryArtifactRef
    ) -> None:
        """Persist an SDK-verified receipt and its exact rendered source."""
        bind_receipt(self._workspace.workspace_dir, 'document_id', generated, artifact)

    def resume_artifact(
        self, artifact: OrdinaryArtifactRef, *, source: bytes | None = None
    ) -> PDFDocumentHandle:
        """Resume the exact published source retained in this output directory.

        The selected artifact is the expected base for the next render. The
        data plane independently authorizes the caller and conversation.
        """
        if source is not None:
            import_source(self._workspace.workspace_dir, 'pdf', artifact, source)
        return cast(
            'PDFDocumentHandle',
            resume_source(self._workspace.workspace_dir, 'document_id', artifact),
        )

    def bind_private_generated_file_receipt(
        self, generated: GeneratedFile, artifact: PrivateArtifactRef
    ) -> None:
        """Persist the SDK-verified private revision for subsequent renders."""
        bind_private_receipt(self._workspace.workspace_dir, 'document_id', generated, artifact)

    def resume_private_artifact(
        self, artifact: PrivateArtifactRef, *, source: bytes
    ) -> PDFDocumentHandle:
        """Resume the exact bytes from private_artifacts.download_source on any host."""
        return cast(
            'PDFDocumentHandle',
            resume_private_source(
                self._workspace.workspace_dir, 'pdf', 'document_id', artifact, source
            ),
        )

    def sdk_private_workspace(self, arguments: Mapping[str, object]) -> bool:
        """Let the SDK shield readback from this exact locally owned private source."""
        handle = arguments.get('doc')
        if not isinstance(handle, Mapping):
            return False
        with self._workspace.lock:
            return (
                source_custody(self._workspace.load(cast('Mapping[str, object]', handle)))
                == 'vault_private'
            )

    def authorized_generated_file_roots(self) -> tuple[Path, ...]:
        """Return the output roots the SDK may admit for this toolset."""
        return (self._workspace.output_dir,)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(_HANDLE_SCHEMA)
    def create_document(self, filename: str) -> PDFDocumentHandle:
        return cast(
            'PDFDocumentHandle',
            self._workspace.create(filename, {'compositions': {}, 'blocks': []}),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(_REFERENCE_SCHEMA)
    def compose_artifact(
        self,
        doc: PDFDocumentHandle,
        composition_id: str,
        content: PDFCompositionContent,
    ) -> PDFCompositionReference:
        """Store content for put_block; only placed blocks appear in the PDF.

        Compose a heading label separately from the section's body paragraphs;
        otherwise the entire section receives heading typography.
        Keep prose concise, state shared caveats once, and use list content for
        action steps. Preserve all requested facts and any requested detail.
        """
        if not composition_id.strip():
            raise ValueError('composition_id must be a non-empty string')
        validated = _CONTENT.validate_python(content)
        self._validate_content(validated)
        with self._workspace.lock:
            manifest = self._workspace.load(doc)
            if validated['kind'] == 'image':
                image_bytes(manifest, cast('ImageReference', validated.get('image')))
            cast('dict[str, object]', manifest['compositions'])[composition_id] = validated
            self._workspace.write(doc['document_id'], manifest)
        return {'document_id': doc['document_id'], 'composition_id': composition_id}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(_STATE_SCHEMA)
    def read_document(self, doc: PDFDocumentHandle) -> PDFDocumentState:
        """Inspect the outline and verify all requested text and images are placed.

        After numeric edits, review all related totals and qualitative assertions
        such as equal allocations or unchanged trends; revise any that are stale.
        """
        with self._workspace.lock:
            manifest = self._workspace.load(doc)
        compositions = cast('dict[str, PDFCompositionContent]', manifest['compositions'])
        states: list[PDFCompositionState] = [
            {'composition_id': key, 'content': value} for key, value in sorted(compositions.items())
        ]
        return {
            'document': doc,
            'compositions': states,
            'outline': cast('list[dict[str, object]]', manifest['blocks']),
        }

    @requires_composition(
        'block',
        reference_key='composition',
        allow_missing_for=('page_break', 'spacer'),
        upstream_tool='PDF_compose_artifact',
    )
    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def put_block(
        self,
        doc: PDFDocumentHandle,
        block_id: str,
        block: PDFBlock,
        position: PDFBlockPosition,
    ) -> dict[str, object]:
        """Place or update composed content, including an authenticated image.

        Use title/heading for a short label only, paragraph for body prose, and
        bullet_list/numbered_list for list items. Place the heading and its body
        as separate blocks; every word in a heading block receives heading style.
        Once composition references are available, submit known placements in
        document order together in one model turn. This SDK toolset runs writes
        one at a time in arrival order; separate turns per block are unnecessary.
        Wait for any preceding call whose returned value is still needed.
        """
        if not block_id.strip():
            raise ValueError('block_id must be a non-empty string')
        validated_block = _BLOCK.validate_python(block)
        validated_position = _POSITION.validate_python(position)
        with self._workspace.lock:
            manifest = self._workspace.load(doc)
            self._validate_block(manifest, validated_block)
            blocks = cast('list[dict[str, object]]', manifest['blocks'])
            existing = next(
                (index for index, entry in enumerate(blocks) if entry['block_id'] == block_id),
                None,
            )
            created = existing is None
            if existing is not None:
                if blocks[existing]['position'] == validated_position:
                    blocks[existing] = {
                        'block_id': block_id,
                        'block': validated_block,
                        'position': validated_position,
                    }
                    self._workspace.write(doc['document_id'], manifest)
                    return {'document': doc, 'block_id': block_id, 'created': False}
                blocks.pop(existing)
            blocks.insert(
                self._insertion_index(blocks, validated_position),
                {
                    'block_id': block_id,
                    'block': validated_block,
                    'position': validated_position,
                },
            )
            self._workspace.write(doc['document_id'], manifest)
        return {'document': doc, 'block_id': block_id, 'created': created}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def remove_block(self, doc: PDFDocumentHandle, block_id: str) -> dict[str, object]:
        with self._workspace.lock:
            manifest = self._workspace.load(doc)
            blocks = cast('list[dict[str, object]]', manifest['blocks'])
            retained = [entry for entry in blocks if entry['block_id'] != block_id]
            removed = len(retained) != len(blocks)
            manifest['blocks'] = retained
            if removed:
                self._workspace.write(doc['document_id'], manifest)
        return {'document': doc, 'block_id': block_id, 'removed': removed}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(_GENERATED_SCHEMA)
    def render_document(
        self,
        doc: PDFDocumentHandle,
        *,
        overwrite: bool = False,
        include_bytes: bool = False,
    ) -> GeneratedFile:
        """Render placed blocks after checking read_document for missing requested content."""
        with self._workspace.lock:
            manifest = self._workspace.load(doc)
            for entry in cast('list[dict[str, object]]', manifest['blocks']):
                self._validate_block(manifest, cast('PDFBlock', entry['block']))
            raw = render_pdf_bytes(manifest)
            target = self._workspace.write_output(
                str(manifest['filename']), raw, overwrite=overwrite
            )
            source_revision = snapshot_source(self._workspace.workspace_dir, manifest, raw)
            target = immutable_render_path(
                self._workspace.workspace_dir, source_revision, target.name, raw
            )
        return GeneratedFile(
            kind='generated_file',
            artifact_kind='document',
            filename=str(manifest['filename']),
            path=str(target),
            mime_type=_PDF_MIME,
            size_bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            custody=source_custody(manifest),
            expected_base=expected_base(manifest),
            private_expected_base=expected_private_base(manifest),
            workspace={
                'document_id': doc['document_id'],
                'filename': doc['filename'],
                'source_revision': source_revision,
            },
            content_base64=base64.b64encode(raw).decode('ascii') if include_bytes else None,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(_GENERATED_SCHEMA)
    def create_pdf(
        self,
        filename: str,
        document: PDFOneShotDocument,
        *,
        overwrite: bool = False,
        include_bytes: bool = False,
    ) -> GeneratedFile:
        validated = _ONE_SHOT.validate_python(document)
        target = self._workspace.safe_output_path(filename)
        if target.exists() and not overwrite:
            raise FileExistsError(str(target))
        doc = self.create_document(filename)
        try:
            for source in validated['blocks']:
                block = self._one_shot_block(doc, source)
                self.put_block(doc, source['block_id'], block, {'anchor': 'end'})
            return self.render_document(doc, overwrite=overwrite, include_bytes=include_bytes)
        except Exception:
            self._workspace.discard(doc)
            raise

    def validate_composition_reference(
        self,
        doc: object,
        reference: object,
        argument_name: str,
    ) -> None:
        required = 'PDF_compose_artifact'
        if not isinstance(doc, Mapping) or not isinstance(reference, Mapping):
            raise CompositionDependencyError(
                f"argument '{argument_name}' requires a valid existing composition reference "
                f'returned by {required}'
            )
        doc_map = cast('Mapping[object, object]', doc)
        ref_map = cast('Mapping[object, object]', reference)
        composition_id = ref_map.get('composition_id')
        if ref_map.get('document_id') != doc_map.get('document_id') or not isinstance(
            composition_id, str
        ):
            raise CompositionDependencyError(
                f"argument '{argument_name}' requires a valid existing composition reference "
                f'returned by {required}'
            )
        manifest = self._workspace.load(cast('PDFDocumentHandle', doc))
        if composition_id not in cast('dict[str, object]', manifest['compositions']):
            raise CompositionDependencyError(
                f"argument '{argument_name}' references unknown composition '{composition_id}'; "
                f'call {required} first'
            )

    @staticmethod
    def _validate_content(content: PDFCompositionContent) -> None:
        if content['kind'] == 'image':
            if not content.get('image'):
                raise ValueError('image compositions require an admitted image reference')
            return
        if content['kind'] == 'text' and not isinstance(content.get('text'), str):
            raise ValueError("text compositions require a 'text' string")
        if content['kind'] == 'list' and not content.get('items'):
            raise ValueError("list compositions require a non-empty 'items' list")
        if content['kind'] == 'table':
            rows = content.get('rows')
            if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
                raise ValueError('table composition rows must be non-empty and rectangular')

    @staticmethod
    def _validate_block(manifest: dict[str, object], block: PDFBlock) -> None:
        block_type = block['type']
        if block_type == 'image':
            validate_placement(block.get('image_placement'), max_width=6.3, max_height=9.2)
        if block_type in {'page_break', 'spacer'}:
            if block_type == 'spacer' and not 0 <= block.get('height', 12) <= 144:
                raise ValueError('spacer height must be between 0 and 144 points')
            return
        if block_type == 'heading' and not 1 <= block.get('level', 0) <= 9:
            raise ValueError('heading blocks require level between 1 and 9')
        reference = block.get('composition')
        if reference is None:
            raise CompositionDependencyError(
                "argument 'block.composition' requires PDF_compose_artifact"
            )
        content = cast('dict[str, PDFCompositionContent]', manifest['compositions'])[
            reference['composition_id']
        ]
        expected = {
            'title': 'text',
            'heading': 'text',
            'paragraph': 'text',
            'bullet_list': 'list',
            'numbered_list': 'list',
            'table': 'table',
            'image': 'image',
        }[block_type]
        if content['kind'] != expected:
            raise ValueError(f"block type '{block_type}' requires a {expected} composition")

    @staticmethod
    def _insertion_index(blocks: list[dict[str, object]], position: PDFBlockPosition) -> int:
        if position['anchor'] == 'start':
            return 0
        if position['anchor'] == 'end':
            return len(blocks)
        anchor_id = position.get('block_id')
        if not anchor_id:
            raise ValueError(f"position anchor '{position['anchor']}' requires block_id")
        for index, entry in enumerate(blocks):
            if entry['block_id'] == anchor_id:
                return index if position['anchor'] == 'before' else index + 1
        raise ValueError(f"position anchor references unknown block_id '{anchor_id}'")

    def _one_shot_block(self, doc: PDFDocumentHandle, source: PDFOneShotBlock) -> PDFBlock:
        if source['type'] in {'page_break', 'spacer'}:
            return cast(
                'PDFBlock',
                {'type': source['type'], 'height': source.get('height', 12)},
            )
        if source['type'] in {'title', 'heading', 'paragraph'}:
            content = cast('PDFCompositionContent', {'kind': 'text', 'text': source.get('content')})
        elif source['type'] in {'bullet_list', 'numbered_list'}:
            content = cast('PDFCompositionContent', {'kind': 'list', 'items': source.get('items')})
        else:
            content = cast('PDFCompositionContent', {'kind': 'table', 'rows': source.get('rows')})
        reference = self.compose_artifact(doc, f'{source["block_id"]}-content', content)
        if source['type'] == 'heading':
            return cast(
                'PDFHeadingBlock',
                {'type': 'heading', 'composition': reference, 'level': source.get('level')},
            )
        return cast('PDFContentBlock', {'type': source['type'], 'composition': reference})
