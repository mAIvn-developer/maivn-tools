"""Google Drive API connector."""

# pyright: strict

from __future__ import annotations

import base64
from typing import Any, cast

from maivn import toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from ._shared import TokenSource, make_bearer_auth

DRIVE_API_URL = "https://www.googleapis.com/drive/v3"
_DEFAULT_LIST_FIELDS = "files(id,name,mimeType,modifiedTime,size,owners,parents),nextPageToken"

# Drive v3 requires supportsAllDrives=true so per-file operations resolve files
# that live in shared (Team) drives; supportsTeamDrives is deprecated. Without it,
# requests targeting shared-drive file IDs can 404 or be rejected.
_SUPPORTS_ALL_DRIVES = "true"


def _extract_file_id(candidate: Any) -> str:
    """Pull a Drive file/folder ID out of common shapes returned by list/search.

    Accepts a raw string id, a summary dict (``{"file_id": ..., ...}`` or
    ``{"id": ..., ...}``), or a list/tuple of such dicts (first valid id
    wins). Raises ``ValueError`` if no usable id can be found.
    """
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("file_id must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        mapping = cast(dict[Any, Any], candidate)
        for key in ("file_id", "folder_id", "id"):
            value: Any = mapping.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("dict candidate has no file_id/folder_id/id")
    if isinstance(candidate, (list, tuple)):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in sequence:
            try:
                return _extract_file_id(item)
            except ValueError:
                continue
        raise ValueError("no usable file id in candidate sequence")
    raise ValueError("file_id must be a string or a file/folder dict")


@toolset(prefix="google_drive")
class GoogleDriveToolSet:
    """A connector for Google Drive.

    Args:
        token: OAuth bearer credential. Accepts an :class:`OAuth2Token`, a
            callable returning one, or a raw access-token string.
        transport: Optional :class:`HttpTransport` override.
        base_url: Override for tests or for self-hosted mirrors.
    """

    metadata = ProviderMetadata(
        name="google_drive",
        display_name="Google Drive",
        version="0.1.0",
        description="Search, fetch metadata, download, and upload Google Drive files.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "https://www.googleapis.com/auth/drive.readonly": "Read-only access.",
            "https://www.googleapis.com/auth/drive.file": (
                "Per-file access to files created or opened."
            ),
            "https://www.googleapis.com/auth/drive": "Full access to all files.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developers.google.com/drive/api",
        homepage_url="https://drive.google.com",
        tags=("files", "google"),
    )

    def __init__(
        self,
        token: TokenSource,
        *,
        transport: HttpTransport | None = None,
        base_url: str = DRIVE_API_URL,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url,
            auth=make_bearer_auth(token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @staticmethod
    def _file_summary(
        file: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        mime_type: Any = file.get("mimeType", "")
        ref_prefix = "folder" if mime_type == "application/vnd.google-apps.folder" else "file"
        owners: Any = file.get("owners", []) or []
        owner = ""
        if owners and isinstance(owners[0], dict):
            first_owner = cast(dict[Any, Any], owners[0])
            owner = first_owner.get("displayName") or first_owner.get("emailAddress") or ""
        summary: dict[str, Any] = {
            f"{ref_prefix}_ref": f"{ref_prefix}_{index}",
            "name": file.get("name", ""),
            "mime_type": mime_type,
            "modified_time": file.get("modifiedTime", ""),
            "size": file.get("size", ""),
            "owner": owner,
        }
        if include_ids:
            summary["file_id"] = file.get("id", "")
            parents = file.get("parents")
            if parents:
                summary["parents"] = parents
        return summary

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_files(
        self,
        query: str = "",
        *,
        page_size: int = 25,
        page_token: str | None = None,
        order_by: str | None = "modifiedTime desc",
        include_metadata: bool = True,
        include_ids: bool = False,
        fields: str | None = None,
    ) -> dict[str, Any]:
        """Search Drive using the v3 query language.

        Best first tool for file exploration. By default it returns compact,
        human-readable summaries: each item has a stable ``file_ref`` (or
        ``folder_ref`` for folders), ``name``, ``mime_type``,
        ``modified_time``, ``size``, and ``owner``. Raw Drive IDs are omitted
        by default because they are internal handles. Set ``include_ids=True``
        when a follow-up tool (``download_file``, ``delete_file``,
        ``update_file_metadata``) needs the raw ``file_id``. Set
        ``include_metadata=False`` to get the raw provider response
        unchanged. Preserves ``nextPageToken`` for pagination.
        """
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        if not include_metadata and fields is None:
            fields = "files(id,name,mimeType,modifiedTime,size,owners),nextPageToken"
        params: dict[str, Any] = {
            "pageSize": page_size,
            "fields": fields or _DEFAULT_LIST_FIELDS,
            "includeItemsFromAllDrives": "true",
            "supportsAllDrives": _SUPPORTS_ALL_DRIVES,
            "corpora": "allDrives",
        }
        if query:
            params["q"] = query
        if order_by is not None:
            params["orderBy"] = order_by
        if page_token is not None:
            params["pageToken"] = page_token
        payload: dict[str, Any] = self._client.get("/files", params=params).json()
        if not include_metadata:
            return payload
        summaries: list[dict[str, Any]] = []
        files: Any = payload.get("files", [])
        for index, item in enumerate(files, start=1):
            if not isinstance(item, dict):
                continue
            file_item = cast(dict[str, Any], item)
            summaries.append(self._file_summary(file_item, index=index, include_ids=include_ids))
        return {
            "files": summaries,
            "nextPageToken": payload.get("nextPageToken"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_file(
        self,
        file_id: Any,
        *,
        fields: str = "id,name,mimeType,parents,modifiedTime,size,owners",
    ) -> dict[str, Any]:
        """Return metadata for a single Drive file.

        Accepts a raw file ID string or a file dict returned by
        ``search_files(include_ids=True)``. Returns the full Drive file
        resource at the requested fields. Use this when you need parents,
        owners, or other fields not shown in ``search_files`` summaries.
        """
        file_id = _extract_file_id(file_id)
        return self._client.get(
            f"/files/{file_id}",
            params={"fields": fields, "supportsAllDrives": _SUPPORTS_ALL_DRIVES},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def download_file(self, file_id: Any) -> dict[str, Any]:
        """Download binary file content as base64 bytes plus metadata.

        Accepts a raw file ID string or a file dict returned by
        ``search_files(include_ids=True)``. Returns
        ``{"file_id": ..., "content_base64": ..., "size": ..., "content_type": ...}``.
        For Google-native docs (Docs/Sheets/Slides) use ``export_file``
        instead — they cannot be downloaded directly.
        """
        file_id = _extract_file_id(file_id)
        response = self._client.get(
            f"/files/{file_id}",
            params={"alt": "media", "supportsAllDrives": _SUPPORTS_ALL_DRIVES},
        )
        return {
            "file_id": file_id,
            "content_base64": base64.b64encode(response.body).decode("ascii"),
            "size": len(response.body),
            "content_type": response.header("Content-Type"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.EXPORT))
    def export_file(self, file_id: Any, mime_type: str) -> dict[str, Any]:
        """Export a Google Doc/Sheet/Slide to ``mime_type``.

        Accepts a raw file ID or a file dict. Use for Google-native files
        only (``application/vnd.google-apps.*``). Common ``mime_type``
        values: ``application/pdf``, ``text/plain``,
        ``application/vnd.openxmlformats-officedocument.wordprocessingml.document``.
        """
        file_id = _extract_file_id(file_id)
        if not mime_type:
            raise ValueError("mime_type must be a non-empty string")
        response = self._client.get(
            f"/files/{file_id}/export",
            params={"mimeType": mime_type, "supportsAllDrives": _SUPPORTS_ALL_DRIVES},
        )
        return {
            "file_id": file_id,
            "mime_type": mime_type,
            "content_base64": base64.b64encode(response.body).decode("ascii"),
            "size": len(response.body),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_folder(
        self,
        name: str,
        *,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a folder.

        Returns the new folder's metadata including the server-assigned
        ``id``. Pass ``id`` as ``parent_id`` to other create/move tools.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        payload: dict[str, Any] = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id is not None:
            payload["parents"] = [parent_id]
        return self._client.post(
            "/files",
            params={"supportsAllDrives": _SUPPORTS_ALL_DRIVES},
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_file(self, file_id: Any) -> dict[str, Any]:
        """Permanently delete a file or folder. Destructive and not reversible.

        Accepts a raw file ID or a file dict from
        ``search_files(include_ids=True)``. This uses the hard-delete
        endpoint; use ``trash_file`` for a recoverable move to Trash.
        Confirm with the user before calling.
        """
        file_id = _extract_file_id(file_id)
        response = self._client.delete(
            f"/files/{file_id}",
            params={"supportsAllDrives": _SUPPORTS_ALL_DRIVES},
        )
        return {"deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def trash_file(self, file_id: Any) -> dict[str, Any]:
        """Move a file to Trash (recoverable).

        Accepts a raw file ID or a file dict. Use ``delete_file`` for a
        permanent, non-recoverable delete.
        """
        file_id = _extract_file_id(file_id)
        return self._client.patch(
            f"/files/{file_id}",
            params={"supportsAllDrives": _SUPPORTS_ALL_DRIVES},
            json={"trashed": True},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def untrash_file(self, file_id: Any) -> dict[str, Any]:
        """Restore a file from Trash.

        Accepts a raw file ID or a file dict.
        """
        file_id = _extract_file_id(file_id)
        return self._client.patch(
            f"/files/{file_id}",
            params={"supportsAllDrives": _SUPPORTS_ALL_DRIVES},
            json={"trashed": False},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def rename_file(self, file_id: Any, new_name: str) -> dict[str, Any]:
        """Rename a file by patching its ``name`` field.

        Accepts a raw file ID or a file dict.
        """
        file_id = _extract_file_id(file_id)
        if not new_name:
            raise ValueError("new_name must be non-empty")
        return self._client.patch(
            f"/files/{file_id}",
            params={"supportsAllDrives": _SUPPORTS_ALL_DRIVES},
            json={"name": new_name},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_file_metadata(
        self,
        file_id: Any,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch arbitrary Drive file metadata fields.

        Accepts a raw file ID or a file dict from
        ``search_files(include_ids=True)``. ``patch`` is merged onto the
        existing resource — only fields you include are changed.
        """
        file_id = _extract_file_id(file_id)
        if not patch:
            raise ValueError("patch must contain at least one field")
        return self._client.patch(
            f"/files/{file_id}",
            params={"supportsAllDrives": _SUPPORTS_ALL_DRIVES},
            json=patch,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def copy_file(
        self,
        file_id: Any,
        *,
        name: str | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        """Copy a file to ``parent_id`` with optional new ``name``.

        Accepts a raw file ID or a file dict. Returns the new file's
        metadata.
        """
        file_id = _extract_file_id(file_id)
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if parent_id is not None:
            payload["parents"] = [parent_id]
        return self._client.post(
            f"/files/{file_id}/copy",
            params={"supportsAllDrives": _SUPPORTS_ALL_DRIVES},
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def move_file(
        self,
        file_id: Any,
        *,
        add_parent_id: str,
        remove_parent_id: str | None = None,
    ) -> dict[str, Any]:
        """Move a file by patching its ``parents`` via ``addParents``/``removeParents``.

        Accepts a raw file ID or a file dict from
        ``search_files(include_ids=True)``. Provide ``remove_parent_id`` to
        unlink the file from its current parent (otherwise it stays linked
        to both).
        """
        file_id = _extract_file_id(file_id)
        if not add_parent_id:
            raise ValueError("add_parent_id must be non-empty")
        params: dict[str, Any] = {
            "addParents": add_parent_id,
            "supportsAllDrives": _SUPPORTS_ALL_DRIVES,
        }
        if remove_parent_id is not None:
            params["removeParents"] = remove_parent_id
        return self._client.patch(
            f"/files/{file_id}",
            params=params,
            json={},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def empty_trash(self) -> dict[str, Any]:
        """Permanently delete every file in the user's Drive trash.

        Destructive and irreversible — confirm with the user before calling.
        Returns ``{"emptied": True, "status": ...}``.
        """
        response = self._client.delete("/files/trash")
        return {"emptied": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_shortcut(
        self,
        target_id: str,
        name: str,
        *,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a Drive shortcut to ``target_id``.

        Returns the new shortcut's metadata. The ``target_id`` is the raw
        Drive ID of the file being pointed at.
        """
        if not target_id or not name:
            raise ValueError("target_id and name must be non-empty")
        payload: dict[str, Any] = {
            "name": name,
            "mimeType": "application/vnd.google-apps.shortcut",
            "shortcutDetails": {"targetId": target_id},
        }
        if parent_id is not None:
            payload["parents"] = [parent_id]
        return self._client.post(
            "/files",
            params={"supportsAllDrives": _SUPPORTS_ALL_DRIVES},
            json=payload,
        ).json()

    # MARK: - Revisions

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_revisions(
        self,
        file_id: Any,
        *,
        page_size: int = 100,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List revisions of a file.

        Accepts a raw file ID or a file dict. Returns the raw provider
        response with ``revisions[]`` and ``nextPageToken``.
        """
        file_id = _extract_file_id(file_id)
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        params: dict[str, Any] = {"pageSize": page_size}
        if page_token is not None:
            params["pageToken"] = page_token
        return self._client.get(f"/files/{file_id}/revisions", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_revision(self, file_id: Any, revision_id: str) -> dict[str, Any]:
        """Return metadata for a single revision.

        Accepts a raw file ID or a file dict for ``file_id``.
        """
        file_id = _extract_file_id(file_id)
        if not revision_id:
            raise ValueError("revision_id must be non-empty")
        return self._client.get(f"/files/{file_id}/revisions/{revision_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_revision(self, file_id: Any, revision_id: str) -> dict[str, Any]:
        """Delete a revision (not the file itself).

        Destructive — confirm with the user before calling.
        """
        file_id = _extract_file_id(file_id)
        if not revision_id:
            raise ValueError("revision_id must be non-empty")
        self._client.delete(f"/files/{file_id}/revisions/{revision_id}")
        return {"file_id": file_id, "revision_id": revision_id, "deleted": True}

    # MARK: - Permissions

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_permissions(self, file_id: Any) -> dict[str, Any]:
        """List permissions on a file.

        Accepts a raw file ID or a file dict. Returns the raw provider
        response with ``permissions[]``.
        """
        file_id = _extract_file_id(file_id)
        return self._client.get(
            f"/files/{file_id}/permissions",
            params={"supportsAllDrives": _SUPPORTS_ALL_DRIVES},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def share_file(
        self,
        file_id: Any,
        permission_type: str,
        role: str,
        *,
        email_address: str | None = None,
        domain: str | None = None,
        send_notification_email: bool = False,
    ) -> dict[str, Any]:
        """Create a permission (share) on a file.

        ``permission_type`` is one of ``user``, ``group``, ``domain``,
        ``anyone``. ``role`` is one of ``owner``, ``organizer``,
        ``fileOrganizer``, ``writer``, ``commenter``, ``reader``. Returns
        the new permission resource.
        """
        file_id = _extract_file_id(file_id)
        if permission_type not in {"user", "group", "domain", "anyone"}:
            raise ValueError("permission_type must be one of: user, group, domain, anyone")
        if role not in {"owner", "organizer", "fileOrganizer", "writer", "commenter", "reader"}:
            raise ValueError(
                "role must be one of: owner, organizer, fileOrganizer, writer, commenter, reader"
            )
        payload: dict[str, Any] = {"type": permission_type, "role": role}
        if email_address is not None:
            payload["emailAddress"] = email_address
        if domain is not None:
            payload["domain"] = domain
        return self._client.post(
            f"/files/{file_id}/permissions",
            params={
                "sendNotificationEmail": str(send_notification_email).lower(),
                "supportsAllDrives": _SUPPORTS_ALL_DRIVES,
            },
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_permission(
        self,
        file_id: Any,
        permission_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch a permission (typically to change the ``role``)."""
        file_id = _extract_file_id(file_id)
        if not permission_id:
            raise ValueError("permission_id must be non-empty")
        if not patch:
            raise ValueError("patch must contain at least one field")
        return self._client.patch(
            f"/files/{file_id}/permissions/{permission_id}",
            params={"supportsAllDrives": _SUPPORTS_ALL_DRIVES},
            json=patch,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def revoke_permission(self, file_id: Any, permission_id: str) -> dict[str, Any]:
        """Revoke a permission.

        Destructive — confirm with the user before calling.
        """
        file_id = _extract_file_id(file_id)
        if not permission_id:
            raise ValueError("permission_id must be non-empty")
        self._client.delete(
            f"/files/{file_id}/permissions/{permission_id}",
            params={"supportsAllDrives": _SUPPORTS_ALL_DRIVES},
        )
        return {"file_id": file_id, "permission_id": permission_id, "deleted": True}

    # MARK: - Drives and changes

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_drives(
        self,
        *,
        page_size: int = 50,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List shared drives accessible to the user.

        Returns the raw provider response with ``drives[]`` and
        ``nextPageToken``.
        """
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")
        params: dict[str, Any] = {"pageSize": page_size}
        if page_token is not None:
            params["pageToken"] = page_token
        return self._client.get("/drives", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_changes(
        self,
        page_token: str,
        *,
        include_removed: bool = True,
        page_size: int = 100,
    ) -> dict[str, Any]:
        """Return Drive change events since ``page_token``.

        Use ``get_changes_start_page_token`` first to obtain the initial
        token. Returns ``{"changes": [...], "nextPageToken": ...,
        "newStartPageToken": ...}``.
        """
        if not page_token:
            raise ValueError("page_token must be a non-empty string")
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        return self._client.get(
            "/changes",
            params={
                "pageToken": page_token,
                "pageSize": page_size,
                "includeRemoved": str(include_removed).lower(),
                "includeItemsFromAllDrives": "true",
                "supportsAllDrives": _SUPPORTS_ALL_DRIVES,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_changes_start_page_token(self) -> dict[str, Any]:
        """Return the start page token for the changes feed.

        Returns ``{"startPageToken": "..."}`` — pass that string to
        ``list_changes`` to begin tracking incremental changes.
        """
        return self._client.get("/changes/startPageToken").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_about(self, fields: str = "user,storageQuota,maxUploadSize") -> dict[str, Any]:
        """Return Drive ``about`` info (user, quota, upload limits)."""
        return self._client.get("/about", params={"fields": fields}).json()
