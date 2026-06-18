"""Atlassian Confluence Cloud REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_CONTENT_OUTPUT, SEARCH_CONTENT_OUTPUT, SEARCH_OUTPUT


@toolset(prefix="confluence")
class ConfluenceToolSet:
    """A connector for Confluence Cloud REST API v1.

    Args:
        base_url: Confluence site URL, e.g. ``https://acme.atlassian.net``.
            The ``/wiki`` prefix is added automatically.
        email: Atlassian account email (used as the basic-auth username).
        api_token: Atlassian API token. Never logged.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="confluence",
        display_name="Confluence",
        version="0.1.0",
        description="Search and manage Confluence spaces, pages, comments, and labels.",
        auth_modes=(AuthMode.BASIC,),
        scopes={
            "read:confluence-content.all": "Read pages, blogposts, and attachments.",
            "write:confluence-content": "Create and update content.",
            "write:confluence-space": "Create and update spaces.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developer.atlassian.com/cloud/confluence/rest/v1/intro/",
        homepage_url="https://www.atlassian.com/software/confluence",
        tags=("wiki", "atlassian"),
    )

    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        api_token: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not email:
            raise ValueError("email is required")
        if not api_token:
            raise ValueError("api_token is required")
        self.connection = connection
        site = base_url.rstrip("/")
        if not site.endswith("/wiki"):
            site = f"{site}/wiki"
        self._client = HttpClient(
            base_url=site,
            auth=BasicAuth(email, api_token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Identity

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_current_user(self) -> dict[str, Any]:
        """Return the authenticated user."""
        return self._client.get("/rest/api/user/current").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self, account_id: str) -> dict[str, Any]:
        """Return a user by ``accountId``."""
        if not account_id:
            raise ValueError("account_id must be a non-empty string")
        return self._client.get(
            "/rest/api/user",
            params={"accountId": account_id},
        ).json()

    # MARK: - Spaces

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_spaces(
        self,
        *,
        space_key: list[str] | None = None,
        type: str | None = None,
        status: str | None = None,
        start: int = 0,
        limit: int = 25,
    ) -> dict[str, Any]:
        """List Confluence spaces.

        Returns the raw Confluence ``{"results": [...], "size": ..., ...}``
        response. Each result carries ``key`` (e.g. ``ENG``) which is the
        canonical handle to pass to :meth:`get_space` and content tools.
        """
        if limit < 1 or limit > 250:
            raise ValueError("limit must be between 1 and 250")
        params: dict[str, Any] = {"start": start, "limit": limit}
        if space_key is not None:
            params["spaceKey"] = space_key
        if type is not None:
            params["type"] = type
        if status is not None:
            params["status"] = status
        return self._client.get("/rest/api/space", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_space(self, space_key: str) -> dict[str, Any]:
        """Return one space by key."""
        if not space_key:
            raise ValueError("space_key must be a non-empty string")
        return self._client.get(f"/rest/api/space/{space_key}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_space(
        self,
        *,
        key: str,
        name: str,
        description: str | None = None,
        private: bool = False,
    ) -> dict[str, Any]:
        """Create a new space."""
        if not key or not name:
            raise ValueError("key and name are required")
        payload: dict[str, Any] = {"key": key, "name": name}
        if description is not None:
            payload["description"] = {"plain": {"value": description, "representation": "plain"}}
        path = "/rest/api/space/_private" if private else "/rest/api/space"
        return self._client.post(path, json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_space(self, space_key: str) -> dict[str, Any]:
        """Schedule a space for deletion.

        Destructive: returns a long-running task descriptor. The space and
        all its content are queued for removal. Confirm with the user
        first.
        """
        if not space_key:
            raise ValueError("space_key must be a non-empty string")
        return self._client.delete(f"/rest/api/space/{space_key}").json()

    # MARK: - Content (pages and blog posts)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_CONTENT_OUTPUT)
    def list_content(
        self,
        *,
        type: str = "page",
        space_key: str | None = None,
        title: str | None = None,
        status: str | None = None,
        expand: str | None = None,
        start: int = 0,
        limit: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Confluence content (pages, blog posts, comments, attachments).

        By default returns compact summaries with a stable ``page_ref``
        (``page_1``, ``page_2``, ...) plus title, type, space key, version
        number, and the web URL. Confluence numeric content IDs are
        internal handles and are omitted unless ``include_ids=True``. Set
        ``include_metadata=False`` to receive the raw Confluence response
        including pagination cursors.
        """
        if type not in {"page", "blogpost", "comment", "attachment"}:
            raise ValueError("type must be page/blogpost/comment/attachment")
        params: dict[str, Any] = {"type": type, "start": start, "limit": limit}
        if space_key is not None:
            params["spaceKey"] = space_key
        if title is not None:
            params["title"] = title
        if status is not None:
            params["status"] = status
        if expand is not None:
            params["expand"] = expand
        response = self._client.get("/rest/api/content", params=params).json()
        if not include_metadata:
            return response
        return self._summarize_content(response, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_content(
        self,
        content_id: Any,
        *,
        expand: str | None = None,
        version: int | None = None,
    ) -> dict[str, Any]:
        """Return one content item by ID.

        ``content_id`` accepts the raw numeric ID string, a result dict
        from :meth:`list_content`/:meth:`search` (``include_ids=True``), or
        a list of such dicts.
        """
        resolved = self._extract_content_id(content_id)
        params: dict[str, Any] = {}
        if expand is not None:
            params["expand"] = expand
        if version is not None:
            params["version"] = version
        return self._client.get(
            f"/rest/api/content/{resolved}",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_page(
        self,
        *,
        space_key: str,
        title: str,
        body: str,
        parent_id: str | None = None,
        representation: str = "storage",
    ) -> dict[str, Any]:
        """Create a Confluence page.

        Returns the new page resource (``id``, ``title``, ``_links.webui``).
        """
        if not space_key or not title or not body:
            raise ValueError("space_key, title, and body are required")
        if representation not in {"storage", "wiki", "view"}:
            raise ValueError("representation must be storage/wiki/view")
        payload: dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {
                representation: {"value": body, "representation": representation},
            },
        }
        if parent_id is not None:
            payload["ancestors"] = [{"id": parent_id}]
        return self._client.post("/rest/api/content", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_page(
        self,
        content_id: Any,
        *,
        title: str,
        body: str,
        version: int,
        representation: str = "storage",
    ) -> dict[str, Any]:
        """Update a page.

        ``content_id`` accepts the raw numeric ID string or a dict/list
        returned by :meth:`list_content`/:meth:`search`/:meth:`get_content`.
        ``version`` is the new version number (previous + 1).
        """
        resolved = self._extract_content_id(content_id)
        if not title or not body:
            raise ValueError("title and body are required")
        payload: dict[str, Any] = {
            "id": resolved,
            "type": "page",
            "title": title,
            "version": {"number": version},
            "body": {
                representation: {"value": body, "representation": representation},
            },
        }
        return self._client.put(f"/rest/api/content/{resolved}", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_content(self, content_id: Any) -> dict[str, Any]:
        """Trash a content item.

        Destructive: ``status=trashed`` initially; call again to purge.
        ``content_id`` accepts the raw numeric ID string or a dict/list
        from :meth:`list_content`/:meth:`search`/:meth:`get_content`.
        """
        resolved = self._extract_content_id(content_id)
        response = self._client.delete(f"/rest/api/content/{resolved}")
        return {"id": resolved, "deleted": True, "status": response.status}

    # MARK: - Children, versions, labels

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_children(
        self,
        content_id: Any,
        *,
        type: str = "page",
        start: int = 0,
        limit: int = 25,
        expand: str | None = None,
    ) -> dict[str, Any]:
        """List child content under a page or blog post.

        ``content_id`` accepts the raw numeric ID string or a dict/list
        from :meth:`list_content`/:meth:`search`.
        """
        resolved = self._extract_content_id(content_id)
        params: dict[str, Any] = {"start": start, "limit": limit}
        if expand is not None:
            params["expand"] = expand
        return self._client.get(
            f"/rest/api/content/{resolved}/child/{type}",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_versions(
        self,
        content_id: Any,
        *,
        start: int = 0,
        limit: int = 25,
    ) -> dict[str, Any]:
        """List versions of a content item.

        ``content_id`` accepts the raw numeric ID string or a dict/list
        from :meth:`list_content`/:meth:`search`.
        """
        resolved = self._extract_content_id(content_id)
        return self._client.get(
            f"/rest/api/content/{resolved}/version",
            params={"start": start, "limit": limit},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_labels(
        self,
        content_id: Any,
        *,
        start: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        """List labels attached to a content item.

        ``content_id`` accepts the raw numeric ID string or a dict/list
        from :meth:`list_content`/:meth:`search`.
        """
        resolved = self._extract_content_id(content_id)
        return self._client.get(
            f"/rest/api/content/{resolved}/label",
            params={"start": start, "limit": limit},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_label(self, content_id: Any, label: str, *, prefix: str = "global") -> dict[str, Any]:
        """Add a label to a content item.

        ``content_id`` accepts the raw numeric ID string or a dict/list
        from :meth:`list_content`/:meth:`search`.
        """
        resolved = self._extract_content_id(content_id)
        if not label:
            raise ValueError("label must be a non-empty string")
        return self._client.post(
            f"/rest/api/content/{resolved}/label",
            json=[{"prefix": prefix, "name": label}],
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def remove_label(self, content_id: Any, label: str) -> dict[str, Any]:
        """Remove a label from a content item.

        Destructive: the label/content association is deleted.
        """
        resolved = self._extract_content_id(content_id)
        if not label:
            raise ValueError("label must be a non-empty string")
        self._client.delete(
            f"/rest/api/content/{resolved}/label",
            params={"name": label},
        )
        return {"id": resolved, "label": label, "removed": True}

    # MARK: - Comments

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_comments(
        self,
        content_id: Any,
        *,
        location: str | None = None,
        depth: str | None = None,
        start: int = 0,
        limit: int = 25,
    ) -> dict[str, Any]:
        """List comments on a content item.

        ``content_id`` accepts the raw numeric ID string or a dict/list
        from :meth:`list_content`/:meth:`search`.
        """
        resolved = self._extract_content_id(content_id)
        params: dict[str, Any] = {"start": start, "limit": limit}
        if location is not None:
            params["location"] = location
        if depth is not None:
            params["depth"] = depth
        return self._client.get(
            f"/rest/api/content/{resolved}/child/comment",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_comment(
        self,
        *,
        container_id: str,
        body: str,
        representation: str = "storage",
    ) -> dict[str, Any]:
        """Create a comment on a page or blog post."""
        if not container_id or not body:
            raise ValueError("container_id and body must be non-empty")
        payload = {
            "type": "comment",
            "container": {"id": container_id, "type": "page"},
            "body": {
                representation: {"value": body, "representation": representation},
            },
        }
        return self._client.post("/rest/api/content", json=payload).json()

    # MARK: - Search

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SEARCH_OUTPUT)
    def search(
        self,
        cql: str,
        *,
        start: int = 0,
        limit: int = 25,
        expand: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Run a CQL (Confluence Query Language) search.

        Best first tool for finding pages or other content. By default
        returns compact summaries with a stable ``page_ref`` (``page_1``,
        ``page_2``, ...) plus title, type, space key, and web URL.
        Confluence numeric IDs are internal handles and are omitted unless
        ``include_ids=True``. Set ``include_metadata=False`` to receive the
        raw Confluence search response.
        """
        if not cql:
            raise ValueError("cql must be a non-empty string")
        params: dict[str, Any] = {"cql": cql, "start": start, "limit": limit}
        if expand is not None:
            params["expand"] = expand
        response = self._client.get("/rest/api/search", params=params).json()
        if not include_metadata:
            return response
        return self._summarize_search(response, include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SEARCH_CONTENT_OUTPUT)
    def search_content(
        self,
        cql: str,
        *,
        start: int = 0,
        limit: int = 25,
        expand: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Run a CQL search restricted to content (pages/blog posts/comments).

        Same summary behavior as :meth:`search`. Set
        ``include_metadata=False`` to receive the raw Confluence response.
        """
        if not cql:
            raise ValueError("cql must be a non-empty string")
        params: dict[str, Any] = {"cql": cql, "start": start, "limit": limit}
        if expand is not None:
            params["expand"] = expand
        response = self._client.get("/rest/api/content/search", params=params).json()
        if not include_metadata:
            return response
        return self._summarize_content(response, include_ids=include_ids)

    # MARK: - Attachments

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_attachments(
        self,
        content_id: Any,
        *,
        start: int = 0,
        limit: int = 50,
        media_type: str | None = None,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """List attachments on a content item.

        ``content_id`` accepts the raw numeric ID string or a dict/list
        from :meth:`list_content`/:meth:`search`.
        """
        resolved = self._extract_content_id(content_id)
        params: dict[str, Any] = {"start": start, "limit": limit}
        if media_type is not None:
            params["mediaType"] = media_type
        if filename is not None:
            params["filename"] = filename
        return self._client.get(
            f"/rest/api/content/{resolved}/child/attachment",
            params=params,
        ).json()

    # MARK: - Internal

    @staticmethod
    def _summarize_content(
        payload: dict[str, Any],
        *,
        include_ids: bool,
    ) -> dict[str, Any]:
        summaries: list[dict[str, Any]] = []
        results: list[Any] = payload.get("results", []) or []
        for index, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                continue
            item_dict = cast("dict[str, Any]", item)
            summaries.append(_content_item_summary(item_dict, index=index, include_ids=include_ids))
        result: dict[str, Any] = {"results": summaries}
        for key in ("start", "limit", "size", "_links"):
            if key in payload:
                result[key] = payload[key]
        return result

    @staticmethod
    def _summarize_search(
        payload: dict[str, Any],
        *,
        include_ids: bool,
    ) -> dict[str, Any]:
        summaries: list[dict[str, Any]] = []
        results: list[Any] = payload.get("results", []) or []
        for index, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                continue
            item_dict = cast("dict[str, Any]", item)
            content: Any = item_dict.get("content")
            summary: dict[str, Any]
            if isinstance(content, dict):
                content_dict = cast("dict[str, Any]", content)
                summary = _content_item_summary(content_dict, index=index, include_ids=include_ids)
                summary["excerpt"] = item_dict.get("excerpt", "")
                summary["resultGlobalContainer"] = item_dict.get("resultGlobalContainer", "")
            else:
                summary = {
                    "page_ref": f"page_{index}",
                    "title": item_dict.get("title", ""),
                    "type": item_dict.get("entityType", item_dict.get("type", "")),
                    "url": item_dict.get("url", ""),
                    "excerpt": item_dict.get("excerpt", ""),
                }
            summaries.append(summary)
        result: dict[str, Any] = {"results": summaries}
        for key in ("start", "limit", "size", "totalSize", "cqlQuery"):
            if key in payload:
                result[key] = payload[key]
        return result

    @staticmethod
    def _extract_content_id(candidate: Any) -> str:
        """Pull a Confluence content ID from an arbitrary value.

        Accepts the raw numeric ID string, a result dict from
        :meth:`list_content`/:meth:`search`/:meth:`get_content` (looking up
        ``content_id``, ``id``, or ``page_id``), or a list of such dicts.
        """
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("content_id must be a non-empty string")
            return candidate
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return str(candidate)
        if isinstance(candidate, dict):
            candidate_dict = cast("dict[Any, Any]", candidate)
            for key in ("content_id", "page_id", "id"):
                value: Any = candidate_dict.get(key)
                if isinstance(value, str) and value:
                    return value
                if isinstance(value, int) and not isinstance(value, bool):
                    return str(value)
        if isinstance(candidate, list | tuple):
            candidate_seq = cast("list[Any] | tuple[Any, ...]", candidate)
            for item in candidate_seq:
                try:
                    return ConfluenceToolSet._extract_content_id(item)
                except ValueError:
                    continue
        raise ValueError(f"could not extract Confluence content id from: {candidate!r}")


def _content_item_summary(
    item: dict[str, Any],
    *,
    index: int,
    include_ids: bool,
) -> dict[str, Any]:
    space_block: Any = item.get("space")
    version_block: Any = item.get("version")
    links_block: Any = item.get("_links")
    space_key: Any = (
        cast("dict[str, Any]", space_block).get("key", "") if isinstance(space_block, dict) else ""
    )
    version_number: Any = (
        cast("dict[str, Any]", version_block).get("number", 0)
        if isinstance(version_block, dict)
        else 0
    )
    url: Any = (
        cast("dict[str, Any]", links_block).get("webui", "")
        if isinstance(links_block, dict)
        else ""
    )
    summary: dict[str, Any] = {
        "page_ref": f"page_{index}",
        "title": item.get("title", ""),
        "type": item.get("type", ""),
        "status": item.get("status", ""),
        "space_key": space_key,
        "version": version_number,
        "url": url,
    }
    if include_ids:
        summary["content_id"] = item.get("id", "")
    return summary
