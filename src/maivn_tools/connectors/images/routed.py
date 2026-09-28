"""Optional adapter to the installed Brain image router, without a core dependency."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

from maivn_contracts.artifacts import ImageGenerationIntentV1
from .models import ImageProviderBatch, ImageProviderInputs

if TYPE_CHECKING:
    from collections.abc import Mapping


class _Model(Protocol):
    def model_validate(self, value: object) -> object: ...


class _Dumpable(Protocol):
    def model_dump(self, *, mode: str) -> dict[str, object]: ...


class _Generate(Protocol):
    async def __call__(
        self, catalog: object, intent: object, inputs: object, providers: Mapping[str, object]
    ) -> _Dumpable: ...


class RoutedImageGenerator:
    """Reuse configured Brain routing and safety-aware fallback on the SDK host.

    Install maivn-brain separately and pass its trusted catalog snapshot and
    configured provider adapters. No provider/model identifiers become tool arguments.
    """

    def __init__(self, *, catalog: object, providers: Mapping[str, object]) -> None:
        module = import_module('maivn_brain.models.image_generation')
        self._intent = cast('_Model', module.ImageGenerationIntent)
        self._inputs = cast('_Model', module.ImageGenerationInputs)
        self._generate = cast('_Generate', module.generate_routed_images)
        self._catalog = catalog
        self._providers = dict(providers)

    async def generate(
        self, intent: ImageGenerationIntentV1, inputs: ImageProviderInputs
    ) -> ImageProviderBatch:
        """Preserve the production router's retryable/fatal/safety failure decisions."""
        prompt = [intent.prompt, f'Visual style: {intent.style}.']
        if intent.negative_prompt:
            prompt.append(f'Avoid: {intent.negative_prompt}')
        routed_intent = self._intent.model_validate(
            {
                'prompt': '\n'.join(prompt),
                'operation': intent.operation,
                'image_count': intent.image_count,
                'width_pixels': intent.width_pixels,
                'height_pixels': intent.height_pixels,
                'aspect_ratio': None if intent.aspect_ratio == 'custom' else intent.aspect_ratio,
                'transparency': intent.transparency,
                'quality': 'professional' if intent.quality == 'high' else 'balanced',
                'safety_policy': intent.safety_policy,
            }
        )
        batch = await self._generate(
            self._catalog,
            routed_intent,
            self._inputs.model_validate(inputs.model_dump(mode='python')),
            self._providers,
        )
        return ImageProviderBatch.model_validate(batch.model_dump(mode='python'))
