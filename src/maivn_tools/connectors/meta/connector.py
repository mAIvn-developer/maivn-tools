"""Meta Graph API connector (Facebook Pages + user-managed assets)."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_PAGE_POSTS_OUTPUT, LIST_POST_COMMENTS_OUTPUT

# Default Graph API version. v19.0 was sunset on 2026-05-21; this must stay a
# currently-supported version. v24.0 gives headroom without being bleeding-edge
# (latest is v25.0). See the changelog for active-version windows:
# https://developers.facebook.com/docs/graph-api/changelog/versions/
_API_VERSION = "v24.0"


@toolset(prefix="meta")
class MetaToolSet:
    """A connector for the Meta Graph API (Facebook).

    Args:
        access_token: User or page access token. Page tokens are required
            for most page-write operations.
        graph_version: Graph API version segment (e.g. ``"v24.0"``).
    """

    metadata = ProviderMetadata(
        name="meta",
        display_name="Meta (Facebook)",
        version="0.1.0",
        description="Facebook Pages, posts, comments, insights, and user profile.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "pages_show_list": "List the pages a user manages.",
            "pages_read_engagement": "Read page posts and comments.",
            "pages_manage_posts": "Publish + delete page posts.",
            "pages_manage_engagement": "Reply to comments.",
            "read_insights": "Read page / post insights.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developers.facebook.com/docs/graph-api/",
        homepage_url="https://www.facebook.com/",
        tags=("social-media", "meta"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        graph_version: str = _API_VERSION,
        base_url: str = "https://graph.facebook.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self.connection = connection
        self._version = graph_version
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(access_token, query_param="access_token"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _path(self, suffix: str) -> str:
        return f"/{self._version}{suffix}"

    # MARK: - Internal helpers

    @staticmethod
    def _select_post_id(candidate: Any) -> str:
        """Resolve a post ID from a string or a post dict returned by listings."""
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("post_id must be a non-empty string")
            return candidate
        if isinstance(candidate, dict):
            mapping = cast("dict[str, Any]", candidate)
            for key in ("post_id", "id"):
                value: Any = mapping.get(key)
                if isinstance(value, str) and value:
                    return value
        if isinstance(candidate, list) and candidate:
            return MetaToolSet._select_post_id(candidate[0])
        raise ValueError("could not resolve post_id from input")

    @classmethod
    def _post_summary(
        cls,
        post: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        post_id = post.get("id", "")
        summary: dict[str, Any] = {
            "post_ref": f"post_{index}",
            "message": post.get("message", "") or post.get("story", ""),
            "posted_at": post.get("created_time", ""),
            "permalink_url": post.get("permalink_url", ""),
        }
        if include_ids:
            summary["post_id"] = post_id
        return summary

    @classmethod
    def _comment_summary(
        cls,
        comment: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        from_field: Any = comment.get("from") or {}
        author: Any = (
            cast("dict[str, Any]", from_field).get("name", "")
            if isinstance(from_field, dict)
            else ""
        )
        summary: dict[str, Any] = {
            "comment_ref": f"comment_{index}",
            "author": author,
            "message": comment.get("message", ""),
            "posted_at": comment.get("created_time", ""),
            "like_count": comment.get("like_count", 0),
        }
        if include_ids:
            summary["comment_id"] = comment.get("id", "")
        return summary

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_me(self, *, fields: list[str] | None = None) -> dict[str, Any]:
        """Return the authenticated user's profile (``/me``).

        Returns the raw Graph user resource. Use ``fields`` to control which
        fields are returned (e.g. ``["id", "name", "email"]``).
        """
        params: dict[str, Any] = {}
        if fields is not None:
            params["fields"] = ",".join(fields)
        return self._client.get(self._path("/me"), params=params or None).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_accounts(self) -> dict[str, Any]:
        """List Facebook Pages managed by the authenticated user.

        Returns ``{"data": [<page>, ...]}`` where each page carries the
        ``access_token`` you need for page-write operations.
        """
        return self._client.get(self._path("/me/accounts")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_page(self, page_id: str, *, fields: list[str] | None = None) -> dict[str, Any]:
        """Return one Page by ID.

        Returns the Graph Page resource with the requested ``fields``.
        """
        if not page_id:
            raise ValueError("page_id must be a non-empty string")
        params: dict[str, Any] = {}
        if fields is not None:
            params["fields"] = ",".join(fields)
        return self._client.get(
            self._path(f"/{page_id}"),
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_PAGE_POSTS_OUTPUT)
    def list_page_posts(
        self,
        page_id: str,
        *,
        limit: int = 10,
        after: str | None = None,
        fields: list[str] | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List posts published on a Page.

        Best first tool for Facebook page triage. Default mode returns
        compact summaries: ``post_ref`` (stable ``post_1``, ``post_2``,
        ...), ``message``, ``posted_at``, and ``permalink_url``. Raw Graph
        post IDs are omitted by default; set ``include_ids=True`` only when
        a follow-up tool (``delete_post``, ``get_post_insights``) needs the
        raw ``post_id``. Set ``include_metadata=False`` for the raw Graph
        response.
        """
        if not page_id:
            raise ValueError("page_id must be a non-empty string")
        params: dict[str, Any] = {"limit": limit}
        if after is not None:
            params["after"] = after
        merged_fields = list(fields) if fields else []
        if include_metadata:
            for needed in ("message", "story", "created_time", "permalink_url"):
                if needed not in merged_fields:
                    merged_fields.append(needed)
        if merged_fields:
            params["fields"] = ",".join(merged_fields)
        payload: dict[str, Any] = self._client.get(
            self._path(f"/{page_id}/posts"),
            params=params,
        ).json()
        if not include_metadata:
            return payload
        summaries: list[dict[str, Any]] = []
        data: Any = payload.get("data", [])
        for index, post in enumerate(data, start=1):
            if not isinstance(post, dict):
                continue
            post_dict = cast("dict[str, Any]", post)
            summaries.append(self._post_summary(post_dict, index=index, include_ids=include_ids))
        return {
            "posts": summaries,
            "paging": payload.get("paging"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def publish_page_post(
        self,
        page_id: str,
        *,
        message: str | None = None,
        link: str | None = None,
        published: bool = True,
        scheduled_publish_time: int | None = None,
    ) -> dict[str, Any]:
        """Publish a new Page post.

        Returns the new post resource (``id``, optional ``post_id``). To
        schedule, pass a future ``scheduled_publish_time`` (Unix seconds);
        the call is automatically marked unpublished.
        """
        if not page_id:
            raise ValueError("page_id must be a non-empty string")
        if not message and not link:
            raise ValueError("provide message or link")
        body: dict[str, Any] = {"published": published}
        if message is not None:
            body["message"] = message
        if link is not None:
            body["link"] = link
        if scheduled_publish_time is not None:
            body["scheduled_publish_time"] = scheduled_publish_time
            body["published"] = False
        return self._client.post(
            self._path(f"/{page_id}/feed"),
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_post(self, post: str | dict[str, Any]) -> dict[str, Any]:
        """Permanently delete a Facebook post.

        Accepts a raw ``post_id`` string OR a post dict from
        ``list_page_posts`` (looks up ``post_id`` / ``id``). Destructive
        and not reversible — confirm with the user.
        """
        post_id = self._select_post_id(post)
        return self._client.delete(self._path(f"/{post_id}")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_POST_COMMENTS_OUTPUT)
    def list_post_comments(
        self,
        post_id: str,
        *,
        limit: int = 10,
        after: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List comments on a post.

        Default returns compact summaries: ``comment_ref``, ``author``
        (name), ``message``, ``posted_at``, ``like_count``. Raw comment IDs
        are omitted unless ``include_ids=True``. ``include_metadata=False``
        returns the raw Graph response.
        """
        if not post_id:
            raise ValueError("post_id must be a non-empty string")
        params: dict[str, Any] = {"limit": limit}
        if include_metadata:
            params["fields"] = "from,message,created_time,like_count"
        if after is not None:
            params["after"] = after
        payload: dict[str, Any] = self._client.get(
            self._path(f"/{post_id}/comments"),
            params=params,
        ).json()
        if not include_metadata:
            return payload
        summaries: list[dict[str, Any]] = []
        data: Any = payload.get("data", [])
        for index, comment in enumerate(data, start=1):
            if not isinstance(comment, dict):
                continue
            comment_dict = cast("dict[str, Any]", comment)
            summaries.append(
                self._comment_summary(comment_dict, index=index, include_ids=include_ids)
            )
        return {
            "comments": summaries,
            "paging": payload.get("paging"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def reply_to_comment(self, comment_id: str, *, message: str) -> dict[str, Any]:
        """Reply to a Facebook comment.

        Returns the new comment resource (``id``). ``comment_id`` is the
        Graph internal ID returned by ``list_post_comments(include_ids=True)``.
        """
        if not comment_id or not message:
            raise ValueError("comment_id and message must be non-empty")
        return self._client.post(
            self._path(f"/{comment_id}/comments"),
            json={"message": message},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_comment(self, comment_id: str) -> dict[str, Any]:
        """Permanently delete a Facebook comment.

        Destructive and not reversible. Confirm with the user before
        calling.
        """
        if not comment_id:
            raise ValueError("comment_id must be a non-empty string")
        return self._client.delete(self._path(f"/{comment_id}")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_page_insights(
        self,
        page_id: str,
        *,
        metric: list[str],
        period: str = "day",
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """Read Page-level insights.

        Returns the raw Graph insights response. ``metric`` is the list of
        insight names (e.g. ``["page_impressions", "page_engaged_users"]``).
        """
        if not page_id or not metric:
            raise ValueError("page_id and metric must be non-empty")
        params: dict[str, Any] = {"metric": ",".join(metric), "period": period}
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        return self._client.get(
            self._path(f"/{page_id}/insights"),
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_post_insights(
        self,
        post_id: str,
        *,
        metric: list[str],
    ) -> dict[str, Any]:
        """Read insights for one post.

        Returns the raw Graph insights response. ``metric`` is the list of
        post-level insight names (e.g. ``["post_impressions"]``).
        """
        if not post_id or not metric:
            raise ValueError("post_id and metric must be non-empty")
        return self._client.get(
            self._path(f"/{post_id}/insights"),
            params={"metric": ",".join(metric)},
        ).json()
