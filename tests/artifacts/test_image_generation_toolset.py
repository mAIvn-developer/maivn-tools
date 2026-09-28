"""SDK-local provider results retain private custody and exact editable sources."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Literal

import pytest
from maivn.artifact_images import ResolvedArtifactImage
from maivn_contracts.artifacts import ImageGenerationIntentV1, PrivateArtifactRef
from PIL import Image

from maivn_tools import ImagesToolSet
from maivn_tools.connectors.images import (
    ImageProviderBatch,
    ImageProviderInputs,
    ImageProviderOutput,
    LocalImageGenerationError,
)
from tests.artifacts.test_revision_sources import (
    _private_receipt,  # pyright: ignore[reportPrivateUsage] - exact private source fixture.
    _receipt,  # pyright: ignore[reportPrivateUsage] - exact ordinary source fixture.
)


class Provider:
    def __init__(self) -> None:
        self.calls: list[tuple[ImageGenerationIntentV1, ImageProviderInputs]] = []

    async def generate(
        self, intent: ImageGenerationIntentV1, inputs: ImageProviderInputs
    ) -> ImageProviderBatch:
        self.calls.append((intent, inputs))
        stream = io.BytesIO()
        Image.new('RGB', (256, 256), 'blue' if intent.operation == 'generate' else 'green').save(
            stream, 'PNG'
        )
        return ImageProviderBatch(
            images=tuple(
                ImageProviderOutput(image_bytes=stream.getvalue(), declared_mime='image/png')
                for _ in range(intent.image_count)
            )
        )


@pytest.mark.parametrize('custody', ['ordinary', 'vault_private'])
def test_generated_image_edit_restores_exact_source_on_fresh_host(
    tmp_path: Path, custody: Literal['ordinary', 'vault_private']
) -> None:
    provider = Provider()
    tools = ImagesToolSet(tmp_path / 'first-host', generator=provider, custody=custody)
    batch = asyncio.run(tools.generate_images('Blue square', width_pixels=256, height_pixels=256))
    first = batch.files[0]
    assert first.custody == custody
    source = tools.export_generated_file_source(first)
    receipt = _private_receipt(first) if custody == 'vault_private' else _receipt(first)
    if isinstance(receipt, PrivateArtifactRef):
        tools.bind_private_generated_file_receipt(first, receipt)
    else:
        tools.bind_generated_file_receipt(first, receipt)
    fresh = ImagesToolSet(tmp_path / 'fresh-host', generator=provider, custody=custody)
    handle = (
        fresh.resume_private_artifact(receipt, source=source)
        if isinstance(receipt, PrivateArtifactRef)
        else fresh.resume_artifact(receipt, source=source)
    )
    if custody == 'vault_private':
        assert first.filename not in json.dumps(handle)
        assert 'Blue square' not in json.dumps(handle)
        assert fresh.sdk_private_workspace({'image': handle}) is True
    second = asyncio.run(fresh.edit_source(handle, 'Make the square green'))
    assert second.private_expected_base == (receipt if custody == 'vault_private' else None)
    assert second.expected_base == (receipt if custody == 'ordinary' else None)
    assert second.custody == custody
    assert provider.calls[-1][0].operation == 'edit'
    assert provider.calls[-1][1].references[0].image_bytes == Path(first.path).read_bytes()
    assert Path(second.path).read_bytes() != Path(first.path).read_bytes()
    assert Path(first.path).read_bytes() == provider.calls[-1][1].references[0].image_bytes


def test_exact_private_image_edit_inherits_custody_in_ordinary_toolset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = Provider()
    private_tools = ImagesToolSet(tmp_path / 'private', generator=provider)
    first = asyncio.run(
        private_tools.generate_images('Blue square', width_pixels=256, height_pixels=256)
    ).files[0]
    receipt = _private_receipt(first)
    original_bytes = Path(first.path).read_bytes()

    async def resolve(artifact_id: str) -> ResolvedArtifactImage:
        assert artifact_id == receipt.artifact_id
        return ResolvedArtifactImage(
            content=original_bytes,
            artifact_ref=receipt,
            mime_type=receipt.mime_type,
            private=True,
        )

    monkeypatch.setattr('maivn_tools.connectors.images.toolset.resolve_artifact_image', resolve)
    ordinary_tools = ImagesToolSet(tmp_path / 'ordinary', generator=provider, custody='ordinary')
    edited = asyncio.run(
        ordinary_tools.edit_image(
            receipt.artifact_id, 'Green square', width_pixels=256, height_pixels=256
        )
    )
    assert edited.custody == 'vault_private'
    assert edited.private_expected_base == receipt
    assert edited.expected_base is None
    assert provider.calls[-1][1].references[0].image_bytes == Path(first.path).read_bytes()


def test_private_configuration_refuses_ordinary_revision_before_provider(tmp_path: Path) -> None:
    provider = Provider()
    ordinary = ImagesToolSet(tmp_path / 'ordinary', generator=provider, custody='ordinary')
    first = asyncio.run(
        ordinary.generate_images('Blue square', width_pixels=256, height_pixels=256)
    ).files[0]
    private = ImagesToolSet(tmp_path / 'private', generator=provider)
    handle = private.resume_artifact(
        _receipt(first), source=ordinary.export_generated_file_source(first)
    )
    with pytest.raises(LocalImageGenerationError):
        asyncio.run(private.edit_source(handle, 'Green square'))
    assert len(provider.calls) == 1


def test_malformed_provider_bytes_fail_without_publishing_output(tmp_path: Path) -> None:
    class MalformedProvider:
        async def generate(
            self, intent: ImageGenerationIntentV1, inputs: ImageProviderInputs
        ) -> ImageProviderBatch:
            return ImageProviderBatch(
                images=(
                    ImageProviderOutput(image_bytes=b'private-sentinel', declared_mime='image/png'),
                )
            )

    tools = ImagesToolSet(tmp_path, generator=MalformedProvider())
    with pytest.raises(LocalImageGenerationError) as caught:
        asyncio.run(tools.generate_images('Private request'))
    assert 'private-sentinel' not in str(caught.value)
    assert not list(tmp_path.rglob('*.png'))


def test_configured_provider_deadline_cancels_without_publishing(tmp_path: Path) -> None:
    cancelled: list[bool] = []

    class SlowProvider(Provider):
        async def generate(
            self, intent: ImageGenerationIntentV1, inputs: ImageProviderInputs
        ) -> ImageProviderBatch:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
            return await super().generate(intent, inputs)

    tools = ImagesToolSet(tmp_path, generator=SlowProvider(), provider_timeout_seconds=0.01)
    with pytest.raises(LocalImageGenerationError):
        asyncio.run(tools.generate_images('Synthetic observatory'))
    assert cancelled == [True]
    assert not list(tmp_path.rglob('*.png'))


@pytest.mark.parametrize('deadline', [0.0, -1.0, float('inf'), float('nan')])
def test_provider_deadline_requires_finite_positive_value(tmp_path: Path, deadline: float) -> None:
    with pytest.raises(ValueError, match='positive finite'):
        ImagesToolSet(tmp_path, generator=Provider(), provider_timeout_seconds=deadline)
