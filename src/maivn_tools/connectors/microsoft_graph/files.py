"""Microsoft Graph files connector covering OneDrive and SharePoint."""

# pyright: strict

from __future__ import annotations

import base64
from typing import Any, cast

from maivn import toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpTransport
from ._shared import GRAPH_API_URL, TokenSource, make_graph_client


def _extract_item_id(candidate: Any) -> str:
    """Pull a Graph drive item id out of common shapes returned by list/search.

    Accepts a raw string id, a summary dict with ``item_id``/``id``, or a
    list of such dicts (first valid id wins). Raises ``ValueError`` if no
    usable id can be found.
    """
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("item_id must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        candidate_dict = cast("dict[str, Any]", candidate)
        for key in ("item_id", "file_id", "folder_id", "id"):
            value: Any = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("dict candidate has no item_id/file_id/folder_id/id")
    if isinstance(candidate, (list, tuple)):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in sequence:
            try:
                return _extract_item_id(item)
            except ValueError:
                continue
        raise ValueError("no usable item id in candidate sequence")
    raise ValueError("item_id must be a string or a drive-item dict")


def _item_summary(
    item: dict[str, Any],
    *,
    index: int,
    include_ids: bool,
) -> dict[str, Any]:
    is_folder = "folder" in item
    ref_prefix = "folder" if is_folder else "item"
    owner = ""
    created_by: Any = item.get("createdBy")
    owner_info: Any = (
        cast("dict[str, Any]", created_by).get("user") if isinstance(created_by, dict) else None
    )
    if isinstance(owner_info, dict):
        owner_dict = cast("dict[str, Any]", owner_info)
        display_name: Any = owner_dict.get("displayName")
        email: Any = owner_dict.get("email")
        owner = display_name or email or ""
    summary: dict[str, Any] = {
        f"{ref_prefix}_ref": f"{ref_prefix}_{index}",
        "name": item.get("name", ""),
        "kind": "folder" if is_folder else "file",
        "size": item.get("size", 0),
        "modified_time": item.get("lastModifiedDateTime", ""),
        "owner": owner,
        "web_url": item.get("webUrl", ""),
    }
    file_info: Any = item.get("file")
    if isinstance(file_info, dict):
        file_dict = cast("dict[str, Any]", file_info)
        mime: Any = file_dict.get("mimeType")
        if mime:
            summary["mime_type"] = mime
    if include_ids:
        summary["item_id"] = item.get("id", "")
        parent_ref: Any = item.get("parentReference")
        if isinstance(parent_ref, dict):
            parent_dict = cast("dict[str, Any]", parent_ref)
            if parent_dict.get("id"):
                summary["parent_id"] = parent_dict["id"]
    return summary


def _summarize_value_payload(
    payload: dict[str, Any],
    *,
    include_ids: bool,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    values: Any = payload.get("value", []) or []
    raw: Any
    for index, raw in enumerate(values, start=1):
        if not isinstance(raw, dict):
            continue
        raw_dict = cast("dict[str, Any]", raw)
        items.append(_item_summary(raw_dict, index=index, include_ids=include_ids))
    out: dict[str, Any] = {"items": items}
    if "@odata.nextLink" in payload:
        out["next_link"] = payload["@odata.nextLink"]
    return out


@toolset(prefix="ms_files")
class MicrosoftFilesToolSet:
    """A connector covering OneDrive (per-user) and SharePoint (per-site) drives.

    The connector dispatches every tool against a configured drive root.
    Common roots are:

    * ``"me/drive"`` — the authenticated user's OneDrive.
    * ``"users/{user}/drive"`` — another user's drive (admin scope required).
    * ``"sites/{site-id}/drive"`` — the default document library of a
      SharePoint site.

    Args:
        token: OAuth bearer credential.
        drive_root: Path prefix selecting the drive (default ``"me/drive"``).
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="microsoft_graph_files",
        display_name="OneDrive / SharePoint",
        version="0.1.0",
        description="Search, fetch metadata, download, and upload files via Microsoft Graph.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "Files.Read": "Read user files.",
            "Files.ReadWrite": "Manage user files.",
            "Sites.Read.All": "Read SharePoint sites.",
            "Sites.ReadWrite.All": "Manage SharePoint sites.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://learn.microsoft.com/graph/api/resources/onedrive",
        homepage_url="https://onedrive.live.com",
        tags=("files", "microsoft", "sharepoint"),
    )

    def __init__(
        self,
        token: TokenSource,
        *,
        drive_root: str = "me/drive",
        transport: HttpTransport | None = None,
        base_url: str = GRAPH_API_URL,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not drive_root:
            raise ValueError("drive_root must be a non-empty string")
        self.connection = connection
        self._drive_root = drive_root.strip("/")
        self._client = make_graph_client(token, transport=transport, base_url=base_url)

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_root_children(
        self,
        *,
        top: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List the items in the drive root.

        Best first tool for browsing a OneDrive/SharePoint root. Returns
        compact summaries: each item has ``item_ref`` (or ``folder_ref``
        for folders), ``name``, ``kind``, ``size``, ``modified_time``,
        ``owner``, and ``web_url``. Raw Graph IDs are omitted by default —
        set ``include_ids=True`` when a follow-up tool (``download_file``,
        ``delete_item``) needs the raw ``item_id``. Set
        ``include_metadata=False`` for the raw provider response.
        """
        if top < 1 or top > 1000:
            raise ValueError("top must be between 1 and 1000")
        payload = self._client.get(
            self._drive_path("/root/children"),
            params={"$top": top},
        ).json()
        if not include_metadata:
            return payload
        return _summarize_value_payload(payload, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_files(
        self,
        query: str,
        *,
        top: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Run a drive-wide search for ``query``.

        Best first tool for finding a file by name or content. Returns
        compact summaries (``item_ref``, ``name``, ``kind``, ``size``,
        ``modified_time``, ``owner``, ``web_url``). Raw Graph IDs are
        omitted by default — set ``include_ids=True`` when a follow-up
        tool (``download_file``, ``delete_item``, ``move_item``) needs the
        raw ``item_id``. Set ``include_metadata=False`` for the raw
        provider response.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        if top < 1 or top > 1000:
            raise ValueError("top must be between 1 and 1000")
        payload = self._client.get(
            self._drive_path(f"/root/search(q='{query}')"),
            params={"$top": top},
        ).json()
        if not include_metadata:
            return payload
        return _summarize_value_payload(payload, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_item(self, item_id: Any) -> dict[str, Any]:
        """Return metadata for a single drive item.

        Accepts a raw item id or an item dict returned by ``search_files``
        / ``list_root_children`` / ``list_children`` with
        ``include_ids=True``. Returns the full Graph driveItem resource.
        """
        item_id = _extract_item_id(item_id)
        return self._client.get(self._drive_path(f"/items/{item_id}")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def download_file(self, item_id: Any) -> dict[str, Any]:
        """Download a file as base64 bytes plus metadata.

        Accepts a raw item id or an item dict. Returns
        ``{"item_id": ..., "content_base64": ..., "size": ..., "content_type": ...}``.
        Use ``get_item`` first if you only need metadata.
        """
        item_id = _extract_item_id(item_id)
        response = self._client.get(self._drive_path(f"/items/{item_id}/content"))
        return {
            "item_id": item_id,
            "content_base64": base64.b64encode(response.body).decode("ascii"),
            "size": len(response.body),
            "content_type": response.header("Content-Type"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upload_small_file(
        self,
        parent_id: str,
        name: str,
        content_base64: str,
        *,
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        """Upload a file under 4 MB. Larger uploads need a resumable session.

        Returns the new item's metadata. For files larger than 4 MB call
        ``create_upload_session`` and upload chunks to the returned
        ``uploadUrl``.
        """
        if not parent_id:
            raise ValueError("parent_id must be a non-empty string")
        if not name:
            raise ValueError("name must be a non-empty string")
        if not content_base64:
            raise ValueError("content_base64 must be a non-empty string")
        body = base64.b64decode(content_base64)
        if len(body) > 4 * 1024 * 1024:
            raise ValueError(
                "upload_small_file is limited to 4 MB; use a resumable session for larger files"
            )
        response = self._client.put(
            self._drive_path(f"/items/{parent_id}:/{name}:/content"),
            data=body,
            headers={"Content-Type": content_type},
        )
        return response.json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_item(self, item_id: Any) -> dict[str, Any]:
        """Delete a drive item. Destructive — moves to user's recycle bin.

        Accepts a raw item id or an item dict. Confirm with the user before
        calling.
        """
        item_id = _extract_item_id(item_id)
        response = self._client.delete(self._drive_path(f"/items/{item_id}"))
        return {"deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_children(
        self,
        item_id: Any,
        *,
        top: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List children of a specific folder (use ``list_root_children`` for root).

        Accepts a raw folder id or a folder dict. Returns compact summaries
        with ``item_ref`` / ``folder_ref`` plus name, kind, size, modified
        time, owner, and web URL. Set ``include_ids=True`` for raw ids and
        ``include_metadata=False`` for the raw provider response.
        """
        item_id = _extract_item_id(item_id)
        if top < 1 or top > 1000:
            raise ValueError("top must be between 1 and 1000")
        payload = self._client.get(
            self._drive_path(f"/items/{item_id}/children"),
            params={"$top": top},
        ).json()
        if not include_metadata:
            return payload
        return _summarize_value_payload(payload, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_item_by_path(self, path: str) -> dict[str, Any]:
        """Look up an item by its path relative to the drive root.

        ``path`` is a forward-slash path under the drive root such as
        ``"Documents/spec.docx"``. Returns the full Graph driveItem
        resource — use ``include_ids`` is not relevant since the caller
        already knows the path.
        """
        if not path:
            raise ValueError("path must be a non-empty string")
        clean = path.strip("/")
        return self._client.get(self._drive_path(f"/root:/{clean}")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_folder(
        self,
        parent_id: str,
        name: str,
        *,
        conflict_behavior: str = "rename",
    ) -> dict[str, Any]:
        """Create a folder under ``parent_id``.

        Returns the new folder's metadata. ``conflict_behavior`` is one of
        ``fail``, ``replace``, ``rename``.
        """
        if not parent_id or not name:
            raise ValueError("parent_id and name must be non-empty")
        if conflict_behavior not in {"fail", "replace", "rename"}:
            raise ValueError("conflict_behavior must be fail, replace, or rename")
        return self._client.post(
            self._drive_path(f"/items/{parent_id}/children"),
            json={
                "name": name,
                "folder": {},
                "@microsoft.graph.conflictBehavior": conflict_behavior,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def rename_item(self, item_id: Any, new_name: str) -> dict[str, Any]:
        """Rename a drive item.

        Accepts a raw item id or an item dict.
        """
        item_id = _extract_item_id(item_id)
        if not new_name:
            raise ValueError("new_name must be non-empty")
        return self._client.patch(
            self._drive_path(f"/items/{item_id}"),
            json={"name": new_name},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_item_metadata(self, item_id: Any, patch: dict[str, Any]) -> dict[str, Any]:
        """Patch arbitrary drive-item metadata.

        Accepts a raw item id or an item dict. Only fields you include in
        ``patch`` are changed.
        """
        item_id = _extract_item_id(item_id)
        if not patch:
            raise ValueError("patch must contain at least one field")
        return self._client.patch(self._drive_path(f"/items/{item_id}"), json=patch).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def move_item(self, item_id: Any, new_parent_id: str) -> dict[str, Any]:
        """Move an item under a new parent folder.

        Accepts a raw item id or an item dict for ``item_id``.
        """
        item_id = _extract_item_id(item_id)
        if not new_parent_id:
            raise ValueError("new_parent_id must be non-empty")
        return self._client.patch(
            self._drive_path(f"/items/{item_id}"),
            json={"parentReference": {"id": new_parent_id}},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def copy_item(
        self,
        item_id: Any,
        *,
        new_parent_id: str | None = None,
        new_name: str | None = None,
    ) -> dict[str, Any]:
        """Copy an item (returns the monitor URL via the ``Location`` header).

        Accepts a raw item id or an item dict. Returns
        ``{"status": ..., "monitor_url": ...}`` — Graph runs the copy
        asynchronously and exposes progress at the monitor URL.
        """
        item_id = _extract_item_id(item_id)
        payload: dict[str, Any] = {}
        if new_parent_id is not None:
            payload["parentReference"] = {"id": new_parent_id}
        if new_name is not None:
            payload["name"] = new_name
        response = self._client.post(
            self._drive_path(f"/items/{item_id}/copy"),
            json=payload or None,
        )
        return {"status": response.status, "monitor_url": response.header("Location")}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_upload_session(
        self,
        parent_id: str,
        name: str,
        *,
        conflict_behavior: str = "rename",
    ) -> dict[str, Any]:
        """Open a resumable upload session for large (>4 MB) files.

        Returns ``{"uploadUrl": ...}`` — PUT consecutive chunks to that URL
        per the Microsoft Graph large-file upload protocol.
        """
        if not parent_id or not name:
            raise ValueError("parent_id and name must be non-empty")
        if conflict_behavior not in {"fail", "replace", "rename"}:
            raise ValueError("conflict_behavior must be fail, replace, or rename")
        return self._client.post(
            self._drive_path(f"/items/{parent_id}:/{name}:/createUploadSession"),
            json={
                "item": {"@microsoft.graph.conflictBehavior": conflict_behavior, "name": name},
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_versions(self, item_id: Any, *, top: int = 100) -> dict[str, Any]:
        """List versions of a drive item.

        Accepts a raw item id or an item dict.
        """
        item_id = _extract_item_id(item_id)
        if top < 1 or top > 1000:
            raise ValueError("top must be between 1 and 1000")
        return self._client.get(
            self._drive_path(f"/items/{item_id}/versions"),
            params={"$top": top},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def restore_version(self, item_id: Any, version_id: str) -> dict[str, Any]:
        """Restore a previous version of an item.

        Accepts a raw item id or an item dict for ``item_id``.
        """
        item_id = _extract_item_id(item_id)
        if not version_id:
            raise ValueError("version_id must be non-empty")
        response = self._client.post(
            self._drive_path(f"/items/{item_id}/versions/{version_id}/restoreVersion"),
        )
        return {"restored": True, "status": response.status}

    # MARK: - Sharing & permissions

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_permissions(self, item_id: Any) -> dict[str, Any]:
        """List permissions on a drive item.

        Accepts a raw item id or an item dict.
        """
        item_id = _extract_item_id(item_id)
        return self._client.get(self._drive_path(f"/items/{item_id}/permissions")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_share_link(
        self,
        item_id: Any,
        *,
        link_type: str = "view",
        scope: str = "anonymous",
        password: str | None = None,
        expiration_datetime: str | None = None,
    ) -> dict[str, Any]:
        """Create a sharing link for a drive item.

        Accepts a raw item id or an item dict. Returns the link resource
        with ``link.webUrl`` ready to share.
        """
        item_id = _extract_item_id(item_id)
        if link_type not in {"view", "edit", "embed"}:
            raise ValueError("link_type must be view, edit, or embed")
        if scope not in {"anonymous", "organization", "users"}:
            raise ValueError("scope must be anonymous, organization, or users")
        payload: dict[str, Any] = {"type": link_type, "scope": scope}
        if password is not None:
            payload["password"] = password
        if expiration_datetime is not None:
            payload["expirationDateTime"] = expiration_datetime
        return self._client.post(
            self._drive_path(f"/items/{item_id}/createLink"),
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def invite_to_item(
        self,
        item_id: Any,
        recipients: list[str],
        *,
        roles: list[str] | None = None,
        require_sign_in: bool = True,
        send_invitation: bool = False,
        message: str | None = None,
    ) -> dict[str, Any]:
        """Invite specific recipients to a drive item via ``invite``.

        Accepts a raw item id or an item dict. ``roles`` defaults to
        ``["read"]``.
        """
        item_id = _extract_item_id(item_id)
        if not recipients:
            raise ValueError("recipients must be non-empty")
        payload: dict[str, Any] = {
            "recipients": [{"email": addr} for addr in recipients],
            "requireSignIn": require_sign_in,
            "sendInvitation": send_invitation,
            "roles": list(roles) if roles else ["read"],
        }
        if message is not None:
            payload["message"] = message
        return self._client.post(
            self._drive_path(f"/items/{item_id}/invite"),
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def revoke_permission(self, item_id: Any, permission_id: str) -> dict[str, Any]:
        """Revoke a sharing permission.

        Destructive — confirm with the user before calling.
        """
        item_id = _extract_item_id(item_id)
        if not permission_id:
            raise ValueError("permission_id must be non-empty")
        self._client.delete(self._drive_path(f"/items/{item_id}/permissions/{permission_id}"))
        return {"item_id": item_id, "permission_id": permission_id, "deleted": True}

    # MARK: - Drive metadata

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_drive(self) -> dict[str, Any]:
        """Return the drive metadata (quota, owner, drive type)."""
        return self._client.get(f"/{self._drive_root}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_recent(self) -> dict[str, Any]:
        """List recently-accessed items in the drive.

        Deprecated: the Graph ``drive: recent`` endpoint is sunsetting and
        operates in a degraded state until November 2026, after which it
        stops returning data. Migrate recent-files use cases to the
        Microsoft Search API (``POST /search/query`` with ``entityTypes``
        ``driveItem``) or Insights (``/me/insights/used``). Returns the raw
        provider response. For human-friendly summaries prefer
        ``search_files`` or ``list_root_children``.

        This endpoint documents no query parameters; ``$top`` is not
        contractually supported here and paging is not available.
        """
        return self._client.get(self._drive_path("/recent")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_shared_with_me(self) -> dict[str, Any]:
        """List items shared with the user.

        Deprecated: the Graph ``drive: sharedWithMe`` endpoint is sunsetting
        and operates in a degraded state until November 2026, after which it
        stops returning data. Migrate to the Microsoft Search API
        (``POST /search/query`` with ``entityTypes`` ``driveItem``) or the
        shared-items insights surface. Note returned items carry the
        ``remoteItem`` facet. Returns the raw provider response. For
        human-friendly summaries prefer ``search_files`` or
        ``list_root_children``.

        This endpoint documents no query parameters; ``$top`` is not
        contractually supported here and paging is not available.
        """
        return self._client.get(self._drive_path("/sharedWithMe")).json()

    # MARK: - Internal

    def _drive_path(self, suffix: str) -> str:
        if not suffix.startswith("/"):
            suffix = "/" + suffix
        return f"/{self._drive_root}{suffix}"
