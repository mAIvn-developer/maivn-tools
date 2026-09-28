"""Step-wise deterministic PPTX generation toolset."""

# pyright: strict

from __future__ import annotations

import base64
import hashlib
import math
import os
from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal, cast

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
from ..artifacts.images import ImageReference, admit_image, image_bytes
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ..artifacts import ManifestWorkspace
from ..documents.dependencies import CompositionDependencyError, requires_composition
from .models import (
    OneShotPresentation,
    PresentationCompositionContent,
    PresentationCompositionReference,
    PresentationCompositionState,
    PresentationElement,
    PresentationHandle,
    PresentationPosition,
    PresentationState,
)
from .renderer import render_pptx_bytes
from .layout import LayoutIssue, inspect_layout

if TYPE_CHECKING:
    from pathlib import Path

_CONTENT = TypeAdapter(PresentationCompositionContent)
_ELEMENT = TypeAdapter(PresentationElement)
_POSITION = TypeAdapter(PresentationPosition)
_ONE_SHOT = TypeAdapter(OneShotPresentation)
_HANDLE_SCHEMA = TypeAdapter(PresentationHandle).json_schema()
_REFERENCE_SCHEMA = TypeAdapter(PresentationCompositionReference).json_schema()
_STATE_SCHEMA = TypeAdapter(PresentationState).json_schema()
_GENERATED_SCHEMA = GeneratedFile.model_json_schema()
_PPTX_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'


@toolset(prefix='presentations', metadata={'serialize_calls': True})
class PresentationsToolSet:
    metadata = ProviderMetadata(
        name='presentations',
        display_name='Presentations',
        version='0.1.0',
        description='Compose, inspect, and deterministically render local PPTX files.',
        auth_modes=(AuthMode.NONE,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        tags=('artifacts', 'presentations', 'local'),
    )

    def __init__(self, output_dir: str | os.PathLike[str]) -> None:
        self._workspace = ManifestWorkspace(
            output_dir,
            workspace_name='presentations',
            id_field='presentation_id',
            extension='.pptx',
        )
        self.connection = None

    def compose_image(
        self,
        doc: PresentationHandle,
        composition_id: str,
        *,
        content_base64: str,
        mime_type: str,
        alt_text: str,
    ) -> PresentationCompositionReference:
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
            self._workspace.write(doc['presentation_id'], manifest)
        return {'presentation_id': doc['presentation_id'], 'composition_id': composition_id}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(_REFERENCE_SCHEMA)
    async def compose_artifact_image(
        self,
        doc: PresentationHandle,
        composition_id: str,
        artifact_id: str,
        alt_text: str,
    ) -> PresentationCompositionReference:
        """Compose an exact attached image ID through authenticated SDK retrieval.

        Use an image artifact_id supplied by a message attachment or completed
        image generation. The SDK refuses invented IDs and inaccessible images.
        Then put_element with type='image', this reference and slide coordinates.
        Only placed elements appear in the rendered slides.
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
            self._workspace.write(doc['presentation_id'], manifest)
        return {'presentation_id': doc['presentation_id'], 'composition_id': composition_id}

    def export_generated_file_source(self, generated: GeneratedFile) -> bytes:
        """Export the exact portable source through SDK-controlled artifact custody."""
        return export_source(self._workspace.workspace_dir, 'presentations', generated)

    def bind_generated_file_receipt(
        self, generated: GeneratedFile, artifact: OrdinaryArtifactRef
    ) -> None:
        """Persist an SDK-verified receipt and its exact rendered source."""
        bind_receipt(self._workspace.workspace_dir, 'presentation_id', generated, artifact)

    def resume_artifact(
        self, artifact: OrdinaryArtifactRef, *, source: bytes | None = None
    ) -> PresentationHandle:
        """Resume the exact published source retained in this output directory.

        The selected artifact is the expected base for the next render. The
        data plane independently authorizes the caller and conversation.
        """
        if source is not None:
            import_source(self._workspace.workspace_dir, 'presentations', artifact, source)
        return cast(
            'PresentationHandle',
            resume_source(self._workspace.workspace_dir, 'presentation_id', artifact),
        )

    def bind_private_generated_file_receipt(
        self, generated: GeneratedFile, artifact: PrivateArtifactRef
    ) -> None:
        """Persist the SDK-verified private revision for subsequent renders."""
        bind_private_receipt(self._workspace.workspace_dir, 'presentation_id', generated, artifact)

    def resume_private_artifact(
        self, artifact: PrivateArtifactRef, *, source: bytes
    ) -> PresentationHandle:
        """Resume the exact bytes from private_artifacts.download_source on any host."""
        return cast(
            'PresentationHandle',
            resume_private_source(
                self._workspace.workspace_dir, 'presentations', 'presentation_id', artifact, source
            ),
        )

    def sdk_private_workspace(self, arguments: Mapping[str, object]) -> bool:
        """Let the SDK shield readback from this exact locally owned private source."""
        handle = arguments.get('presentation')
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

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(TypeAdapter(list[LayoutIssue]).json_schema())
    def inspect_layout(self, presentation: PresentationHandle) -> list[LayoutIssue]:
        """Report estimated clipping, overlaps, and suspicious text for review.

        Review literal escapes and body line breaks against the intended prose.
        Preserve deliberate examples and line breaks; repair accidental ones.
        """
        with self._workspace.lock:
            return inspect_layout(self._workspace.load(presentation))

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(_HANDLE_SCHEMA)
    def create_presentation(self, filename: str) -> PresentationHandle:
        """Create a presentation with a 13.333 by 7.5 inch slide canvas.

        Element x, y, width and height use inches; font_size uses points.
        """
        return cast(
            'PresentationHandle',
            self._workspace.create(filename, {'compositions': {}, 'slides': []}),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(_REFERENCE_SCHEMA)
    def compose_artifact(
        self,
        presentation: PresentationHandle,
        composition_id: str,
        content: PresentationCompositionContent,
    ) -> PresentationCompositionReference:
        if not composition_id.strip():
            raise ValueError('composition_id must be a non-empty string')
        validated = _CONTENT.validate_python(content)
        self._validate_content(validated)
        with self._workspace.lock:
            manifest = self._workspace.load(presentation)
            if validated['kind'] == 'image':
                image_bytes(manifest, cast('ImageReference', validated.get('image')))
            cast('dict[str, object]', manifest['compositions'])[composition_id] = validated
            self._workspace.write(presentation['presentation_id'], manifest)
        return {
            'presentation_id': presentation['presentation_id'],
            'composition_id': composition_id,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def put_slide(
        self,
        presentation: PresentationHandle,
        slide_id: str,
        position: PresentationPosition,
        *,
        layout: Literal['blank'] = 'blank',
    ) -> dict[str, object]:
        """Create or move a blank slide; position its content with put_element.

        Slides have no automatic title or content placeholders. Choose explicit
        element positions and typography, then inspect_layout before rendering.
        """
        if not slide_id.strip() or layout != 'blank':
            raise ValueError("slide_id must be non-empty and layout must be 'blank'")
        validated_position = _POSITION.validate_python(position)
        with self._workspace.lock:
            manifest = self._workspace.load(presentation)
            slides = cast('list[dict[str, object]]', manifest['slides'])
            existing = next(
                (index for index, slide in enumerate(slides) if slide['slide_id'] == slide_id),
                None,
            )
            created = existing is None
            elements: list[dict[str, object]] = []
            if existing is not None:
                elements = cast('list[dict[str, object]]', slides[existing]['elements'])
                slides.pop(existing)
            slides.insert(
                self._position_index(slides, validated_position, 'slide_id'),
                {
                    'slide_id': slide_id,
                    'layout': layout,
                    'position': validated_position,
                    'elements': elements,
                },
            )
            self._workspace.write(presentation['presentation_id'], manifest)
        return {'presentation': presentation, 'slide_id': slide_id, 'created': created}

    @requires_composition(
        'element',
        reference_key='composition',
        upstream_tool='PRESENTATIONS_compose_artifact',
        document_arg='presentation',
    )
    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def put_element(
        self,
        presentation: PresentationHandle,
        slide_id: str,
        element_id: str,
        element: PresentationElement,
        position: PresentationPosition | None = None,
    ) -> dict[str, object]:
        """Place or update one composed element using geometry in inches.

        Keep x + width <= 13.333 and y + height <= 7.5. For example a title
        can use x=0.7, y=0.5, width=11.9, height=0.8, font_size=30 points.
        Inspect the complete presentation layout before rendering.
        """
        if not element_id.strip():
            raise ValueError('element_id must be a non-empty string')
        validated = _ELEMENT.validate_python(element)
        self._validate_element(validated)
        validated_position = _POSITION.validate_python(position or {'anchor': 'end'})
        with self._workspace.lock:
            manifest = self._workspace.load(presentation)
            self._validate_element_content(manifest, validated)
            slide = self._slide(manifest, slide_id)
            elements = cast('list[dict[str, object]]', slide['elements'])
            existing = next(
                (index for index, item in enumerate(elements) if item['element_id'] == element_id),
                None,
            )
            created = existing is None
            if existing is not None:
                if elements[existing]['position'] == validated_position:
                    elements[existing] = {
                        'element_id': element_id,
                        'element': validated,
                        'position': validated_position,
                    }
                    self._workspace.write(presentation['presentation_id'], manifest)
                    return {
                        'presentation': presentation,
                        'slide_id': slide_id,
                        'element_id': element_id,
                        'created': False,
                    }
                elements.pop(existing)
            elements.insert(
                self._position_index(elements, validated_position, 'element_id'),
                {
                    'element_id': element_id,
                    'element': validated,
                    'position': validated_position,
                },
            )
            self._workspace.write(presentation['presentation_id'], manifest)
        return {
            'presentation': presentation,
            'slide_id': slide_id,
            'element_id': element_id,
            'created': created,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def remove_element(
        self, presentation: PresentationHandle, slide_id: str, element_id: str
    ) -> dict[str, object]:
        with self._workspace.lock:
            manifest = self._workspace.load(presentation)
            slide = self._slide(manifest, slide_id)
            elements = cast('list[dict[str, object]]', slide['elements'])
            retained = [item for item in elements if item['element_id'] != element_id]
            removed = len(retained) != len(elements)
            slide['elements'] = retained
            if removed:
                self._workspace.write(presentation['presentation_id'], manifest)
        return {
            'presentation': presentation,
            'slide_id': slide_id,
            'element_id': element_id,
            'removed': removed,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(_STATE_SCHEMA)
    def read_presentation(self, presentation: PresentationHandle) -> PresentationState:
        with self._workspace.lock:
            manifest = self._workspace.load(presentation)
        compositions = cast('dict[str, PresentationCompositionContent]', manifest['compositions'])
        states: list[PresentationCompositionState] = [
            {'composition_id': key, 'content': value} for key, value in sorted(compositions.items())
        ]
        return {
            'presentation': presentation,
            'compositions': states,
            'slides': cast('list[dict[str, object]]', manifest['slides']),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(_GENERATED_SCHEMA)
    def render_presentation(
        self,
        presentation: PresentationHandle,
        *,
        overwrite: bool = False,
        include_bytes: bool = False,
    ) -> GeneratedFile:
        with self._workspace.lock:
            manifest = self._workspace.load(presentation)
            if not cast('list[object]', manifest['slides']):
                raise ValueError('presentation must contain at least one slide')
            for slide in cast('list[dict[str, object]]', manifest['slides']):
                for item in cast('list[dict[str, object]]', slide['elements']):
                    self._validate_element_content(
                        manifest, cast('PresentationElement', item['element'])
                    )
            raw = render_pptx_bytes(manifest)
            target = self._workspace.write_output(
                str(manifest['filename']), raw, overwrite=overwrite
            )
            source_revision = snapshot_source(self._workspace.workspace_dir, manifest, raw)
            target = immutable_render_path(
                self._workspace.workspace_dir, source_revision, target.name, raw
            )
        return GeneratedFile(
            kind='generated_file',
            artifact_kind='presentation',
            filename=str(manifest['filename']),
            path=str(target),
            mime_type=_PPTX_MIME,
            size_bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            custody=source_custody(manifest),
            expected_base=expected_base(manifest),
            private_expected_base=expected_private_base(manifest),
            workspace={
                'source_revision': source_revision,
                'presentation_id': presentation['presentation_id'],
                'filename': presentation['filename'],
            },
            content_base64=base64.b64encode(raw).decode('ascii') if include_bytes else None,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(_GENERATED_SCHEMA)
    def create_pptx(
        self,
        filename: str,
        document: OneShotPresentation,
        *,
        overwrite: bool = False,
        include_bytes: bool = False,
    ) -> GeneratedFile:
        validated = _ONE_SHOT.validate_python(document)
        target = self._workspace.safe_output_path(filename)
        if target.exists() and not overwrite:
            raise FileExistsError(str(target))
        presentation = self.create_presentation(filename)
        try:
            for slide in validated['slides']:
                self.put_slide(
                    presentation,
                    slide['slide_id'],
                    {'anchor': 'end'},
                    layout=slide.get('layout', 'blank'),
                )
                for source in slide['elements']:
                    reference = self.compose_artifact(
                        presentation,
                        f'{slide["slide_id"]}-{source["element_id"]}-content',
                        source['content'],
                    )
                    element = cast(
                        'PresentationElement',
                        {
                            key: value
                            for key, value in source.items()
                            if key not in {'element_id', 'content'}
                        }
                        | {'composition': reference},
                    )
                    self.put_element(
                        presentation,
                        slide['slide_id'],
                        source['element_id'],
                        element,
                    )
            return self.render_presentation(
                presentation, overwrite=overwrite, include_bytes=include_bytes
            )
        except Exception:
            self._workspace.discard(presentation)
            raise

    def validate_composition_reference(
        self,
        doc: object,
        reference: object,
        argument_name: str,
    ) -> None:
        required = 'PRESENTATIONS_compose_artifact'
        if not isinstance(doc, Mapping) or not isinstance(reference, Mapping):
            raise CompositionDependencyError(
                f"argument '{argument_name}' requires a reference returned by {required}"
            )
        doc_map = cast('Mapping[object, object]', doc)
        ref_map = cast('Mapping[object, object]', reference)
        composition_id = ref_map.get('composition_id')
        if ref_map.get('presentation_id') != doc_map.get('presentation_id') or not isinstance(
            composition_id, str
        ):
            raise CompositionDependencyError(
                f"argument '{argument_name}' requires a reference returned by {required}"
            )
        manifest = self._workspace.load(cast('PresentationHandle', doc))
        if composition_id not in cast('dict[str, object]', manifest['compositions']):
            raise CompositionDependencyError(
                f"argument '{argument_name}' references unknown composition '{composition_id}'; "
                f'call {required} first'
            )

    @staticmethod
    def _validate_content(content: PresentationCompositionContent) -> None:
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
                raise ValueError('table compositions must be non-empty and rectangular')
        if content['kind'] == 'chart':
            categories = content.get('categories')
            series = content.get('series')
            if (
                not categories
                or not series
                or any(len(item['values']) != len(categories) for item in series)
            ):
                raise ValueError('chart compositions require aligned categories and series')

    @staticmethod
    def _validate_element(element: PresentationElement) -> None:
        if any(not math.isfinite(element[key]) for key in ('x', 'y', 'width', 'height')):
            raise ValueError('element geometry must be finite')
        size = element.get('font_size', 20)
        if not math.isfinite(size) or not 6 <= size <= 96:
            raise ValueError('font_size must be finite and between 6 and 96 points')
        family = element.get('font_family', 'Aptos')
        if not family.strip() or len(family) > 100 or any(ord(c) < 32 for c in family):
            raise ValueError('font_family must contain 1 to 100 printable characters')
        if any(element[key] < 0 for key in ('x', 'y', 'width', 'height')):
            raise ValueError('element geometry cannot be negative')
        if element['width'] <= 0 or element['height'] <= 0:
            raise ValueError('element width and height must be positive')
        if element['x'] + element['width'] > 13.333 or element['y'] + element['height'] > 7.5:
            raise ValueError(
                'element geometry must remain within the slide canvas: use inches on a '
                '13.333 by 7.5 inch slide; x + width <= 13.333 and y + height <= 7.5'
            )

    @staticmethod
    def _validate_element_content(
        manifest: dict[str, object], element: PresentationElement
    ) -> None:
        content = cast('dict[str, PresentationCompositionContent]', manifest['compositions'])[
            element['composition']['composition_id']
        ]
        expected = {
            'title': 'text',
            'text': 'text',
            'list': 'list',
            'table': 'table',
            'chart': 'chart',
            'image': 'image',
        }[element['type']]
        if content['kind'] != expected:
            raise ValueError(f"element type '{element['type']}' requires {expected} content")

    @staticmethod
    def _slide(manifest: dict[str, object], slide_id: str) -> dict[str, object]:
        for slide in cast('list[dict[str, object]]', manifest['slides']):
            if slide['slide_id'] == slide_id:
                return slide
        raise ValueError(f"unknown slide_id '{slide_id}'")

    @staticmethod
    def _position_index(
        entries: list[dict[str, object]],
        position: PresentationPosition,
        id_field: str,
    ) -> int:
        if position['anchor'] == 'start':
            return 0
        if position['anchor'] == 'end':
            return len(entries)
        anchor_id = position.get('item_id')
        if not anchor_id:
            raise ValueError(f"position anchor '{position['anchor']}' requires item_id")
        for index, entry in enumerate(entries):
            if entry[id_field] == anchor_id:
                return index if position['anchor'] == 'before' else index + 1
        raise ValueError(f"position references unknown item_id '{anchor_id}'")
