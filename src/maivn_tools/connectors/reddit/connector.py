"""Reddit API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast
from urllib.parse import urlencode

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="reddit")
class RedditToolSet:
    """A connector for the Reddit OAuth API.

    Args:
        access_token: OAuth 2.0 access token.
        user_agent: Reddit requires a descriptive ``User-Agent`` header
            (``platform:appid:version (by /u/handle)``).
    """

    metadata = ProviderMetadata(
        name="reddit",
        display_name="Reddit",
        version="0.1.0",
        description="Subreddits, posts, comments, voting, and user feeds.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "identity": "Account identity.",
            "read": "Read posts and comments.",
            "submit": "Submit posts.",
            "edit": "Edit user content.",
            "vote": "Cast votes.",
            "subscribe": "Subscribe to subreddits.",
            "history": "Read user history.",
            "mysubreddits": "List subscribed subreddits.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://www.reddit.com/dev/api",
        homepage_url="https://www.reddit.com/",
        tags=("social-media", "discussion"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        user_agent: str,
        base_url: str = "https://oauth.reddit.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        if not user_agent:
            raise ValueError("user_agent is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(access_token),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "User-Agent": user_agent,
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _post_form(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = urlencode(payload).encode("utf-8")
        response = self._client.post(
            path,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        result: dict[str, Any] = response.json()
        return result

    # MARK: - Internal helpers

    @staticmethod
    def _select_thing_id(candidate: object) -> str:
        """Resolve a Reddit fullname (``t3_...``/``t1_...``) from input.

        Accepts a raw string ``thing_id``, or a post/comment dict from
        listing endpoints (looks up ``thing_id`` / ``name`` / ``id`` /
        ``post_ref`` shapes).
        """
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("thing_id must be a non-empty string")
            return candidate
        if isinstance(candidate, dict):
            mapping = cast(dict[str, Any], candidate)
            for key in ("thing_id", "name", "fullname"):
                value = mapping.get(key)
                if isinstance(value, str) and value:
                    return value
            data = mapping.get("data")
            if isinstance(data, dict):
                nested = cast(dict[str, Any], data)
                for key in ("name", "thing_id", "fullname"):
                    value = nested.get(key)
                    if isinstance(value, str) and value:
                        return value
        if isinstance(candidate, list) and candidate:
            items = cast(list[Any], candidate)
            return RedditToolSet._select_thing_id(items[0])
        raise ValueError("could not resolve thing_id from input")

    @classmethod
    def _post_summary(
        cls,
        listing_child: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        data: dict[str, Any] = listing_child.get("data") or {}
        summary: dict[str, Any] = {
            "post_ref": f"post_{index}",
            "title": data.get("title", ""),
            "author": data.get("author", ""),
            "subreddit": data.get("subreddit", ""),
            "posted_at": data.get("created_utc", 0),
            "score": data.get("score", 0),
            "num_comments": data.get("num_comments", 0),
            "url": f"https://www.reddit.com{data.get('permalink', '')}"
            if data.get("permalink")
            else data.get("url", ""),
            "selftext": data.get("selftext", "")[:500] if data.get("selftext") else "",
        }
        if include_ids:
            summary["thing_id"] = data.get("name", "")
            summary["post_id"] = data.get("id", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_me(self) -> dict[str, Any]:
        """Return the authenticated user's identity.

        Returns ``{"name": ..., "id": ..., "icon_img": ..., ...}``. Cheap,
        useful as a connection sanity check.
        """
        return self._client.get("/api/v1/me").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_subscribed_subreddits(
        self,
        *,
        limit: int = 25,
        after: str | None = None,
    ) -> dict[str, Any]:
        """List subreddits the user is subscribed to.

        Returns the raw Reddit listing response. Each child carries a
        ``data.display_name`` (the subreddit name) and ``data.url``.
        """
        params: dict[str, Any] = {"limit": limit}
        if after is not None:
            params["after"] = after
        return self._client.get("/subreddits/mine/subscriber", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_subreddit_about(self, subreddit: str) -> dict[str, Any]:
        """Return metadata for one subreddit.

        Returns the raw Reddit subreddit ``about`` resource (subscribers,
        public description, rules summary, etc.).
        """
        if not subreddit:
            raise ValueError("subreddit must be a non-empty string")
        return self._client.get(f"/r/{subreddit}/about").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_subreddit_posts(
        self,
        subreddit: str,
        *,
        sort: str = "hot",
        limit: int = 10,
        after: str | None = None,
        time: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List posts from a subreddit.

        Best first tool for subreddit triage. ``sort`` is one of
        ``hot``/``new``/``top``/``rising``/``controversial``. Default
        returns compact summaries: ``post_ref`` (stable ``post_1`` ...),
        ``title``, ``author``, ``subreddit``, ``posted_at`` (Unix epoch),
        ``score``, ``num_comments``, ``url``, and a truncated
        ``selftext``. Raw Reddit fullnames (``t3_...``) are omitted
        unless ``include_ids=True``. Set ``include_metadata=False`` for
        the raw Reddit listing.
        """
        if not subreddit:
            raise ValueError("subreddit must be a non-empty string")
        if sort not in {"hot", "new", "top", "rising", "controversial"}:
            raise ValueError("sort must be hot/new/top/rising/controversial")
        params: dict[str, Any] = {"limit": limit}
        if after is not None:
            params["after"] = after
        if time is not None:
            params["t"] = time
        payload: dict[str, Any] = self._client.get(f"/r/{subreddit}/{sort}", params=params).json()
        if not include_metadata:
            return payload
        data_obj = payload.get("data")
        data: dict[str, Any] = cast(dict[str, Any], data_obj) if isinstance(data_obj, dict) else {}
        children: list[Any] = data.get("children", [])
        summaries: list[dict[str, Any]] = []
        for index, child in enumerate(children, start=1):
            if not isinstance(child, dict):
                continue
            child_dict = cast(dict[str, Any], child)
            summaries.append(self._post_summary(child_dict, index=index, include_ids=include_ids))
        return {
            "posts": summaries,
            "after": data.get("after"),
            "before": data.get("before"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search(
        self,
        query: str,
        *,
        subreddit: str | None = None,
        sort: str = "relevance",
        limit: int = 10,
        after: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search Reddit posts (optionally scoped to a subreddit).

        Best first tool for Reddit search. Default returns compact
        ``post_ref`` summaries (same shape as ``list_subreddit_posts``).
        Raw fullnames are omitted unless ``include_ids=True``. Set
        ``include_metadata=False`` for the raw Reddit listing.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        if sort not in {"relevance", "hot", "top", "new", "comments"}:
            raise ValueError("sort must be relevance/hot/top/new/comments")
        params: dict[str, Any] = {"q": query, "sort": sort, "limit": limit}
        if after is not None:
            params["after"] = after
        path = f"/r/{subreddit}/search" if subreddit else "/search"
        if subreddit:
            params["restrict_sr"] = "true"
        payload: dict[str, Any] = self._client.get(path, params=params).json()
        if not include_metadata:
            return payload
        data_obj = payload.get("data")
        data: dict[str, Any] = cast(dict[str, Any], data_obj) if isinstance(data_obj, dict) else {}
        children: list[Any] = data.get("children", [])
        summaries: list[dict[str, Any]] = []
        for index, child in enumerate(children, start=1):
            if not isinstance(child, dict):
                continue
            child_dict = cast(dict[str, Any], child)
            summaries.append(self._post_summary(child_dict, index=index, include_ids=include_ids))
        return {
            "posts": summaries,
            "after": data.get("after"),
            "before": data.get("before"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_post(self, *, subreddit: str, post_id: str) -> dict[str, Any]:
        """Fetch a single post with its comment tree.

        Returns the raw Reddit response: a 2-element array of listings —
        the first is the post, the second is the top-level comment tree.
        """
        if not subreddit or not post_id:
            raise ValueError("subreddit and post_id are required")
        return self._client.get(f"/r/{subreddit}/comments/{post_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def submit_post(
        self,
        *,
        subreddit: str,
        title: str,
        kind: str = "self",
        text: str | None = None,
        url: str | None = None,
    ) -> dict[str, Any]:
        """Submit a self-post or link to a subreddit.

        Returns the Reddit ``api/submit`` response. ``kind="self"``
        requires ``text``; ``kind="link"`` requires ``url``.
        """
        if not subreddit or not title:
            raise ValueError("subreddit and title are required")
        if kind not in {"self", "link"}:
            raise ValueError("kind must be self or link")
        if kind == "self" and not text:
            raise ValueError("text is required when kind=self")
        if kind == "link" and not url:
            raise ValueError("url is required when kind=link")
        data: dict[str, Any] = {
            "sr": subreddit,
            "title": title,
            "kind": kind,
            "api_type": "json",
        }
        if text is not None:
            data["text"] = text
        if url is not None:
            data["url"] = url
        return self._post_form("/api/submit", data)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def submit_comment(
        self,
        *,
        parent: str | dict[str, Any],
        text: str,
    ) -> dict[str, Any]:
        """Reply to a post (``t3_...``) or comment (``t1_...``).

        ``parent`` accepts a raw fullname string OR a post dict from
        ``list_subreddit_posts`` / ``search`` (looks up ``thing_id`` /
        ``name`` / ``data.name``).
        """
        if not text:
            raise ValueError("text is required")
        parent_id = self._select_thing_id(parent)
        return self._post_form(
            "/api/comment",
            {"thing_id": parent_id, "text": text, "api_type": "json"},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def vote(
        self,
        *,
        thing: str | dict[str, Any],
        direction: int,
    ) -> dict[str, Any]:
        """Vote on a post or comment.

        ``direction`` is ``1`` (upvote), ``0`` (clear vote), or ``-1``
        (downvote). ``thing`` accepts a raw fullname string OR a post
        dict from listing endpoints.
        """
        if direction not in {1, 0, -1}:
            raise ValueError("direction must be 1, 0, or -1")
        thing_id = self._select_thing_id(thing)
        return self._post_form("/api/vote", {"id": thing_id, "dir": direction})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def save(
        self,
        thing: str | dict[str, Any],
        *,
        category: str | None = None,
    ) -> dict[str, Any]:
        """Save a post or comment to the user's saved list.

        ``thing`` accepts a raw fullname or a post dict from listings.
        """
        thing_id = self._select_thing_id(thing)
        payload: dict[str, Any] = {"id": thing_id}
        if category is not None:
            payload["category"] = category
        return self._post_form("/api/save", payload)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def unsave(self, thing: str | dict[str, Any]) -> dict[str, Any]:
        """Unsave a post or comment.

        ``thing`` accepts a raw fullname or a post dict from listings.
        """
        thing_id = self._select_thing_id(thing)
        return self._post_form("/api/unsave", {"id": thing_id})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def subscribe(self, subreddit: str, *, unsubscribe: bool = False) -> dict[str, Any]:
        """Subscribe to (or unsubscribe from) a subreddit.

        Pass ``unsubscribe=True`` to unsubscribe instead.
        """
        if not subreddit:
            raise ValueError("subreddit is required")
        return self._post_form(
            "/api/subscribe",
            {
                "action": "unsub" if unsubscribe else "sub",
                "sr_name": subreddit,
            },
        )

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_thing(self, thing: str | dict[str, Any]) -> dict[str, Any]:
        """Permanently delete a post or comment owned by the user.

        Accepts a raw fullname OR a post/comment dict from listings.
        Destructive and not reversible — confirm with the user.
        """
        thing_id = self._select_thing_id(thing)
        return self._post_form("/api/del", {"id": thing_id})
