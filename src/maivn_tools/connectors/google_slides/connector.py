# pyright: strict
"""Google Slides API v1 connector."""

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from ..google_workspace._shared import TokenSource, make_bearer_auth

# MARK: Helpers


def _extract_pres_id(candidate: Any) -> str:
    """Pull a Google Slides ``presentationId`` out of a raw string or dict."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("presentation_id must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        mapping = cast("dict[str, object]", candidate)
        for key in ("presentation_id", "presentationId", "file_id", "id"):
            value = mapping.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("dict candidate has no presentation id")
    raise ValueError("presentation_id must be a string or a presentation dict")


# MARK: ToolSet


@toolset(prefix="google_slides")
class GoogleSlidesToolSet:
    """A connector for the Google Slides API v1.

    Use this for slide/shape/text edits on existing presentations. To
    find a deck by name first, use :class:`GoogleDriveToolSet`
    (``search_files``) and pass the returned dict here — most tools
    accept either a raw presentation ID or a Drive file dict.
    """

    metadata = ProviderMetadata(
        name="google_slides",
        display_name="Google Slides",
        version="0.1.0",
        description="Create and edit Google Slides presentations.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "https://www.googleapis.com/auth/presentations": "Full Slides access.",
            "https://www.googleapis.com/auth/presentations.readonly": "Read-only Slides access.",
        },
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developers.google.com/slides/api/reference/rest",
        homepage_url="https://slides.google.com/",
        tags=("slides", "google-workspace"),
    )

    def __init__(
        self,
        *,
        token: TokenSource,
        base_url: str = "https://slides.googleapis.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=make_bearer_auth(token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_presentation(self, presentation_id: Any) -> dict[str, Any]:
        """Return a presentation.

        Accepts a raw presentation ID or a Drive file dict (from
        ``GoogleDriveToolSet.search_files(include_ids=True)``). Returns
        the full presentation resource: ``title``, ``slides[*]``,
        ``masters[*]``, ``layouts[*]``.
        """
        presentation_id = _extract_pres_id(presentation_id)
        return self._client.get(f"/v1/presentations/{presentation_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_page(self, presentation_id: Any, page_object_id: str) -> dict[str, Any]:
        """Return one slide/master/layout.

        Accepts a raw presentation ID or a presentation dict for
        ``presentation_id``. ``page_object_id`` is the slide's ``objectId``
        from ``get_presentation``.
        """
        presentation_id = _extract_pres_id(presentation_id)
        if not page_object_id:
            raise ValueError("page_object_id must be non-empty")
        return self._client.get(
            f"/v1/presentations/{presentation_id}/pages/{page_object_id}",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_page_thumbnail(
        self,
        presentation_id: Any,
        page_object_id: str,
        *,
        thumbnail_size: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, Any]:
        """Return a slide thumbnail URL.

        Accepts a raw presentation ID or a presentation dict.
        ``thumbnail_size`` is ``SMALL``/``MEDIUM``/``LARGE``.
        ``mime_type`` is the ``ThumbnailMimeType`` enum whose only valid
        value is ``PNG`` (the default when unspecified); pass a MIME-type
        string like ``image/png`` and the API rejects it.
        """
        presentation_id = _extract_pres_id(presentation_id)
        if not page_object_id:
            raise ValueError("page_object_id must be non-empty")
        if mime_type is not None and mime_type != "PNG":
            raise ValueError("mime_type must be 'PNG' (the only valid ThumbnailMimeType)")
        params: dict[str, Any] = {}
        if thumbnail_size is not None:
            params["thumbnailProperties.thumbnailSize"] = thumbnail_size
        if mime_type is not None:
            params["thumbnailProperties.mimeType"] = mime_type
        return self._client.get(
            f"/v1/presentations/{presentation_id}/pages/{page_object_id}/thumbnail",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_presentation(self, title: str) -> dict[str, Any]:
        """Create a blank presentation.

        Returns the new presentation resource — pass ``presentationId`` to
        ``create_slide`` / ``insert_text`` / ``batch_update`` to populate it.
        """
        if not title:
            raise ValueError("title must be a non-empty string")
        return self._client.post("/v1/presentations", json={"title": title}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def batch_update(
        self,
        presentation_id: Any,
        requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply edit requests (create slide, insert text, etc.).

        Accepts a raw presentation ID or a presentation dict. ``requests``
        follows the Slides API ``batchUpdate`` schema — prefer
        ``create_slide`` / ``insert_text`` / ``replace_all_text`` for
        common cases.
        """
        presentation_id = _extract_pres_id(presentation_id)
        if not requests:
            raise ValueError("requests must be non-empty")
        return self._client.post(
            f"/v1/presentations/{presentation_id}:batchUpdate",
            json={"requests": requests},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_slide(
        self,
        presentation_id: Any,
        *,
        insertion_index: int | None = None,
        layout: str | None = None,
        object_id: str | None = None,
    ) -> dict[str, Any]:
        """Insert a new slide.

        Accepts a raw presentation ID or a presentation dict. ``layout`` is
        a predefined layout name (``BLANK``, ``TITLE``, ``TITLE_AND_BODY``,
        etc.). If ``object_id`` is provided, it becomes the new slide's
        stable ID.
        """
        request: dict[str, Any] = {}
        if insertion_index is not None:
            request["insertionIndex"] = insertion_index
        if layout is not None:
            request["slideLayoutReference"] = {"predefinedLayout": layout}
        if object_id is not None:
            request["objectId"] = object_id
        return self.batch_update(presentation_id, [{"createSlide": request}])

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def insert_text(
        self,
        presentation_id: Any,
        *,
        object_id: str,
        text: str,
        insertion_index: int = 0,
    ) -> dict[str, Any]:
        """Insert text into a shape or table cell.

        Accepts a raw presentation ID or a presentation dict. ``object_id``
        is the shape's ``objectId`` from the presentation.
        """
        if not object_id or not text:
            raise ValueError("object_id and text must be non-empty")
        return self.batch_update(
            presentation_id,
            [
                {
                    "insertText": {
                        "objectId": object_id,
                        "text": text,
                        "insertionIndex": insertion_index,
                    }
                }
            ],
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def replace_all_text(
        self,
        presentation_id: Any,
        *,
        find: str,
        replace: str,
        match_case: bool = False,
    ) -> dict[str, Any]:
        """Replace all occurrences of ``find`` with ``replace``.

        Accepts a raw presentation ID or a presentation dict.
        """
        if not find:
            raise ValueError("find must be a non-empty string")
        return self.batch_update(
            presentation_id,
            [
                {
                    "replaceAllText": {
                        "containsText": {"text": find, "matchCase": match_case},
                        "replaceText": replace,
                    }
                }
            ],
        )

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_object(
        self,
        presentation_id: Any,
        object_id: str,
    ) -> dict[str, Any]:
        """Delete a slide, shape, or other page object. Destructive — confirm with user.

        Accepts a raw presentation ID or a presentation dict for
        ``presentation_id``.
        """
        if not object_id:
            raise ValueError("object_id must be a non-empty string")
        return self.batch_update(
            presentation_id,
            [{"deleteObject": {"objectId": object_id}}],
        )
