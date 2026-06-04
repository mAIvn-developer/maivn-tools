"""Notion API v1 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# Notion-Version header default. ``2022-06-28`` remains a valid, fully
# supported REST contract (Notion has no announced sunset for older REST
# versions) and every endpoint/filter shape in this connector is correct for
# it. Deprecation trajectory: versions >= ``2025-09-03`` introduce the
# non-backward-compatible "data sources" model -- database query/retrieve move
# to ``/v1/data_sources`` (``database_id`` -> ``data_source_id``) and search
# ``filter.value`` gains ``"data_source"``. Adopting a newer default therefore
# requires migrating those endpoints, not just bumping this pin. Override per
# instance via the ``notion_version`` constructor argument.
_NOTION_VERSION = "2022-06-28"


@toolset(prefix="notion")
class NotionToolSet:
    """A connector for the Notion API v1.

    Args:
        token: Integration secret (internal or OAuth bearer).
        notion_version: ``Notion-Version`` header value.
        base_url: Override the API root.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="notion",
        display_name="Notion",
        version="0.1.0",
        description="Read and edit Notion pages, databases, blocks, and comments.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE, AuthMode.BEARER),
        scopes={
            "read_content": "Read pages, databases, and blocks.",
            "update_content": "Create and update pages, databases, and blocks.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developers.notion.com/reference/intro",
        homepage_url="https://www.notion.so/",
        tags=("knowledge-base", "docs"),
    )

    def __init__(
        self,
        *,
        token: str,
        notion_version: str = _NOTION_VERSION,
        base_url: str = "https://api.notion.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not token:
            raise ValueError("token is required")
        if not notion_version:
            raise ValueError("notion_version is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(token),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Notion-Version": notion_version,
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Identity

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_self(self) -> dict[str, Any]:
        """Return the bot user that owns the integration token."""
        return self._client.get("/v1/users/me").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self, user_id: str) -> dict[str, Any]:
        """Return a user object."""
        if not user_id:
            raise ValueError("user_id must be a non-empty string")
        return self._client.get(f"/v1/users/{user_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_users(
        self,
        *,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        """List workspace users."""
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")
        params: dict[str, Any] = {"page_size": page_size}
        if start_cursor is not None:
            params["start_cursor"] = start_cursor
        return self._client.get("/v1/users", params=params).json()

    # MARK: - Search

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search(
        self,
        query: str = "",
        *,
        filter_type: str | None = None,
        sort_direction: str | None = None,
        start_cursor: str | None = None,
        page_size: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search Notion pages and databases.

        Best first tool for finding content in a workspace. By default
        returns compact summaries with a stable ``result_ref`` (``result_1``,
        ``result_2``, ...) plus the object type (``page``/``database``),
        title, URL, and last-edited timestamp. Notion ``id`` GUIDs are
        internal handles and are omitted unless ``include_ids=True``. Set
        ``include_metadata=False`` to receive the raw Notion response
        including ``has_more``/``next_cursor`` pagination cursors.
        ``filter_type`` is ``"page"`` or ``"database"``.
        """
        if filter_type is not None and filter_type not in {"page", "database"}:
            raise ValueError("filter_type must be 'page' or 'database'")
        if sort_direction is not None and sort_direction not in {"ascending", "descending"}:
            raise ValueError("sort_direction must be 'ascending' or 'descending'")
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")
        payload: dict[str, Any] = {"query": query, "page_size": page_size}
        if filter_type is not None:
            payload["filter"] = {"value": filter_type, "property": "object"}
        if sort_direction is not None:
            payload["sort"] = {"direction": sort_direction, "timestamp": "last_edited_time"}
        if start_cursor is not None:
            payload["start_cursor"] = start_cursor
        response = self._client.post("/v1/search", json=payload).json()
        if not include_metadata:
            return response
        return self._summarize_search_results(response, include_ids=include_ids)

    # MARK: - Pages

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_page(self, page_id: Any) -> dict[str, Any]:
        """Return a page by ID.

        ``page_id`` accepts the raw Notion ID string, a result dict from
        :meth:`search`/:meth:`query_database` (``include_ids=True``), or a
        list of such dicts.
        """
        resolved = self._extract_page_id(page_id)
        return self._client.get(f"/v1/pages/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_page_property(
        self,
        page_id: Any,
        property_id: str,
        *,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        """Retrieve a single property item from a page.

        ``page_id`` accepts the raw Notion ID string or a dict/list from
        :meth:`search`/:meth:`query_database`.
        """
        resolved = self._extract_page_id(page_id)
        if not property_id:
            raise ValueError("property_id must be a non-empty string")
        params: dict[str, Any] = {"page_size": page_size}
        if start_cursor is not None:
            params["start_cursor"] = start_cursor
        return self._client.get(
            f"/v1/pages/{resolved}/properties/{property_id}",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_page(
        self,
        *,
        parent: dict[str, Any],
        properties: dict[str, Any],
        children: list[dict[str, Any]] | None = None,
        icon: dict[str, Any] | None = None,
        cover: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new page under a database or page parent.

        Returns the new Notion page resource.
        """
        if not parent:
            raise ValueError("parent must be a non-empty dict")
        payload: dict[str, Any] = {"parent": parent, "properties": properties}
        if children is not None:
            payload["children"] = children
        if icon is not None:
            payload["icon"] = icon
        if cover is not None:
            payload["cover"] = cover
        return self._client.post("/v1/pages", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_page(
        self,
        page_id: Any,
        *,
        properties: dict[str, Any] | None = None,
        archived: bool | None = None,
        icon: dict[str, Any] | None = None,
        cover: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Patch page properties or archive state.

        ``page_id`` accepts the raw Notion ID string or a dict/list from
        :meth:`search`/:meth:`query_database`.
        """
        resolved = self._extract_page_id(page_id)
        if properties is None and archived is None and icon is None and cover is None:
            raise ValueError("at least one of properties/archived/icon/cover must be set")
        payload: dict[str, Any] = {}
        if properties is not None:
            payload["properties"] = properties
        if archived is not None:
            payload["archived"] = archived
        if icon is not None:
            payload["icon"] = icon
        if cover is not None:
            payload["cover"] = cover
        return self._client.patch(f"/v1/pages/{resolved}", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def archive_page(self, page_id: Any) -> dict[str, Any]:
        """Archive (soft-delete) a page.

        Destructive: the page is moved to the trash. ``page_id`` accepts
        the raw Notion ID string or a dict/list from :meth:`search`/
        :meth:`query_database`.
        """
        resolved = self._extract_page_id(page_id)
        return self._client.patch(
            f"/v1/pages/{resolved}",
            json={"archived": True},
        ).json()

    # MARK: - Databases

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_database(self, database_id: str) -> dict[str, Any]:
        """Return a database object."""
        if not database_id:
            raise ValueError("database_id must be a non-empty string")
        return self._client.get(f"/v1/databases/{database_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def query_database(
        self,
        database_id: str,
        *,
        filter: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
        start_cursor: str | None = None,
        page_size: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Query rows in a Notion database.

        Best first tool for filtering a database. By default returns
        compact summaries with a stable ``page_ref`` (``page_1``, ``page_2``,
        ...) plus the row title, URL, and last-edited timestamp. Notion
        ``id`` GUIDs are internal handles and are omitted unless
        ``include_ids=True``. Set ``include_metadata=False`` to receive the
        raw Notion response including ``has_more``/``next_cursor``
        pagination cursors.

        ``filter`` and ``sorts`` follow Notion's filter/sort syntax.
        """
        if not database_id:
            raise ValueError("database_id must be a non-empty string")
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")
        payload: dict[str, Any] = {"page_size": page_size}
        if filter is not None:
            payload["filter"] = filter
        if sorts is not None:
            payload["sorts"] = sorts
        if start_cursor is not None:
            payload["start_cursor"] = start_cursor
        response = self._client.post(
            f"/v1/databases/{database_id}/query",
            json=payload,
        ).json()
        if not include_metadata:
            return response
        return self._summarize_search_results(response, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_database(
        self,
        *,
        parent: dict[str, Any],
        title: list[dict[str, Any]],
        properties: dict[str, Any],
        icon: dict[str, Any] | None = None,
        cover: dict[str, Any] | None = None,
        is_inline: bool | None = None,
    ) -> dict[str, Any]:
        """Create a new database under a page parent."""
        if not parent or not title or not properties:
            raise ValueError("parent, title, and properties are required")
        payload: dict[str, Any] = {
            "parent": parent,
            "title": title,
            "properties": properties,
        }
        if icon is not None:
            payload["icon"] = icon
        if cover is not None:
            payload["cover"] = cover
        if is_inline is not None:
            payload["is_inline"] = is_inline
        return self._client.post("/v1/databases", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_database(
        self,
        database_id: str,
        *,
        title: list[dict[str, Any]] | None = None,
        description: list[dict[str, Any]] | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update database title, description, or schema."""
        if not database_id:
            raise ValueError("database_id must be a non-empty string")
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description
        if properties is not None:
            payload["properties"] = properties
        if not payload:
            raise ValueError("at least one of title/description/properties must be set")
        return self._client.patch(
            f"/v1/databases/{database_id}",
            json=payload,
        ).json()

    # MARK: - Blocks

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_block(self, block_id: str) -> dict[str, Any]:
        """Return a block by ID."""
        if not block_id:
            raise ValueError("block_id must be a non-empty string")
        return self._client.get(f"/v1/blocks/{block_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_block_children(
        self,
        block_id: str,
        *,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        """List children of a block (the block can be a page)."""
        if not block_id:
            raise ValueError("block_id must be a non-empty string")
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")
        params: dict[str, Any] = {"page_size": page_size}
        if start_cursor is not None:
            params["start_cursor"] = start_cursor
        return self._client.get(
            f"/v1/blocks/{block_id}/children",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def append_block_children(
        self,
        block_id: str,
        children: list[dict[str, Any]],
        *,
        after: str | None = None,
    ) -> dict[str, Any]:
        """Append child blocks under a block or page."""
        if not block_id:
            raise ValueError("block_id must be a non-empty string")
        if not children:
            raise ValueError("children must be a non-empty list")
        payload: dict[str, Any] = {"children": children}
        if after is not None:
            payload["after"] = after
        return self._client.patch(
            f"/v1/blocks/{block_id}/children",
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_block(self, block_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Update an existing block. ``fields`` follow the Notion block schema."""
        if not block_id:
            raise ValueError("block_id must be a non-empty string")
        if not fields:
            raise ValueError("fields must be a non-empty dict")
        return self._client.patch(f"/v1/blocks/{block_id}", json=fields).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_block(self, block_id: str) -> dict[str, Any]:
        """Soft-delete (archive) a block.

        Destructive: confirm with the user first.
        """
        if not block_id:
            raise ValueError("block_id must be a non-empty string")
        return self._client.delete(f"/v1/blocks/{block_id}").json()

    # MARK: - Comments

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_comments(
        self,
        block_id: str,
        *,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        """List comments on a block/page."""
        if not block_id:
            raise ValueError("block_id must be a non-empty string")
        params: dict[str, Any] = {"block_id": block_id, "page_size": page_size}
        if start_cursor is not None:
            params["start_cursor"] = start_cursor
        return self._client.get("/v1/comments", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_comment(
        self,
        *,
        parent: dict[str, Any] | None = None,
        discussion_id: str | None = None,
        rich_text: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create a comment under a page parent or existing discussion."""
        if parent is None and discussion_id is None:
            raise ValueError("either parent or discussion_id must be provided")
        if not rich_text:
            raise ValueError("rich_text must be a non-empty list")
        payload: dict[str, Any] = {"rich_text": rich_text}
        if parent is not None:
            payload["parent"] = parent
        if discussion_id is not None:
            payload["discussion_id"] = discussion_id
        return self._client.post("/v1/comments", json=payload).json()

    # MARK: - Internal

    @staticmethod
    def _summarize_search_results(
        payload: dict[str, Any],
        *,
        include_ids: bool,
    ) -> dict[str, Any]:
        summaries: list[dict[str, Any]] = []
        raw_results: Any = payload.get("results", []) or []
        results: list[Any] = cast("list[Any]", raw_results) if isinstance(raw_results, list) else []
        for index, raw_item in enumerate(results, start=1):
            if not isinstance(raw_item, dict):
                continue
            item: dict[str, Any] = cast("dict[str, Any]", raw_item)
            object_type: Any = item.get("object", "")
            ref_prefix = "page" if object_type == "page" else "result"
            summary: dict[str, Any] = {
                f"{ref_prefix}_ref": f"{ref_prefix}_{index}",
                "object": object_type,
                "title": _extract_notion_title(item),
                "url": item.get("url", ""),
                "last_edited_time": item.get("last_edited_time", ""),
                "archived": item.get("archived", False),
            }
            parent: Any = item.get("parent")
            if isinstance(parent, dict):
                parent_dict: dict[str, Any] = cast("dict[str, Any]", parent)
                summary["parent_type"] = parent_dict.get("type", "")
            if include_ids:
                summary["page_id"] = item.get("id", "")
            summaries.append(summary)
        result: dict[str, Any] = {"results": summaries}
        if "next_cursor" in payload:
            result["next_cursor"] = payload["next_cursor"]
        if "has_more" in payload:
            result["has_more"] = payload["has_more"]
        return result

    @staticmethod
    def _extract_page_id(candidate: Any) -> str:
        """Pull a Notion page/database ID from an arbitrary value.

        Accepts the raw Notion ID string, a result dict returned by
        :meth:`search`/:meth:`query_database` (looking up ``page_id`` or
        ``id``), or a list of such dicts.
        """
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("page_id must be a non-empty string")
            return candidate
        if isinstance(candidate, dict):
            candidate_dict: dict[str, Any] = cast("dict[str, Any]", candidate)
            for key in ("page_id", "id"):
                value: Any = candidate_dict.get(key)
                if isinstance(value, str) and value:
                    return value
        if isinstance(candidate, list | tuple):
            sequence: list[Any] | tuple[Any, ...] = cast("list[Any] | tuple[Any, ...]", candidate)
            for item in sequence:
                try:
                    return NotionToolSet._extract_page_id(item)
                except ValueError:
                    continue
        raise ValueError(f"could not extract Notion page id from: {candidate!r}")


def _extract_notion_title(item: dict[str, Any]) -> str:
    """Pull the human title out of a Notion search result item."""
    object_type: Any = item.get("object", "")
    if object_type == "database":
        title_parts: Any = item.get("title") or []
        return _join_rich_text(title_parts)
    properties: Any = item.get("properties") or {}
    if not isinstance(properties, dict):
        return ""
    properties_dict: dict[str, Any] = cast("dict[str, Any]", properties)
    for prop in properties_dict.values():
        if isinstance(prop, dict):
            prop_dict: dict[str, Any] = cast("dict[str, Any]", prop)
            if prop_dict.get("type") == "title":
                return _join_rich_text(prop_dict.get("title") or [])
    return ""


def _join_rich_text(parts: Any) -> str:
    pieces: list[str] = []
    if not isinstance(parts, list):
        return ""
    parts_list: list[Any] = cast("list[Any]", parts)
    for part in parts_list:
        if isinstance(part, dict):
            part_dict: dict[str, Any] = cast("dict[str, Any]", part)
            nested_text: dict[str, Any] = part_dict.get("text", {})
            text: Any = part_dict.get("plain_text") or nested_text.get("content", "")
            if isinstance(text, str):
                pieces.append(text)
    return "".join(pieces)
