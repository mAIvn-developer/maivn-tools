"""Dropbox API v2 connector (RPC-style JSON over POST)."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


def _extract_dropbox_path(candidate: Any) -> str:
    """Pull a Dropbox path out of common shapes returned by list/search.

    Dropbox uses paths as identifiers (no opaque ID). Accepts a raw path
    string, a Dropbox entry dict (``{"path_lower": ..., "path_display": ...}``),
    a summary dict (``{"path": ...}``), or a list of such (first valid wins).
    """
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("path must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        mapping = cast(dict[str, Any], candidate)
        for key in ("path", "path_lower", "path_display", "id"):
            value: Any = mapping.get(key)
            if isinstance(value, str) and value:
                return value
        # search_v2 returns matches with metadata nested
        metadata: Any = mapping.get("metadata")
        if isinstance(metadata, dict):
            try:
                return _extract_dropbox_path(metadata)
            except ValueError:
                pass
            inner: Any = cast(dict[str, Any], metadata).get("metadata")
            if isinstance(inner, dict):
                try:
                    return _extract_dropbox_path(inner)
                except ValueError:
                    pass
        raise ValueError("dict candidate has no Dropbox path")
    if isinstance(candidate, (list, tuple)):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in sequence:
            try:
                return _extract_dropbox_path(item)
            except ValueError:
                continue
        raise ValueError("no usable Dropbox path in candidate sequence")
    raise ValueError("path must be a string or a Dropbox entry dict")


def _dropbox_entry_summary(
    entry: dict[str, Any],
    *,
    index: int,
    include_ids: bool,
) -> dict[str, Any]:
    tag = entry.get(".tag") or ""
    ref_prefix = "folder" if tag == "folder" else ("file" if tag == "file" else "entry")
    summary: dict[str, Any] = {
        f"{ref_prefix}_ref": f"{ref_prefix}_{index}",
        "name": entry.get("name", ""),
        "kind": tag,
        "path": entry.get("path_display") or entry.get("path_lower") or "",
        "size": entry.get("size", 0),
        "modified_time": entry.get("server_modified", "") or entry.get("client_modified", ""),
    }
    if include_ids and entry.get("id"):
        summary["id"] = entry["id"]
        if entry.get("rev"):
            summary["rev"] = entry["rev"]
    return summary


def _summarize_dropbox_entries(
    payload: dict[str, Any],
    *,
    include_ids: bool,
    entries_key: str = "entries",
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    raw_entries: Any = payload.get(entries_key, []) or []
    if not isinstance(raw_entries, (list, tuple)):
        raw_entries = []
    raw_sequence = cast("list[Any] | tuple[Any, ...]", raw_entries)
    for index, raw in enumerate(raw_sequence, start=1):
        if not isinstance(raw, dict):
            continue
        entry = cast(dict[str, Any], raw)
        # search_v2 results wrap entries
        nested_meta: Any = entry.get("metadata")
        if "metadata" in entry and isinstance(nested_meta, dict):
            nested = cast(dict[str, Any], nested_meta)
            inner_meta: Any = nested.get("metadata")
            if "metadata" in nested and isinstance(inner_meta, dict):
                inner = cast(dict[str, Any], inner_meta)
                items.append(_dropbox_entry_summary(inner, index=index, include_ids=include_ids))
            else:
                items.append(_dropbox_entry_summary(nested, index=index, include_ids=include_ids))
        else:
            items.append(_dropbox_entry_summary(entry, index=index, include_ids=include_ids))
    out: dict[str, Any] = {"items": items}
    if payload.get("has_more"):
        out["has_more"] = payload["has_more"]
    if payload.get("cursor"):
        out["cursor"] = payload["cursor"]
    return out


@toolset(prefix="dropbox")
class DropboxToolSet:
    """A connector for the Dropbox API v2.

    Args:
        token: OAuth bearer token. Never logged.
        base_url: API root.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="dropbox",
        display_name="Dropbox",
        version="0.1.0",
        description="Manage Dropbox files, folders, sharing links, and file requests.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE, AuthMode.BEARER),
        scopes={
            "files.metadata.read": "Read file and folder metadata.",
            "files.content.read": "Download files.",
            "files.content.write": "Create and update files.",
            "sharing.write": "Manage shared links and team folders.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://www.dropbox.com/developers/documentation/http/documentation",
        homepage_url="https://www.dropbox.com/",
        tags=("storage", "files"),
    )

    def __init__(
        self,
        *,
        token: str,
        base_url: str = "https://api.dropboxapi.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not token:
            raise ValueError("token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _rpc(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Dropbox RPC endpoints accept ``Content-Type: application/json``."""
        body = payload if payload is not None else {}
        return self._client.post(path, json=body).json()

    # MARK: - Identity

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_current_account(self) -> dict[str, Any]:
        """Return information about the authenticated account.

        Returns the Dropbox account resource (``account_id``, ``name``,
        ``email``).
        """
        return self._rpc("/2/users/get_current_account")

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_space_usage(self) -> dict[str, Any]:
        """Return space-usage information.

        Returns ``{"used": <bytes>, "allocation": {...}}``.
        """
        return self._rpc("/2/users/get_space_usage")

    # MARK: - Files (list and metadata)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_folder(
        self,
        path: Any = "",
        *,
        recursive: bool = False,
        include_deleted: bool = False,
        limit: int | None = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List the contents of a folder. Use ``""`` for the user root.

        Best first tool for browsing Dropbox. Returns compact summaries
        with ``file_ref``/``folder_ref``, ``name``, ``kind``, ``path``,
        ``size``, ``modified_time``. Paths are how Dropbox identifies
        items — they are safe to show in final answers. Set
        ``include_ids=True`` to also expose Dropbox content ``id`` / ``rev``
        when needed by ``restore``/``list_revisions``. Set
        ``include_metadata=False`` for the raw provider response.
        Continue pagination with ``list_folder_continue`` if
        ``has_more`` is set.
        """
        if isinstance(path, (dict, list, tuple)):
            path = _extract_dropbox_path(path)
        payload: dict[str, Any] = {
            "path": path,
            "recursive": recursive,
            "include_deleted": include_deleted,
        }
        if limit is not None:
            payload["limit"] = limit
        raw = self._rpc("/2/files/list_folder", payload)
        if not include_metadata:
            return raw
        return _summarize_dropbox_entries(raw, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_folder_continue(
        self,
        cursor: str,
        *,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Continue a previous ``list_folder`` call.

        Pass the ``cursor`` from the previous response. Same summary shape
        as ``list_folder``.
        """
        if not cursor:
            raise ValueError("cursor must be a non-empty string")
        raw = self._rpc("/2/files/list_folder/continue", {"cursor": cursor})
        if not include_metadata:
            return raw
        return _summarize_dropbox_entries(raw, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_metadata(
        self,
        path: Any,
        *,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        """Return metadata for a single path.

        Accepts a Dropbox path string or a folder/file dict from
        ``list_folder``/``search``.
        """
        path = _extract_dropbox_path(path)
        return self._rpc(
            "/2/files/get_metadata",
            {"path": path, "include_deleted": include_deleted},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search(
        self,
        query: str,
        *,
        path: str | None = None,
        max_results: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search files using Dropbox search v2.

        Best first tool for finding a file by name. Returns compact
        summaries (``file_ref``/``folder_ref``, ``name``, ``kind``,
        ``path``, ``size``, ``modified_time``). Set ``include_ids=True``
        for raw content ids and ``include_metadata=False`` for the raw
        provider response.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        if max_results < 1 or max_results > 1000:
            raise ValueError("max_results must be between 1 and 1000")
        payload: dict[str, Any] = {"query": query, "options": {"max_results": max_results}}
        if path is not None:
            payload["options"]["path"] = path
        raw = self._rpc("/2/files/search_v2", payload)
        if not include_metadata:
            return raw
        return _summarize_dropbox_entries(raw, include_ids=include_ids, entries_key="matches")

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_temporary_link(self, path: Any) -> dict[str, Any]:
        """Return a short-lived direct download URL.

        Accepts a Dropbox path or a file dict.
        """
        path = _extract_dropbox_path(path)
        return self._rpc("/2/files/get_temporary_link", {"path": path})

    # MARK: - Files (mutations)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_folder(self, path: str, *, autorename: bool = False) -> dict[str, Any]:
        """Create a folder.

        Returns the new folder's metadata. Set ``autorename=True`` to let
        Dropbox suffix the name if it already exists.
        """
        if not path:
            raise ValueError("path must be a non-empty string")
        return self._rpc(
            "/2/files/create_folder_v2",
            {"path": path, "autorename": autorename},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def move(
        self,
        *,
        from_path: Any,
        to_path: str,
        autorename: bool = False,
        allow_shared_folder: bool = False,
    ) -> dict[str, Any]:
        """Move or rename a file or folder.

        ``from_path`` accepts a string or a folder/file dict.
        """
        from_path = _extract_dropbox_path(from_path)
        if not to_path:
            raise ValueError("to_path must be non-empty")
        return self._rpc(
            "/2/files/move_v2",
            {
                "from_path": from_path,
                "to_path": to_path,
                "autorename": autorename,
                "allow_shared_folder": allow_shared_folder,
            },
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def copy(
        self,
        *,
        from_path: Any,
        to_path: str,
        autorename: bool = False,
    ) -> dict[str, Any]:
        """Copy a file or folder.

        ``from_path`` accepts a string or a folder/file dict.
        """
        from_path = _extract_dropbox_path(from_path)
        if not to_path:
            raise ValueError("to_path must be non-empty")
        return self._rpc(
            "/2/files/copy_v2",
            {"from_path": from_path, "to_path": to_path, "autorename": autorename},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete(self, path: Any) -> dict[str, Any]:
        """Soft-delete a file or folder. Recoverable via ``restore``.

        Accepts a Dropbox path or a file/folder dict. Destructive —
        confirm with the user first.
        """
        path = _extract_dropbox_path(path)
        return self._rpc("/2/files/delete_v2", {"path": path})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def restore(self, *, path: str, rev: str) -> dict[str, Any]:
        """Restore a deleted version.

        ``rev`` is the revision id from ``list_revisions``.
        """
        if not path or not rev:
            raise ValueError("path and rev must be non-empty")
        return self._rpc("/2/files/restore", {"path": path, "rev": rev})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_revisions(self, path: Any, *, limit: int = 10) -> dict[str, Any]:
        """List revisions of a file.

        Accepts a Dropbox path or a file dict.
        """
        path = _extract_dropbox_path(path)
        return self._rpc(
            "/2/files/list_revisions",
            {"path": path, "limit": limit, "mode": "path"},
        )

    # MARK: - Sharing

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_shared_link(
        self,
        path: Any,
        *,
        require_password: bool = False,
        link_password: str | None = None,
        audience: str | None = None,
    ) -> dict[str, Any]:
        """Create a shared link.

        Accepts a Dropbox path or a file/folder dict. Returns the link
        resource with ``url`` ready to share.
        """
        path = _extract_dropbox_path(path)
        settings: dict[str, Any] = {}
        if require_password:
            settings["require_password"] = True
        if link_password is not None:
            settings["link_password"] = link_password
        if audience is not None:
            settings["audience"] = audience
        payload: dict[str, Any] = {"path": path}
        if settings:
            payload["settings"] = settings
        return self._rpc("/2/sharing/create_shared_link_with_settings", payload)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_shared_links(
        self,
        *,
        path: str | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List shared links the user has access to.

        Returns the raw provider response with ``links[]`` and ``cursor``.
        """
        payload: dict[str, Any] = {}
        if path is not None:
            payload["path"] = path
        if cursor is not None:
            payload["cursor"] = cursor
        return self._rpc("/2/sharing/list_shared_links", payload)

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def revoke_shared_link(self, url: str) -> dict[str, Any]:
        """Revoke a shared link. Destructive — confirm with the user."""
        if not url:
            raise ValueError("url must be a non-empty string")
        self._rpc("/2/sharing/revoke_shared_link", {"url": url})
        return {"url": url, "revoked": True}

    # MARK: - File requests

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_file_requests(self, *, limit: int = 1000) -> dict[str, Any]:
        """List active file-upload requests."""
        return self._rpc("/2/file_requests/list_v2", {"limit": limit})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_file_request(
        self,
        *,
        title: str,
        destination: str,
        deadline_iso: str | None = None,
    ) -> dict[str, Any]:
        """Create a new file-upload request.

        ``destination`` is the folder path where uploads land.
        """
        if not title or not destination:
            raise ValueError("title and destination must be non-empty")
        payload: dict[str, Any] = {"title": title, "destination": destination}
        if deadline_iso is not None:
            payload["deadline"] = {"deadline": deadline_iso}
        return self._rpc("/2/file_requests/create", payload)
