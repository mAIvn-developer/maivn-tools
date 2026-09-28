"""Typed caller-local provider port; encoded image values never enter tool outcomes."""

from __future__ import annotations

from typing import Literal, Protocol, TypedDict
from maivn_contracts.artifacts import ImageGenerationIntentV1
from pydantic import BaseModel, ConfigDict, Field, StrictBytes


class ImageHandle(TypedDict):
    image_id: str
    filename: str


class ImageProviderOutput(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    image_bytes: StrictBytes = Field(min_length=1, max_length=8 * 1024 * 1024, repr=False)
    declared_mime: Literal['image/png', 'image/jpeg', 'image/webp']


class ImageProviderInputs(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    references: tuple[ImageProviderOutput, ...] = Field(default=(), max_length=8)
    mask: ImageProviderOutput | None = None


class ImageProviderBatch(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    images: tuple[ImageProviderOutput, ...] = Field(min_length=1, max_length=4)


class ImageGenerator(Protocol):
    async def generate(
        self, intent: ImageGenerationIntentV1, inputs: ImageProviderInputs
    ) -> ImageProviderBatch:
        """Return local bytes or raise; provider credentials and routing are constructor-owned."""
        ...
