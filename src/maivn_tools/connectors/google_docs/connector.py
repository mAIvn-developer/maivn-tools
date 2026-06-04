"""Google Docs API v1 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from ..google_workspace._shared import TokenSource, make_bearer_auth


def _extract_doc_id(candidate: Any) -> str:
    """Pull a Google Docs ``documentId`` out of a raw string or doc dict.

    Also accepts a Drive search-result dict that uses ``file_id`` — Google
    Docs share their ``documentId`` with the Drive ``fileId``.
    """
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("document_id must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        doc: dict[str, Any] = cast("dict[str, Any]", candidate)
        for key in ("doc_id", "document_id", "documentId", "file_id", "id"):
            value: Any = doc.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("dict candidate has no document id")
    raise ValueError("document_id must be a string or a document dict")


@toolset(prefix="google_docs")
class GoogleDocsToolSet:
    """A connector for the Google Docs API v1.

    Use this for content-level operations on existing Google Docs. To
    find a doc by name first, use :class:`GoogleDriveToolSet` (``search_files``)
    and pass the returned ``file_ref`` / file dict in here — most tools
    accept either a raw ID or a doc dict.
    """

    metadata = ProviderMetadata(
        name="google_docs",
        display_name="Google Docs",
        version="0.1.0",
        description="Create, read, and edit Google Docs documents.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "https://www.googleapis.com/auth/documents": "Full Docs access.",
            "https://www.googleapis.com/auth/documents.readonly": "Read-only Docs access.",
        },
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developers.google.com/docs/api/reference/rest",
        homepage_url="https://docs.google.com/",
        tags=("docs", "google-workspace"),
    )

    def __init__(
        self,
        *,
        token: TokenSource,
        base_url: str = "https://docs.googleapis.com",
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
    def get_document(self, document_id: Any) -> dict[str, Any]:
        """Return a Google Doc by ID.

        Accepts a raw document ID or a file dict from
        ``GoogleDriveToolSet.search_files(include_ids=True)``. Returns the
        full document resource with ``title``, ``body``, ``documentStyle``,
        and ``revisionId``.
        """
        document_id = _extract_doc_id(document_id)
        return self._client.get(f"/v1/documents/{document_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_document(self, title: str) -> dict[str, Any]:
        """Create a blank Google Doc.

        Returns the new document resource — pass ``documentId`` to
        ``insert_text`` / ``replace_text`` / ``batch_update`` to populate
        it.
        """
        if not title:
            raise ValueError("title must be a non-empty string")
        return self._client.post("/v1/documents", json={"title": title}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def batch_update(
        self,
        document_id: Any,
        requests: list[dict[str, Any]],
        *,
        write_control: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply one or more update requests (insert text, format, etc.).

        Accepts a raw document ID or a document dict. ``requests`` follows
        the Docs API ``batchUpdate`` schema — use ``insert_text`` /
        ``replace_text`` / ``delete_content_range`` for the common cases.
        """
        document_id = _extract_doc_id(document_id)
        if not requests:
            raise ValueError("requests must be non-empty")
        body: dict[str, Any] = {"requests": requests}
        if write_control is not None:
            body["writeControl"] = write_control
        return self._client.post(
            f"/v1/documents/{document_id}:batchUpdate",
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def insert_text(
        self,
        document_id: Any,
        *,
        text: str,
        index: int = 1,
    ) -> dict[str, Any]:
        """Insert text at ``index`` (1-based, before the trailing newline).

        Accepts a raw document ID or a document dict. Use ``index=1`` to
        insert at the start of the body.
        """
        if not text:
            raise ValueError("text must be a non-empty string")
        return self.batch_update(
            document_id,
            [{"insertText": {"location": {"index": index}, "text": text}}],
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def replace_text(
        self,
        document_id: Any,
        *,
        find: str,
        replace: str,
        match_case: bool = False,
    ) -> dict[str, Any]:
        """Find and replace text throughout a document.

        Accepts a raw document ID or a document dict.
        """
        if not find:
            raise ValueError("find must be a non-empty string")
        return self.batch_update(
            document_id,
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
    def delete_content_range(
        self,
        document_id: Any,
        *,
        start_index: int,
        end_index: int,
    ) -> dict[str, Any]:
        """Delete a content range. Destructive — confirm with the user.

        Accepts a raw document ID or a document dict. ``end_index`` must be
        strictly greater than ``start_index``.
        """
        if end_index <= start_index:
            raise ValueError("end_index must be greater than start_index")
        return self.batch_update(
            document_id,
            [
                {
                    "deleteContentRange": {
                        "range": {
                            "startIndex": start_index,
                            "endIndex": end_index,
                        }
                    }
                }
            ],
        )
