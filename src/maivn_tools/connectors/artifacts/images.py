"""Bounded caller-local image admission for persisted composition manifests.

Image bytes are never part of the model-facing composition reference. The caller
must admit authorized bytes locally; custody of this workspace is the caller's
responsibility, and this module is not a private artifact transport.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import math
import uuid
from typing import Literal, TypedDict, cast

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_DIMENSION = 8192


class ImageReference(TypedDict):
    asset_id: str
    alt_text: str


class ImagePlacement(TypedDict):
    width_inches: float
    height_inches: float
    alignment: Literal['left', 'center', 'right']


def _validate_alt_text(alt_text: str) -> None:
    if not alt_text.strip() or len(alt_text) > 1000 or any(ord(c) < 32 for c in alt_text):
        raise ValueError('image alt_text must contain 1 to 1000 printable characters')


def admit_image(
    manifest: dict[str, object],
    *,
    content_base64: str,
    mime_type: str,
    alt_text: str,
    custody: Literal['ordinary', 'vault_private'] = 'ordinary',
) -> ImageReference:
    """Normalize verified PNG/JPEG bytes into this existing source manifest."""
    if mime_type not in {'image/png', 'image/jpeg'}:
        raise ValueError('image MIME type must be image/png or image/jpeg')
    _validate_alt_text(alt_text)
    if len(content_base64) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise ValueError('image exceeds the 8 MiB byte limit')
    try:
        raw = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError('image requires valid base64') from exc
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError('image exceeds the 8 MiB byte limit or is empty')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            expected_format = 'PNG' if mime_type == 'image/png' else 'JPEG'
            if source.format != expected_format:
                raise ValueError('image bytes do not match the declared MIME type')
            width, height = source.size
            if max(width, height) > MAX_IMAGE_DIMENSION or width * height > MAX_IMAGE_PIXELS:
                raise ValueError('image exceeds pixel or dimension limits')
            if getattr(source, 'n_frames', 1) != 1:
                raise ValueError('image must contain exactly one frame')
            source.verify()
        with Image.open(io.BytesIO(raw)) as source:
            source.load()
            oriented = ImageOps.exif_transpose(source)
            normalized = oriented.convert('RGBA' if expected_format == 'PNG' else 'RGB')
            normalized.info.clear()
            output = io.BytesIO()
            normalized.save(output, format=expected_format)
            raw = output.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError('image data is invalid or unsafe') from exc
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError('normalized image exceeds the 8 MiB byte limit')
    digest = hashlib.sha256(raw).hexdigest()
    asset_id = f'private-image-{uuid.uuid4().hex}' if custody == 'vault_private' else digest
    if custody == 'vault_private':
        cast('dict[str, str]', manifest.setdefault('image_digests', {}))[asset_id] = digest
        manifest['source_custody'] = 'vault_private'
    assets = cast('dict[str, str]', manifest.setdefault('images', {}))
    assets[asset_id] = base64.b64encode(raw).decode('ascii')
    return {'asset_id': asset_id, 'alt_text': alt_text}


def image_bytes(manifest: dict[str, object], reference: ImageReference) -> bytes:
    """Resolve an admitted asset without accepting paths or URLs."""
    _validate_alt_text(reference['alt_text'])
    assets = cast('dict[str, str]', manifest.get('images', {}))
    encoded = assets.get(reference['asset_id'])
    if encoded is None:
        raise ValueError('unknown image asset; admit authorized bytes with compose_image first')
    if len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise ValueError('persisted image exceeds byte limit')
    raw = base64.b64decode(encoded, validate=True)
    expected_digest = cast('dict[str, str]', manifest.get('image_digests', {})).get(
        reference['asset_id'], reference['asset_id']
    )
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError('persisted image asset digest mismatch')
    return raw


def contain_size(raw: bytes, width: float, height: float) -> tuple[float, float]:
    with Image.open(io.BytesIO(raw)) as source:
        ratio = min(width / source.width, height / source.height)
        return source.width * ratio, source.height * ratio


def validate_placement(
    placement: ImagePlacement | None, *, max_width: float, max_height: float
) -> None:
    if placement is None:
        raise ValueError('image blocks require explicit image_placement')
    width, height = placement['width_inches'], placement['height_inches']
    if not math.isfinite(width) or not math.isfinite(height):
        raise ValueError('image placement dimensions must be finite')
    if not 0 < width <= max_width or not 0 < height <= max_height:
        raise ValueError(f'image placement must fit within {max_width} by {max_height} inches')
