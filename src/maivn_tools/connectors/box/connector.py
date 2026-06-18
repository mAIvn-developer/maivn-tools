"""Box Content API v2 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_FOLDER_ITEMS_OUTPUT, SEARCH_OUTPUT


def _extract_box_id(candidate: Any, *, key_hints: tuple[str, ...] = ()) -> str:
    """Pull a Box id out of common shapes returned by list/search.

    Accepts a raw string id, a Box entry dict (``{"id": ..., ...}`` or
    ``{"file_id": ..., ...}``), or a list of such dicts (first valid id
    wins). ``key_hints`` lets callers prioritize keys like ``"file_id"``
    or ``"folder_id"``.
    """
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("id must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        entry = cast(dict[str, Any], candidate)
        for key in (*key_hints, "file_id", "folder_id", "item_id", "id"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("dict candidate has no usable Box id")
    if isinstance(candidate, (list, tuple)):
        for item in cast("list[Any] | tuple[Any, ...]", candidate):
            try:
                return _extract_box_id(item, key_hints=key_hints)
            except ValueError:
                continue
        raise ValueError("no usable Box id in candidate sequence")
    raise ValueError("id must be a string or a Box entry dict")


def _box_entry_summary(
    entry: dict[str, Any],
    *,
    index: int,
    include_ids: bool,
) -> dict[str, Any]:
    kind = entry.get("type") or ""
    ref_prefix = "folder" if kind == "folder" else ("file" if kind == "file" else "item")
    owner: str = ""
    raw_owned_by = entry.get("owned_by")
    if isinstance(raw_owned_by, dict):
        owned_by = cast(dict[str, Any], raw_owned_by)
        owner = owned_by.get("name") or owned_by.get("login") or ""
    summary: dict[str, Any] = {
        f"{ref_prefix}_ref": f"{ref_prefix}_{index}",
        "name": entry.get("name", ""),
        "kind": kind,
        "size": entry.get("size", 0),
        "modified_time": entry.get("modified_at", ""),
        "owner": owner,
    }
    if include_ids:
        summary[f"{ref_prefix}_id" if ref_prefix in {"file", "folder"} else "id"] = entry.get(
            "id", ""
        )
        raw_parent = entry.get("parent")
        if isinstance(raw_parent, dict):
            parent = cast(dict[str, Any], raw_parent)
            if parent.get("id"):
                summary["parent_id"] = parent["id"]
    return summary


def _summarize_box_entries(
    payload: dict[str, Any],
    *,
    include_ids: bool,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    entries = cast("list[Any]", payload.get("entries", []) or [])
    for index, raw in enumerate(entries, start=1):
        if not isinstance(raw, dict):
            continue
        items.append(
            _box_entry_summary(cast(dict[str, Any], raw), index=index, include_ids=include_ids)
        )
    out: dict[str, Any] = {"items": items}
    if "total_count" in payload:
        out["total_count"] = payload["total_count"]
    if "offset" in payload:
        out["offset"] = payload["offset"]
    if "limit" in payload:
        out["limit"] = payload["limit"]
    return out


@toolset(prefix="box")
class BoxToolSet:
    """A connector for the Box Content API v2.

    Args:
        token: OAuth bearer or app-token. Never logged.
        base_url: API root.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="box",
        display_name="Box",
        version="0.1.0",
        description="Manage Box files, folders, sharing, and search.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE, AuthMode.BEARER),
        scopes={
            "root_readonly": "Read files and folders.",
            "root_readwrite": "Read, write, and share files and folders.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developer.box.com/reference/",
        homepage_url="https://www.box.com/",
        tags=("storage", "ecm"),
    )

    def __init__(
        self,
        *,
        token: str,
        base_url: str = "https://api.box.com",
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

    # MARK: - Identity

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_current_user(self) -> dict[str, Any]:
        """Return the authenticated user.

        Returns the Box user resource (``id``, ``name``, ``login``).
        """
        return self._client.get("/2.0/users/me").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self, user_id: str) -> dict[str, Any]:
        """Return a user by ID."""
        if not user_id:
            raise ValueError("user_id must be a non-empty string")
        return self._client.get(f"/2.0/users/{user_id}").json()

    # MARK: - Folders

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_folder(self, folder_id: Any = "0") -> dict[str, Any]:
        """Return folder metadata (default ``"0"`` is the user root).

        Accepts a raw folder id or a folder dict from
        ``list_folder_items``/``search``.
        """
        folder_id = _extract_box_id(folder_id, key_hints=("folder_id",))
        return self._client.get(f"/2.0/folders/{folder_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_FOLDER_ITEMS_OUTPUT)
    def list_folder_items(
        self,
        folder_id: Any = "0",
        *,
        offset: int = 0,
        limit: int = 25,
        fields: list[str] | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List items in a folder.

        Best first tool for browsing Box folders. Returns compact summaries
        with ``file_ref``/``folder_ref``, ``name``, ``kind``, ``size``,
        ``modified_time``, ``owner``. Raw Box IDs are omitted by default —
        set ``include_ids=True`` when a follow-up tool (``delete_file``,
        ``update_file``, ``copy_file``) needs the raw id. Set
        ``include_metadata=False`` for the raw provider response.
        """
        folder_id = _extract_box_id(folder_id, key_hints=("folder_id",))
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if fields is not None:
            params["fields"] = ",".join(fields)
        elif include_metadata:
            params["fields"] = "name,size,modified_at,type,parent,owned_by"
        payload = self._client.get(
            f"/2.0/folders/{folder_id}/items",
            params=params,
        ).json()
        if not include_metadata:
            return payload
        return _summarize_box_entries(payload, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_folder(self, name: str, *, parent_id: str = "0") -> dict[str, Any]:
        """Create a folder under ``parent_id``.

        Returns the new folder's metadata. Pass ``id`` from the result as
        ``parent_id`` to ``create_folder`` or ``copy_file``.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        return self._client.post(
            "/2.0/folders",
            json={"name": name, "parent": {"id": parent_id}},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_folder(
        self,
        folder_id: Any,
        *,
        name: str | None = None,
        parent_id: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Rename or move a folder.

        Accepts a raw folder id or a folder dict. At least one of
        ``name``/``parent_id``/``description`` must be provided.
        """
        folder_id = _extract_box_id(folder_id, key_hints=("folder_id",))
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if parent_id is not None:
            payload["parent"] = {"id": parent_id}
        if description is not None:
            payload["description"] = description
        if not payload:
            raise ValueError("at least one of name/parent_id/description must be set")
        return self._client.put(f"/2.0/folders/{folder_id}", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_folder(self, folder_id: Any, *, recursive: bool = False) -> dict[str, Any]:
        """Delete a folder (moves to trash). Destructive — confirm with user.

        Accepts a raw folder id or a folder dict. ``recursive=True`` is
        required for non-empty folders.
        """
        folder_id = _extract_box_id(folder_id, key_hints=("folder_id",))
        params = {"recursive": "true"} if recursive else None
        self._client.delete(f"/2.0/folders/{folder_id}", params=params)
        return {"id": folder_id, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def copy_folder(
        self,
        folder_id: Any,
        *,
        parent_id: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Copy a folder to a new parent.

        Accepts a raw folder id or a folder dict.
        """
        folder_id = _extract_box_id(folder_id, key_hints=("folder_id",))
        if not parent_id:
            raise ValueError("parent_id must be non-empty")
        payload: dict[str, Any] = {"parent": {"id": parent_id}}
        if name is not None:
            payload["name"] = name
        return self._client.post(f"/2.0/folders/{folder_id}/copy", json=payload).json()

    # MARK: - Files

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_file(self, file_id: Any, *, fields: list[str] | None = None) -> dict[str, Any]:
        """Return file metadata.

        Accepts a raw file id or a file dict.
        """
        file_id = _extract_box_id(file_id, key_hints=("file_id",))
        params = {"fields": ",".join(fields)} if fields else None
        return self._client.get(f"/2.0/files/{file_id}", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_file(
        self,
        file_id: Any,
        *,
        name: str | None = None,
        parent_id: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Rename or move a file.

        Accepts a raw file id or a file dict. At least one of
        ``name``/``parent_id``/``description`` must be provided.
        """
        file_id = _extract_box_id(file_id, key_hints=("file_id",))
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if parent_id is not None:
            payload["parent"] = {"id": parent_id}
        if description is not None:
            payload["description"] = description
        if not payload:
            raise ValueError("at least one of name/parent_id/description must be set")
        return self._client.put(f"/2.0/files/{file_id}", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_file(self, file_id: Any) -> dict[str, Any]:
        """Delete a file (moves to trash). Destructive — confirm with user.

        Accepts a raw file id or a file dict from ``list_folder_items`` /
        ``search`` with ``include_ids=True``.
        """
        file_id = _extract_box_id(file_id, key_hints=("file_id",))
        self._client.delete(f"/2.0/files/{file_id}")
        return {"id": file_id, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def copy_file(
        self,
        file_id: Any,
        *,
        parent_id: str,
        name: str | None = None,
        version: str | None = None,
    ) -> dict[str, Any]:
        """Copy a file.

        Accepts a raw file id or a file dict.
        """
        file_id = _extract_box_id(file_id, key_hints=("file_id",))
        if not parent_id:
            raise ValueError("parent_id must be non-empty")
        payload: dict[str, Any] = {"parent": {"id": parent_id}}
        if name is not None:
            payload["name"] = name
        if version is not None:
            payload["version"] = version
        return self._client.post(f"/2.0/files/{file_id}/copy", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_file_download_url(self, file_id: Any) -> dict[str, Any]:
        """Return a temporary download URL for a file.

        Accepts a raw file id or a file dict. Returns ``{"download_url": ...}``.
        """
        file_id = _extract_box_id(file_id, key_hints=("file_id",))
        return self._client.get(
            f"/2.0/files/{file_id}",
            params={"fields": "download_url"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_file_versions(self, file_id: Any) -> dict[str, Any]:
        """List previous versions of a file.

        Accepts a raw file id or a file dict.
        """
        file_id = _extract_box_id(file_id, key_hints=("file_id",))
        return self._client.get(f"/2.0/files/{file_id}/versions").json()

    # MARK: - Search

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SEARCH_OUTPUT)
    def search(
        self,
        query: str,
        *,
        type: str | None = None,
        scope: str | None = None,
        offset: int = 0,
        limit: int = 25,
        file_extensions: list[str] | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Run a Box search.

        Best first tool for finding files/folders by content or name.
        Returns compact summaries (``file_ref``/``folder_ref``, ``name``,
        ``kind``, ``size``, ``modified_time``, ``owner``). Set
        ``include_ids=True`` for raw ids needed by follow-up tools, or
        ``include_metadata=False`` for the raw provider response.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        params: dict[str, Any] = {"query": query, "offset": offset, "limit": limit}
        if type is not None:
            params["type"] = type
        if scope is not None:
            params["scope"] = scope
        if file_extensions is not None:
            params["file_extensions"] = ",".join(file_extensions)
        if include_metadata:
            params["fields"] = "name,size,modified_at,type,parent,owned_by"
        payload = self._client.get("/2.0/search", params=params).json()
        if not include_metadata:
            return payload
        return _summarize_box_entries(payload, include_ids=include_ids)

    # MARK: - Collaborations & sharing

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_collaborations(self, *, item_id: str, item_type: str) -> dict[str, Any]:
        """List collaborations on a file or folder.

        ``item_type`` is ``"file"`` or ``"folder"``.
        """
        if item_type not in {"file", "folder"}:
            raise ValueError("item_type must be 'file' or 'folder'")
        if not item_id:
            raise ValueError("item_id must be a non-empty string")
        return self._client.get(f"/2.0/{item_type}s/{item_id}/collaborations").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_collaboration(
        self,
        *,
        item_id: str,
        item_type: str,
        accessible_by_login: str | None = None,
        accessible_by_id: str | None = None,
        role: str,
    ) -> dict[str, Any]:
        """Add a collaborator to a file or folder.

        ``item_type`` is ``"file"`` or ``"folder"``. Provide one of
        ``accessible_by_login`` (email) or ``accessible_by_id`` (Box user
        ID). ``role`` is the Box role (``editor``, ``viewer``, etc.).
        """
        if item_type not in {"file", "folder"}:
            raise ValueError("item_type must be 'file' or 'folder'")
        if not item_id or not role:
            raise ValueError("item_id and role must be non-empty")
        if accessible_by_login is None and accessible_by_id is None:
            raise ValueError("provide accessible_by_login or accessible_by_id")
        accessible_by: dict[str, Any] = {"type": "user"}
        if accessible_by_login is not None:
            accessible_by["login"] = accessible_by_login
        if accessible_by_id is not None:
            accessible_by["id"] = accessible_by_id
        payload = {
            "item": {"type": item_type, "id": item_id},
            "accessible_by": accessible_by,
            "role": role,
        }
        return self._client.post("/2.0/collaborations", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_collaboration(self, collaboration_id: str) -> dict[str, Any]:
        """Remove a collaboration. Destructive — confirm with the user."""
        if not collaboration_id:
            raise ValueError("collaboration_id must be a non-empty string")
        self._client.delete(f"/2.0/collaborations/{collaboration_id}")
        return {"id": collaboration_id, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_shared_link(
        self,
        *,
        item_id: str,
        item_type: str,
        access: str = "open",
        password: str | None = None,
        unshared_at: str | None = None,
    ) -> dict[str, Any]:
        """Attach a shared link to a file or folder.

        ``access`` is one of ``open`` (anyone), ``company`` (org members),
        ``collaborators`` (collaborators only). Returns the updated item
        resource with ``shared_link.url``.
        """
        if item_type not in {"file", "folder"}:
            raise ValueError("item_type must be 'file' or 'folder'")
        if not item_id:
            raise ValueError("item_id must be a non-empty string")
        if access not in {"open", "company", "collaborators"}:
            raise ValueError("access must be open/company/collaborators")
        shared_link: dict[str, Any] = {"access": access}
        if password is not None:
            shared_link["password"] = password
        if unshared_at is not None:
            shared_link["unshared_at"] = unshared_at
        return self._client.put(
            f"/2.0/{item_type}s/{item_id}",
            json={"shared_link": shared_link},
        ).json()

    # MARK: - Trash

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_trash(self, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        """List items in the trash."""
        return self._client.get(
            "/2.0/folders/trash/items",
            params={"offset": offset, "limit": limit},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def empty_trash(self) -> dict[str, Any]:
        """Permanently remove a single item from trash. See ``permanently_delete``.

        Box does not expose a bulk "empty trash" endpoint; use
        ``permanently_delete`` for each trashed item.
        """
        raise NotImplementedError(
            "Box requires per-item permanent delete; use permanently_delete()"
        )

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def permanently_delete(self, *, item_id: str, item_type: str) -> dict[str, Any]:
        """Permanently remove a trashed file or folder. Destructive and irreversible.

        Confirm with the user before calling. ``item_type`` is ``"file"``
        or ``"folder"``.
        """
        if item_type not in {"file", "folder"}:
            raise ValueError("item_type must be 'file' or 'folder'")
        if not item_id:
            raise ValueError("item_id must be a non-empty string")
        self._client.delete(f"/2.0/{item_type}s/{item_id}/trash")
        return {"id": item_id, "deleted": True}
