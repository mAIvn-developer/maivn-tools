"""Microsoft PowerPoint connector via Microsoft Graph.

PowerPoint exposes the same content / thumbnail / convert / replace
surface as Word; structured editing (slides, shapes) is not part of
Microsoft Graph.
"""

# pyright: strict
from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from ..microsoft_graph._shared import TokenSource, make_graph_client

# MARK: Helpers


def _extract_ppt_item_id(candidate: Any) -> str:
    """Pull a PowerPoint/Graph drive item id out of a raw string or dict."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("item_id must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        mapping = cast(dict[str, Any], candidate)
        for key in ("item_id", "file_id", "presentation_id", "id"):
            value = mapping.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("dict candidate has no PowerPoint/Graph item id")
    raise ValueError("item_id must be a string or an item dict")


# MARK: ToolSet


@toolset(prefix="powerpoint")
class MicrosoftPowerPointToolSet:
    """A connector for PowerPoint presentations stored on OneDrive / SharePoint.

    Use this for content-level operations on existing ``.pptx`` files. To
    find a deck by name first, use :class:`MicrosoftFilesToolSet`
    (``search_files``) and pass the returned dict here — most tools
    accept either a raw item ID or a Graph item dict.
    """

    metadata = ProviderMetadata(
        name="microsoft_powerpoint",
        display_name="Microsoft PowerPoint",
        version="0.1.0",
        description="Read, convert, and replace PowerPoint presentations via Microsoft Graph.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "Files.Read": "Read user files.",
            "Files.ReadWrite": "Read and write user files.",
        },
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://learn.microsoft.com/en-us/graph/api/driveitem-get",
        homepage_url="https://www.microsoft.com/microsoft-365/powerpoint",
        tags=("presentation", "microsoft"),
    )

    PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

    def __init__(
        self,
        *,
        token: TokenSource,
        drive_id: str | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        self.connection = connection
        self._drive_root = f"drives/{drive_id}" if drive_id else "me/drive"
        self._client: HttpClient = make_graph_client(token, transport=transport)

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_metadata(self, item_id: Any) -> dict[str, Any]:
        """Return presentation metadata.

        Accepts a raw item id or a Graph item dict.
        """
        item_id = _extract_ppt_item_id(item_id)
        return self._client.get(f"/{self._drive_root}/items/{item_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def download_content(self, item_id: Any) -> dict[str, Any]:
        """Download the raw ``.pptx`` bytes.

        Accepts a raw item id or a Graph item dict. Returns
        ``{"item_id": ..., "status": ..., "body": <bytes>}``.
        """
        item_id = _extract_ppt_item_id(item_id)
        response = self._client.get(f"/{self._drive_root}/items/{item_id}/content")
        return {"item_id": item_id, "status": response.status, "body": response.body}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def convert_to(
        self,
        item_id: Any,
        *,
        format: str = "pdf",
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        """Download the presentation converted to ``format``.

        Accepts a raw item id or a Graph item dict. ``format`` is
        ``pdf`` or ``jpg``. When ``format`` is ``jpg``, both ``width``
        and ``height`` (in pixels) are required by Microsoft Graph.
        """
        item_id = _extract_ppt_item_id(item_id)
        if format not in {"pdf", "jpg"}:
            raise ValueError("format must be 'pdf' or 'jpg'")
        params: dict[str, Any] = {"format": format}
        if format == "jpg":
            if width is None or height is None:
                raise ValueError("width and height are required when format is 'jpg'")
            params["width"] = width
            params["height"] = height
        response = self._client.get(
            f"/{self._drive_root}/items/{item_id}/content",
            params=params,
        )
        return {
            "item_id": item_id,
            "format": format,
            "status": response.status,
            "body": response.body,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_thumbnails(self, item_id: Any) -> dict[str, Any]:
        """Return the file's thumbnailSet collection (small/medium/large preview images).

        Graph returns a per-file thumbnail set, not one thumbnail per slide.
        Accepts a raw item id or a Graph item dict.
        """
        item_id = _extract_ppt_item_id(item_id)
        return self._client.get(
            f"/{self._drive_root}/items/{item_id}/thumbnails",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def replace_content(
        self,
        item_id: Any,
        *,
        content_bytes: bytes,
    ) -> dict[str, Any]:
        """Overwrite the presentation content (small-file upload).

        Accepts a raw item id or a Graph item dict. Supports files up to
        250 MB in a single call; for larger or unreliable transfers use
        ``MicrosoftFilesToolSet.create_upload_session`` (resumable upload).
        """
        item_id = _extract_ppt_item_id(item_id)
        if not content_bytes:
            raise ValueError("content_bytes must be non-empty")
        return self._client.put(
            f"/{self._drive_root}/items/{item_id}/content",
            data=content_bytes,
            headers={"Content-Type": self.PPTX_MIME},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upload_new(
        self,
        *,
        path: str,
        content_bytes: bytes,
    ) -> dict[str, Any]:
        """Upload a new ``.pptx`` to a path (small-file upload).

        ``path`` is a forward-slash path under the drive root. Supports
        files up to 250 MB in a single call; for larger or unreliable
        transfers use ``MicrosoftFilesToolSet.create_upload_session``
        (resumable upload). Returns the new Graph driveItem resource.
        """
        if not path:
            raise ValueError("path must be a non-empty string")
        if not content_bytes:
            raise ValueError("content_bytes must be non-empty")
        return self._client.put(
            f"/{self._drive_root}/root:/{path}:/content",
            data=content_bytes,
            headers={"Content-Type": self.PPTX_MIME},
        ).json()
