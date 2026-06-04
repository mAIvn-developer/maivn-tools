"""Stability AI v2beta connector."""

# pyright: strict

from __future__ import annotations

import uuid
from typing import Any

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

# The v2beta stable-image endpoints return raw image bytes only when the
# caller asks for them via this Accept value; with application/json they
# return a base64 JSON envelope instead.
_IMAGE_ACCEPT = "image/*"


# MARK: Helpers


def _encode_multipart(
    fields: dict[str, str],
    files: dict[str, bytes] | None = None,
) -> tuple[bytes, str]:
    """Encode text ``fields`` and binary ``files`` as ``multipart/form-data``.

    Returns ``(body, content_type_header)`` where ``content_type_header``
    includes the generated boundary. The v2beta stable-image endpoints
    require ``multipart/form-data``; the runtime transport only forwards raw
    bytes, so the encoding is performed here. Each entry in ``files`` becomes
    a binary form part whose field name is the dict key.
    """
    boundary = f"----maivnboundary{uuid.uuid4().hex}"
    crlf = b"\r\n"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(b"--" + boundary.encode("ascii"))
        parts.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        parts.append(b"")
        parts.append(value.encode("utf-8"))
    for name, file_bytes in (files or {}).items():
        parts.append(b"--" + boundary.encode("ascii"))
        parts.append(f'Content-Disposition: form-data; name="{name}"; filename="{name}"'.encode())
        parts.append(b"Content-Type: application/octet-stream")
        parts.append(b"")
        parts.append(file_bytes)
    parts.append(b"--" + boundary.encode("ascii") + b"--")
    parts.append(b"")
    body = crlf.join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


# MARK: ToolSet


@toolset(prefix="stability")
class StabilityToolSet:
    """A connector for Stability AI v2beta REST."""

    metadata = ProviderMetadata(
        name="stability",
        display_name="Stability AI",
        version="0.1.0",
        description="Image generation, edit, upscale, control, and 3D.",
        auth_modes=(AuthMode.BEARER, AuthMode.API_KEY),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://platform.stability.ai/docs/api-reference",
        homepage_url="https://platform.stability.ai/",
        tags=("ai", "image", "media"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.stability.ai",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(api_key),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_account(self) -> dict[str, Any]:
        """Return account / credits info.

        Returns ``{"email": ..., "id": ..., "organizations": [...]}``.
        Useful for confirming the API key is valid at startup.
        """
        payload: dict[str, Any] = self._client.get("/v1/user/account").json()
        return payload

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_balance(self) -> dict[str, Any]:
        """Return account balance.

        Returns ``{"credits": float}`` — generation credits remaining on
        the account.
        """
        payload: dict[str, Any] = self._client.get("/v1/user/balance").json()
        return payload

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def generate_image(
        self,
        *,
        prompt: str,
        model: str = "core",
        aspect_ratio: str | None = None,
        negative_prompt: str | None = None,
        seed: int | None = None,
        output_format: str = "png",
    ) -> dict[str, Any]:
        """Generate an image with the v2beta stable-image API.

        Returns ``{"status": int, "body": <image bytes>}``. ``model``
        chooses the path segment (``core``, ``ultra``, ``sd3``) — pick
        ``ultra`` for highest quality, ``core`` for speed.
        """
        if not prompt:
            raise ValueError("prompt must be a non-empty string")
        if model not in {"core", "ultra", "sd3"}:
            raise ValueError("model must be core/ultra/sd3")
        fields: dict[str, str] = {"prompt": prompt, "output_format": output_format}
        if aspect_ratio is not None:
            fields["aspect_ratio"] = aspect_ratio
        if negative_prompt is not None:
            fields["negative_prompt"] = negative_prompt
        if seed is not None:
            fields["seed"] = str(seed)
        body, content_type = _encode_multipart(fields)
        response = self._client.post(
            f"/v2beta/stable-image/generate/{model}",
            data=body,
            headers={"Content-Type": content_type, "Accept": _IMAGE_ACCEPT},
        )
        return {"status": response.status, "body": response.body}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upscale(
        self,
        *,
        image_bytes: bytes,
        prompt: str | None = None,
        output_format: str = "png",
    ) -> dict[str, Any]:
        """Conservative upscale of an image.

        Returns ``{"status": int, "body": <upscaled image bytes>}``.
        """
        if not image_bytes:
            raise ValueError("image_bytes must be non-empty")
        fields: dict[str, str] = {"output_format": output_format}
        if prompt is not None:
            fields["prompt"] = prompt
        body, content_type = _encode_multipart(fields, files={"image": image_bytes})
        response = self._client.post(
            "/v2beta/stable-image/upscale/conservative",
            data=body,
            headers={"Content-Type": content_type, "Accept": _IMAGE_ACCEPT},
        )
        return {"status": response.status, "body": response.body}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def edit_inpaint(
        self,
        *,
        image_bytes: bytes,
        mask_bytes: bytes | None = None,
        prompt: str,
        output_format: str = "png",
    ) -> dict[str, Any]:
        """Inpaint (fill a masked region of) an image.

        Returns ``{"status": int, "body": <edited image bytes>}``. The
        ``prompt`` describes what should appear inside the masked area.
        """
        if not image_bytes or not prompt:
            raise ValueError("image_bytes and prompt must be non-empty")
        fields: dict[str, str] = {"prompt": prompt, "output_format": output_format}
        files: dict[str, bytes] = {"image": image_bytes}
        if mask_bytes is not None:
            files["mask"] = mask_bytes
        body, content_type = _encode_multipart(fields, files=files)
        response = self._client.post(
            "/v2beta/stable-image/edit/inpaint",
            data=body,
            headers={"Content-Type": content_type, "Accept": _IMAGE_ACCEPT},
        )
        return {"status": response.status, "body": response.body}
