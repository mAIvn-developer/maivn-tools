"""Microsoft Word document connector via Microsoft Graph.

Word does not expose a structured "edit-paragraph" API like Excel; this
toolset covers the surface that does exist: metadata, content download,
format conversion, and small-file upload of new ``.docx`` content.
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


def _extract_word_item_id(candidate: Any) -> str:
    """Pull a Word/Graph drive item id out of a raw string or dict."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("item_id must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        mapping = cast("dict[str, Any]", candidate)
        for key in ("item_id", "file_id", "id"):
            value = mapping.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("dict candidate has no Word/Graph item id")
    raise ValueError("item_id must be a string or an item dict")


# MARK: ToolSet


@toolset(prefix="word")
class MicrosoftWordToolSet:
    """A connector for Word documents stored on OneDrive / SharePoint.

    Use this for content-level operations on existing ``.docx`` files. To
    find a doc by name first, use :class:`MicrosoftFilesToolSet`
    (``search_files``) and pass the returned dict here — most tools
    accept either a raw item ID or a Graph item dict.
    """

    metadata = ProviderMetadata(
        name="microsoft_word",
        display_name="Microsoft Word",
        version="0.1.0",
        description="Read, convert, and replace Word documents via Microsoft Graph.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "Files.Read": "Read user files.",
            "Files.ReadWrite": "Read and write user files.",
        },
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://learn.microsoft.com/en-us/graph/api/driveitem-get-content",
        homepage_url="https://www.microsoft.com/microsoft-365/word",
        tags=("document", "microsoft"),
    )

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
        """Return document metadata.

        Accepts a raw item id or a Graph item dict.
        """
        item_id = _extract_word_item_id(item_id)
        return self._client.get(f"/{self._drive_root}/items/{item_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def download_content(self, item_id: Any) -> dict[str, Any]:
        """Download the raw ``.docx`` bytes.

        Accepts a raw item id or a Graph item dict. Returns
        ``{"item_id": ..., "status": ..., "body": <bytes>}``.
        """
        item_id = _extract_word_item_id(item_id)
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
        """Download the document converted to ``format`` (e.g. ``"pdf"``, ``"html"``).

        Valid ``format`` values are ``"pdf"``, ``"html"``, and ``"jpg"``. When
        ``format`` is ``"jpg"``, ``width`` and ``height`` (desired pixel
        dimensions) are required.

        Accepts a raw item id or a Graph item dict.
        """
        item_id = _extract_word_item_id(item_id)
        if format not in {"pdf", "html", "jpg"}:
            raise ValueError("format must be pdf/html/jpg")
        params: dict[str, Any] = {"format": format}
        if format == "jpg":
            if width is None or height is None:
                raise ValueError("width and height are required when format=jpg")
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

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def replace_content(
        self,
        item_id: Any,
        *,
        content_bytes: bytes,
    ) -> dict[str, Any]:
        """Overwrite the document content (small-file upload).

        Accepts a raw item id or a Graph item dict. Supports files up to
        250 MB in a single call; for larger files use
        ``MicrosoftFilesToolSet.create_upload_session``.
        """
        item_id = _extract_word_item_id(item_id)
        if not content_bytes:
            raise ValueError("content_bytes must be non-empty")
        return self._client.put(
            f"/{self._drive_root}/items/{item_id}/content",
            data=content_bytes,
            headers={
                "Content-Type": (
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upload_new(
        self,
        *,
        path: str,
        content_bytes: bytes,
    ) -> dict[str, Any]:
        """Upload a new ``.docx`` to a path (small-file upload).

        ``path`` is a forward-slash path under the drive root. Supports files
        up to 250 MB in a single call; for larger files use
        ``MicrosoftFilesToolSet.create_upload_session``. Returns the new Graph
        driveItem resource.
        """
        if not path:
            raise ValueError("path must be a non-empty string")
        if not content_bytes:
            raise ValueError("content_bytes must be non-empty")
        return self._client.put(
            f"/{self._drive_root}/root:/{path}:/content",
            data=content_bytes,
            headers={
                "Content-Type": (
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
            },
        ).json()
