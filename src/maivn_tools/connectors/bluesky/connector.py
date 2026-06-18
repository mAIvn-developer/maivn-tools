"""Bluesky AT Protocol connector."""

# pyright: strict

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import (
    GET_AUTHOR_FEED_OUTPUT,
    GET_FOLLOWERS_OUTPUT,
    GET_FOLLOWS_OUTPUT,
    GET_TIMELINE_OUTPUT,
    SEARCH_POSTS_OUTPUT,
)


@toolset(prefix="bluesky")
class BlueskyToolSet:
    """A connector for Bluesky's AT Protocol XRPC API.

    Args:
        access_jwt: Access JWT returned by ``com.atproto.server.createSession``
            (typically obtained from ``handle`` + app password).
        did: The authenticated user's DID (``did:plc:...``).
        service_url: PDS service URL (default ``https://bsky.social``).
    """

    metadata = ProviderMetadata(
        name="bluesky",
        display_name="Bluesky",
        version="0.1.0",
        description="Posts, feeds, follows, likes, and reposts via AT Protocol XRPC.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://docs.bsky.app/",
        homepage_url="https://bsky.app/",
        tags=("social-media", "atproto"),
    )

    def __init__(
        self,
        *,
        access_jwt: str,
        did: str,
        service_url: str = "https://bsky.social",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_jwt or not did:
            raise ValueError("access_jwt and did are required")
        self.connection = connection
        self._did = did
        self._client = HttpClient(
            base_url=service_url.rstrip("/"),
            auth=BearerTokenAuth(access_jwt),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @property
    def did(self) -> str:
        return self._did

    # MARK: - Internal helpers

    @staticmethod
    def _select_post_ref(candidate: Any) -> tuple[str, str]:
        """Return ``(uri, cid)`` for a post.

        Accepts a raw ``(uri, cid)`` dict, a post dict from
        ``search_posts``/``get_timeline`` (looks up ``post.uri``/``post.cid``
        or top-level ``uri``/``cid``), or a list of such dicts.
        """
        if isinstance(candidate, dict):
            candidate_dict = cast("dict[str, Any]", candidate)
            post = candidate_dict.get("post")
            if isinstance(post, dict):
                post_dict = cast("dict[str, Any]", post)
                uri = post_dict.get("uri")
                cid = post_dict.get("cid")
                if isinstance(uri, str) and uri and isinstance(cid, str) and cid:
                    return uri, cid
            uri = candidate_dict.get("uri")
            cid = candidate_dict.get("cid")
            if isinstance(uri, str) and uri and isinstance(cid, str) and cid:
                return uri, cid
        if isinstance(candidate, list) and candidate:
            candidate_list = cast("list[Any]", candidate)
            return BlueskyToolSet._select_post_ref(candidate_list[0])
        raise ValueError("could not resolve uri and cid from input")

    @staticmethod
    def _at_uri_to_rkey(uri: object) -> str:
        """Extract the rkey from an at:// URI (``at://did/collection/rkey``)."""
        if not isinstance(uri, str) or "/" not in uri:
            raise ValueError("uri must be an at:// URI")
        return uri.rsplit("/", 1)[-1]

    @staticmethod
    def _select_rkey(candidate: Any) -> str:
        """Resolve an rkey from a string, an at:// uri, or a post dict."""
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("rkey must be a non-empty string")
            if candidate.startswith("at://"):
                return BlueskyToolSet._at_uri_to_rkey(candidate)
            return candidate
        if isinstance(candidate, dict):
            candidate_dict = cast("dict[str, Any]", candidate)
            for key in ("rkey",):
                value = candidate_dict.get(key)
                if isinstance(value, str) and value:
                    return value
            post = candidate_dict.get("post")
            post_uri = cast("dict[str, Any]", post).get("uri") if isinstance(post, dict) else None
            uri = candidate_dict.get("uri") or post_uri
            if isinstance(uri, str) and uri:
                return BlueskyToolSet._at_uri_to_rkey(uri)
        if isinstance(candidate, list) and candidate:
            candidate_list = cast("list[Any]", candidate)
            return BlueskyToolSet._select_rkey(candidate_list[0])
        raise ValueError("could not resolve rkey from input")

    @classmethod
    def _post_summary(
        cls,
        feed_view: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        raw_post = feed_view.get("post")
        post: dict[str, Any] = (
            cast("dict[str, Any]", raw_post) if isinstance(raw_post, dict) else feed_view
        )
        author_raw = post.get("author")
        record_raw = post.get("record")
        author: dict[str, Any] = (
            cast("dict[str, Any]", author_raw) if isinstance(author_raw, dict) else {}
        )
        record: dict[str, Any] = (
            cast("dict[str, Any]", record_raw) if isinstance(record_raw, dict) else {}
        )
        handle = author.get("handle", "")
        uri = post.get("uri", "")
        rkey = ""
        if isinstance(uri, str) and uri.startswith("at://") and "/" in uri:
            rkey = uri.rsplit("/", 1)[-1]
        url = f"https://bsky.app/profile/{handle}/post/{rkey}" if handle and rkey else ""
        text = record.get("text", "")
        summary: dict[str, Any] = {
            "post_ref": f"post_{index}",
            "author": handle,
            "author_name": author.get("displayName", ""),
            "text": text,
            "posted_at": record.get("createdAt", ""),
            "like_count": post.get("likeCount", 0),
            "repost_count": post.get("repostCount", 0),
            "reply_count": post.get("replyCount", 0),
            "url": url,
        }
        if include_ids:
            summary["uri"] = uri
            summary["cid"] = post.get("cid", "")
            summary["rkey"] = rkey
        return summary

    @classmethod
    def _actor_summary(
        cls,
        actor: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        handle = actor.get("handle", "")
        summary: dict[str, Any] = {
            "user_ref": f"user_{index}",
            "handle": handle,
            "name": actor.get("displayName", ""),
            "description": actor.get("description", ""),
            "url": f"https://bsky.app/profile/{handle}" if handle else "",
        }
        if include_ids:
            summary["did"] = actor.get("did", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_profile(self, actor: str) -> dict[str, Any]:
        """Return a Bluesky profile by DID or handle.

        Returns the raw Bluesky actor profile (``did``, ``handle``,
        ``displayName``, ``description``, follower/following counts).
        """
        if not actor:
            raise ValueError("actor is required")
        profile: dict[str, Any] = self._client.get(
            "/xrpc/app.bsky.actor.getProfile", params={"actor": actor}
        ).json()
        return profile

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(GET_TIMELINE_OUTPUT)
    def get_timeline(
        self,
        *,
        limit: int = 25,
        cursor: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Return the authenticated user's home timeline.

        Default returns compact summaries: ``post_ref`` (stable
        ``post_1`` ...), ``author`` handle, ``author_name``, ``text``,
        ``posted_at``, like/repost/reply counts, and ``url``. Raw at:// URIs
        and CIDs are omitted by default; set ``include_ids=True`` only when
        a follow-up tool (``like``, ``repost``, ``delete_post``) needs them.
        Set ``include_metadata=False`` for the raw XRPC response.
        """
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        payload: dict[str, Any] = self._client.get(
            "/xrpc/app.bsky.feed.getTimeline", params=params
        ).json()
        if not include_metadata:
            return payload
        feed: list[Any] = payload.get("feed", [])
        summaries: list[dict[str, Any]] = []
        for index, feed_view in enumerate(feed, start=1):
            if not isinstance(feed_view, dict):
                continue
            feed_view_dict = cast("dict[str, Any]", feed_view)
            summaries.append(
                self._post_summary(feed_view_dict, index=index, include_ids=include_ids)
            )
        return {
            "posts": summaries,
            "cursor": payload.get("cursor"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(GET_AUTHOR_FEED_OUTPUT)
    def get_author_feed(
        self,
        actor: str,
        *,
        limit: int = 25,
        cursor: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Return an author's post feed (DID or handle).

        Same return shape as ``get_timeline`` — compact post summaries by
        default, ``include_ids=True`` to expose raw URIs.
        """
        if not actor:
            raise ValueError("actor is required")
        params: dict[str, Any] = {"actor": actor, "limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        payload: dict[str, Any] = self._client.get(
            "/xrpc/app.bsky.feed.getAuthorFeed", params=params
        ).json()
        if not include_metadata:
            return payload
        feed: list[Any] = payload.get("feed", [])
        summaries: list[dict[str, Any]] = []
        for index, feed_view in enumerate(feed, start=1):
            if not isinstance(feed_view, dict):
                continue
            feed_view_dict = cast("dict[str, Any]", feed_view)
            summaries.append(
                self._post_summary(feed_view_dict, index=index, include_ids=include_ids)
            )
        return {
            "posts": summaries,
            "cursor": payload.get("cursor"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SEARCH_POSTS_OUTPUT)
    def search_posts(
        self,
        query: str,
        *,
        limit: int = 25,
        cursor: str | None = None,
        author: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search public Bluesky posts.

        Best first tool for Bluesky discovery. Default returns compact
        summaries (``post_ref``, ``author`` handle, ``text``, ``posted_at``,
        like/repost counts, ``url``). Raw URIs/CIDs are omitted unless
        ``include_ids=True``. Set ``include_metadata=False`` for the raw
        XRPC response.
        """
        if not query:
            raise ValueError("query is required")
        params: dict[str, Any] = {"q": query, "limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        if author is not None:
            params["author"] = author
        payload: dict[str, Any] = self._client.get(
            "/xrpc/app.bsky.feed.searchPosts", params=params
        ).json()
        if not include_metadata:
            return payload
        posts: list[Any] = payload.get("posts", [])
        summaries: list[dict[str, Any]] = []
        for index, post in enumerate(posts, start=1):
            if not isinstance(post, dict):
                continue
            post_dict = cast("dict[str, Any]", post)
            summaries.append(self._post_summary(post_dict, index=index, include_ids=include_ids))
        return {
            "posts": summaries,
            "cursor": payload.get("cursor"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_post(
        self,
        *,
        text: str,
        reply: dict[str, Any] | None = None,
        embed: dict[str, Any] | None = None,
        langs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a post in the authenticated user's repo.

        Returns ``{"uri": "at://...", "cid": "..."}``. Confirm content
        with the user before calling.
        """
        if not text and not embed:
            raise ValueError("text or embed is required")
        record: dict[str, Any] = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        if reply is not None:
            record["reply"] = reply
        if embed is not None:
            record["embed"] = embed
        if langs is not None:
            record["langs"] = langs
        result: dict[str, Any] = self._client.post(
            "/xrpc/com.atproto.repo.createRecord",
            json={
                "repo": self._did,
                "collection": "app.bsky.feed.post",
                "record": record,
            },
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_post(self, post: str | dict[str, Any]) -> dict[str, Any]:
        """Permanently delete one of the authenticated user's posts.

        Accepts a raw ``rkey`` string, a full at:// URI, OR a post dict
        from ``get_timeline``/``search_posts`` (extracts ``rkey`` from
        ``post.uri``). Destructive and not reversible — confirm with the
        user.
        """
        rkey = self._select_rkey(post)
        result: dict[str, Any] = self._client.post(
            "/xrpc/com.atproto.repo.deleteRecord",
            json={
                "repo": self._did,
                "collection": "app.bsky.feed.post",
                "rkey": rkey,
            },
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def like(
        self,
        post: dict[str, Any] | None = None,
        *,
        uri: str | None = None,
        cid: str | None = None,
    ) -> dict[str, Any]:
        """Like a Bluesky post.

        Accepts either a post/feed-view dict from
        ``search_posts``/``get_timeline``, or explicit ``uri`` + ``cid``
        arguments.
        """
        if post is not None:
            resolved_uri, resolved_cid = self._select_post_ref(post)
        elif uri and cid:
            resolved_uri, resolved_cid = uri, cid
        else:
            raise ValueError("provide post dict or uri+cid")
        result: dict[str, Any] = self._client.post(
            "/xrpc/com.atproto.repo.createRecord",
            json={
                "repo": self._did,
                "collection": "app.bsky.feed.like",
                "record": {
                    "$type": "app.bsky.feed.like",
                    "subject": {"uri": resolved_uri, "cid": resolved_cid},
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                },
            },
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def repost(
        self,
        post: dict[str, Any] | None = None,
        *,
        uri: str | None = None,
        cid: str | None = None,
    ) -> dict[str, Any]:
        """Repost a Bluesky post.

        Accepts either a post/feed-view dict from
        ``search_posts``/``get_timeline``, or explicit ``uri`` + ``cid``
        arguments.
        """
        if post is not None:
            resolved_uri, resolved_cid = self._select_post_ref(post)
        elif uri and cid:
            resolved_uri, resolved_cid = uri, cid
        else:
            raise ValueError("provide post dict or uri+cid")
        result: dict[str, Any] = self._client.post(
            "/xrpc/com.atproto.repo.createRecord",
            json={
                "repo": self._did,
                "collection": "app.bsky.feed.repost",
                "record": {
                    "$type": "app.bsky.feed.repost",
                    "subject": {"uri": resolved_uri, "cid": resolved_cid},
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                },
            },
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def follow(self, subject_did: str) -> dict[str, Any]:
        """Follow another Bluesky account by DID.

        Use ``get_profile`` to resolve a handle to its DID first.
        """
        if not subject_did:
            raise ValueError("subject_did is required")
        result: dict[str, Any] = self._client.post(
            "/xrpc/com.atproto.repo.createRecord",
            json={
                "repo": self._did,
                "collection": "app.bsky.graph.follow",
                "record": {
                    "$type": "app.bsky.graph.follow",
                    "subject": subject_did,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                },
            },
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(GET_FOLLOWERS_OUTPUT)
    def get_followers(
        self,
        actor: str,
        *,
        limit: int = 25,
        cursor: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List followers of an account.

        Default returns compact summaries: ``user_ref`` (stable
        ``user_1`` ...), ``handle``, ``name``, ``description``, ``url``.
        Raw DIDs are omitted unless ``include_ids=True``. Set
        ``include_metadata=False`` for the raw XRPC response.
        """
        if not actor:
            raise ValueError("actor is required")
        params: dict[str, Any] = {"actor": actor, "limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        payload: dict[str, Any] = self._client.get(
            "/xrpc/app.bsky.graph.getFollowers", params=params
        ).json()
        if not include_metadata:
            return payload
        followers: list[Any] = payload.get("followers", [])
        summaries: list[dict[str, Any]] = []
        for index, follower in enumerate(followers, start=1):
            if not isinstance(follower, dict):
                continue
            follower_dict = cast("dict[str, Any]", follower)
            summaries.append(
                self._actor_summary(follower_dict, index=index, include_ids=include_ids)
            )
        return {
            "users": summaries,
            "cursor": payload.get("cursor"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(GET_FOLLOWS_OUTPUT)
    def get_follows(
        self,
        actor: str,
        *,
        limit: int = 25,
        cursor: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List accounts followed by an account.

        Same return shape as ``get_followers`` (compact ``user_ref``
        summaries by default).
        """
        if not actor:
            raise ValueError("actor is required")
        params: dict[str, Any] = {"actor": actor, "limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        payload: dict[str, Any] = self._client.get(
            "/xrpc/app.bsky.graph.getFollows", params=params
        ).json()
        if not include_metadata:
            return payload
        follows: list[Any] = payload.get("follows", [])
        summaries: list[dict[str, Any]] = []
        for index, follow in enumerate(follows, start=1):
            if not isinstance(follow, dict):
                continue
            follow_dict = cast("dict[str, Any]", follow)
            summaries.append(self._actor_summary(follow_dict, index=index, include_ids=include_ids))
        return {
            "users": summaries,
            "cursor": payload.get("cursor"),
        }
