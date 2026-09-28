"""SDK-host image generation/editing with immutable files and portable exact sources."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, NoReturn, cast
from uuid import uuid4

from PIL import Image, ImageOps
from maivn import tool_output, toolify, toolset
from maivn.artifact_images import resolve_artifact_image
from maivn_contracts.artifacts import (
    GeneratedFile,
    GeneratedFiles,
    ImageGenerationIntentV1,
    OrdinaryArtifactRef,
    PrivateArtifactRef,
)

from ..artifacts.revisions import (
    bind_private_receipt,
    bind_receipt,
    expected_base,
    expected_private_base,
    export_source,
    immutable_render_path,
    import_source,
    resume_private_source,
    resume_source,
    snapshot_source,
    source_custody,
)
from ..artifacts.workspace import ManifestWorkspace
from ...core.permissions import PermissionFlag, PermissionSet
from .models import (
    ImageGenerator,
    ImageHandle,
    ImageProviderBatch,
    ImageProviderInputs,
    ImageProviderOutput,
)

_MAX_PIXELS = 16_000_000
_MAX_BYTES = 8 * 1024 * 1024


class LocalImageGenerationError(RuntimeError):
    """Value-free generation failure safe for local tool outcomes."""

    def __init__(self) -> None:
        super().__init__('Image generation or editing could not be completed.')


@toolset(prefix='images', metadata={'serialize_calls': True})
class ImagesToolSet:
    """Generate images locally; the SDK publishes exact outputs through selected custody."""

    def __init__(
        self,
        output_dir: str | os.PathLike[str],
        *,
        generator: ImageGenerator,
        custody: Literal['ordinary', 'vault_private'] = 'vault_private',
        provider_timeout_seconds: float = 300.0,
    ) -> None:
        if custody not in {'ordinary', 'vault_private'}:
            raise ValueError('unsupported image custody')
        if not math.isfinite(provider_timeout_seconds) or provider_timeout_seconds <= 0:
            raise ValueError('provider_timeout_seconds must be positive finite seconds')
        self._workspace = ManifestWorkspace(
            output_dir, workspace_name='images', id_field='image_id', extension='.png'
        )
        self._generator = generator
        self._timeout_seconds = provider_timeout_seconds
        self._custody = custody
        self.connection = None

    def authorized_generated_file_roots(self) -> tuple[Path, ...]:
        return (self._workspace.output_dir,)

    def sdk_private_workspace(self, arguments: Mapping[str, object]) -> bool:
        image = arguments.get('image')
        if not isinstance(image, Mapping):
            return self._custody == 'vault_private'
        with self._workspace.lock:
            return (
                source_custody(self._workspace.load(cast('Mapping[str, object]', image)))
                == 'vault_private'
            )

    def export_generated_file_source(self, generated: GeneratedFile) -> bytes:
        return export_source(self._workspace.workspace_dir, 'images', generated)

    def bind_generated_file_receipt(
        self, generated: GeneratedFile, artifact: OrdinaryArtifactRef
    ) -> None:
        bind_receipt(self._workspace.workspace_dir, 'image_id', generated, artifact)

    def bind_private_generated_file_receipt(
        self, generated: GeneratedFile, artifact: PrivateArtifactRef
    ) -> None:
        bind_private_receipt(self._workspace.workspace_dir, 'image_id', generated, artifact)

    def resume_artifact(self, artifact: OrdinaryArtifactRef, *, source: bytes) -> ImageHandle:
        if artifact.kind != 'image':
            raise LocalImageGenerationError
        import_source(self._workspace.workspace_dir, 'images', artifact, source)
        return cast(
            'ImageHandle', resume_source(self._workspace.workspace_dir, 'image_id', artifact)
        )

    def resume_private_artifact(
        self, artifact: PrivateArtifactRef, *, source: bytes
    ) -> ImageHandle:
        if artifact.kind != 'image':
            raise LocalImageGenerationError
        return cast(
            'ImageHandle',
            resume_private_source(
                self._workspace.workspace_dir, 'images', 'image_id', artifact, source
            ),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(GeneratedFiles.model_json_schema())
    async def generate_images(
        self,
        prompt: str,
        *,
        width_pixels: int = 1024,
        height_pixels: int = 1024,
        image_count: int = 1,
        quality: Literal['standard', 'high'] = 'standard',
    ) -> GeneratedFiles:
        """Generate one to four images; private custody is configured by the application."""
        intent = _intent(
            prompt, width_pixels, height_pixels, image_count, quality, operation='generate'
        )
        return await self._generate(intent, ImageProviderInputs(), base=None)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(GeneratedFile.model_json_schema())
    async def edit_image(
        self,
        artifact_id: str,
        prompt: str,
        *,
        width_pixels: int = 1024,
        height_pixels: int = 1024,
        quality: Literal['standard', 'high'] = 'standard',
    ) -> GeneratedFile:
        """Edit an exact attached image; filenames, URLs and inline bytes are not selectors."""
        resolved = await resolve_artifact_image(artifact_id)
        intent = _intent(prompt, width_pixels, height_pixels, 1, quality, operation='edit')
        inputs = ImageProviderInputs(
            references=(
                ImageProviderOutput.model_validate(
                    {'image_bytes': resolved.content, 'declared_mime': resolved.mime_type}
                ),
            )
        )
        return (await self._generate(intent, inputs, base=resolved.artifact_ref)).files[0]

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    @tool_output(GeneratedFile.model_json_schema())
    async def edit_source(
        self, image: ImageHandle, prompt: str, *, quality: Literal['standard', 'high'] = 'standard'
    ) -> GeneratedFile:
        """Edit an exact source restored by the caller without exposing its private intent."""
        with self._workspace.lock:
            source = self._workspace.load(image)
            base = expected_private_base(source) or expected_base(source)
            original = cast('str', source['image_bytes_base64'])
            prior_intent = ImageGenerationIntentV1.model_validate(source['intent'])
        if base is None:
            raise LocalImageGenerationError
        raw = base64.b64decode(original, validate=True)
        if hashlib.sha256(raw).hexdigest() != source.get('image_sha256') or (
            isinstance(base, OrdinaryArtifactRef) and hashlib.sha256(raw).hexdigest() != base.sha256
        ):
            raise LocalImageGenerationError
        inputs = ImageProviderInputs(
            references=(
                ImageProviderOutput.model_validate(
                    {'image_bytes': raw, 'declared_mime': base.mime_type}
                ),
            )
        )
        intent = _intent(
            prompt,
            prior_intent.width_pixels,
            prior_intent.height_pixels,
            1,
            quality,
            operation='edit',
        )
        return (await self._generate(intent, inputs, base=base)).files[0]

    async def _generate(
        self,
        intent: ImageGenerationIntentV1,
        inputs: ImageProviderInputs,
        *,
        base: OrdinaryArtifactRef | PrivateArtifactRef | None,
    ) -> GeneratedFiles:
        if base is not None and (
            base.kind != 'image' or base.mime_type not in {'image/png', 'image/jpeg'}
        ):
            raise LocalImageGenerationError
        private = isinstance(base, PrivateArtifactRef) or self._custody == 'vault_private'
        if (
            private and isinstance(base, OrdinaryArtifactRef)
        ) or intent.width_pixels * intent.height_pixels > _MAX_PIXELS:
            raise LocalImageGenerationError
        try:
            async with asyncio.timeout(self._timeout_seconds):
                batch = ImageProviderBatch.model_validate(
                    await self._generator.generate(intent, inputs)
                )
            if len(batch.images) != intent.image_count:
                _refuse()
            files: list[GeneratedFile] = []
            for generated in batch.images:
                mime = base.mime_type if base is not None else 'image/png'
                raw = _normalize(generated, mime, intent.width_pixels, intent.height_pixels)
                filename = (
                    base.display_filename
                    if isinstance(base, OrdinaryArtifactRef)
                    else f'image-{uuid4().hex[:12]}.{"jpg" if mime == "image/jpeg" else "png"}'
                )
                workspace = ManifestWorkspace(
                    self._workspace.output_dir,
                    workspace_name='images',
                    id_field='image_id',
                    extension=Path(filename).suffix,
                )
                with workspace.lock:
                    handle = workspace.create(
                        filename,
                        {
                            'source_custody': 'vault_private' if private else 'ordinary',
                            'intent': intent.model_dump(mode='json'),
                            'input_images': [
                                {
                                    'content_base64': base64.b64encode(item.image_bytes).decode(
                                        'ascii'
                                    ),
                                    'mime_type': item.declared_mime,
                                }
                                for item in inputs.references
                            ],
                            'image_bytes_base64': base64.b64encode(raw).decode('ascii'),
                            'image_sha256': hashlib.sha256(raw).hexdigest(),
                            'published_artifact': base.model_dump(mode='json')
                            if isinstance(base, OrdinaryArtifactRef)
                            else None,
                            'published_private_artifact': base.model_dump(mode='json')
                            if isinstance(base, PrivateArtifactRef)
                            else None,
                        },
                    )
                    manifest = workspace.load(handle)
                    token = snapshot_source(workspace.workspace_dir, manifest, raw)
                    target = immutable_render_path(workspace.workspace_dir, token, filename, raw)
                file = GeneratedFile(
                    kind='generated_file',
                    artifact_kind='image',
                    filename=filename,
                    path=str(target),
                    mime_type=mime,
                    size_bytes=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest(),
                    custody='vault_private' if private else 'ordinary',
                    expected_base=base if isinstance(base, OrdinaryArtifactRef) else None,
                    private_expected_base=base if isinstance(base, PrivateArtifactRef) else None,
                    workspace={**handle, 'source_revision': token},
                )
                # Bound the actual package before returning any output to SDK intake.
                self.export_generated_file_source(file)
                files.append(file)
            return GeneratedFiles(kind='generated_files', files=tuple(files))
        except Exception:
            raise LocalImageGenerationError from None


def _intent(
    prompt: str,
    width: int,
    height: int,
    count: int,
    quality: Literal['standard', 'high'],
    *,
    operation: Literal['generate', 'edit'],
) -> ImageGenerationIntentV1:
    return ImageGenerationIntentV1(
        intent_version='v1',
        operation=operation,
        prompt=prompt,
        negative_prompt=None,
        aspect_ratio='custom',
        width_pixels=width,
        height_pixels=height,
        image_count=count,
        quality=quality,
        style='natural',
        transparency=False,
        reference_input_local_ids=(),
        edit_source_local_id='source' if operation == 'edit' else None,
        edit_mask_local_id=None,
        safety_policy='standard',
    )


def _normalize(generated: ImageProviderOutput, mime_type: str, width: int, height: int) -> bytes:
    if len(generated.image_bytes) > _MAX_BYTES:
        raise LocalImageGenerationError
    with Image.open(io.BytesIO(generated.image_bytes)) as image:
        if (
            image.format
            != {'image/png': 'PNG', 'image/jpeg': 'JPEG', 'image/webp': 'WEBP'}[
                generated.declared_mime
            ]
            or image.width * image.height > _MAX_PIXELS
            or max(image.size) > 8192
            or getattr(image, 'n_frames', 1) != 1
        ):
            raise LocalImageGenerationError
        image.load()
        normalized = ImageOps.exif_transpose(image).convert(
            'RGB' if mime_type == 'image/jpeg' else 'RGBA'
        )
        if normalized.size != (width, height):
            normalized = normalized.resize((width, height), Image.Resampling.LANCZOS)  # pyright: ignore[reportUnknownMemberType] - Pillow size overload includes an untyped ndarray.
        normalized.info.clear()
        output = io.BytesIO()
        normalized.save(output, format='JPEG' if mime_type == 'image/jpeg' else 'PNG')
    raw = output.getvalue()
    if len(raw) > _MAX_BYTES:
        raise LocalImageGenerationError
    return raw


def _refuse() -> NoReturn:
    raise LocalImageGenerationError
