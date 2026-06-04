"""X (Twitter) API v2 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="x")
class XToolSet:
    """A connector for the X (formerly Twitter) v2 API.

    Args:
        bearer_token: OAuth 2.0 bearer token (user-context or app-only).
            Note that some write endpoints require an OAuth 2.0 user
            context with the appropriate scopes.
    """

    metadata = ProviderMetadata(
        name="x",
        display_name="X (Twitter)",
        version="0.1.0",
        description="Tweets, users, search, lists, direct messages.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE, AuthMode.OAUTH2_PKCE, AuthMode.BEARER),
        scopes={
            "tweet.read": "Read tweets.",
            "tweet.write": "Post and delete tweets.",
            "users.read": "Read user profiles.",
            "follows.read": "Read follow graphs.",
            "follows.write": "Follow / unfollow.",
            "like.write": "Like / unlike tweets.",
            "list.read": "Read lists.",
            "list.write": "Manage lists.",
            "dm.read": "Read DMs.",
            "dm.write": "Send DMs.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://docs.x.com/x-api",
        homepage_url="https://x.com/",
        tags=("social-media",),
    )

    def __init__(
        self,
        *,
        bearer_token: str,
        base_url: str = "https://api.x.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not bearer_token:
            raise ValueError("bearer_token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(bearer_token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Internal helpers

    @staticmethod
    def _select_tweet_id(candidate: Any) -> str:
        """Resolve a tweet ID from a raw string or a list/search result dict.

        Tolerates ``tweet_id`` raw strings, dicts with ``id`` / ``tweet_id``,
        and the list/search result shape returned by ``search_recent_tweets``
        (``{"tweets": [{...}]}``).
        """
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("tweet_id must be a non-empty string")
            return candidate
        if isinstance(candidate, dict):
            candidate_dict = cast("dict[str, Any]", candidate)
            for key in ("tweet_id", "id"):
                value = candidate_dict.get(key)
                if isinstance(value, str) and value:
                    return value
            tweets = candidate_dict.get("tweets")
            if isinstance(tweets, list) and tweets:
                first = cast("Any", tweets[0])
                if isinstance(first, dict):
                    return XToolSet._select_tweet_id(first)
        if isinstance(candidate, list) and candidate:
            first_item = cast("Any", candidate[0])
            return XToolSet._select_tweet_id(first_item)
        raise ValueError("could not resolve tweet_id from input")

    @staticmethod
    def _tweet_url(tweet_id: str, username: str | None = None) -> str:
        handle = username or "i"
        return f"https://x.com/{handle}/status/{tweet_id}"

    @staticmethod
    def _resolve_username(tweet: dict[str, Any], includes_users: dict[str, str]) -> str:
        author_id = tweet.get("author_id")
        if isinstance(author_id, str) and author_id in includes_users:
            return includes_users[author_id]
        return ""

    @classmethod
    def _tweet_summary(
        cls,
        tweet: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
        username_lookup: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        username = ""
        if username_lookup is not None:
            username = cls._resolve_username(tweet, username_lookup)
        metrics: dict[str, Any] = tweet.get("public_metrics") or {}
        summary: dict[str, Any] = {
            "tweet_ref": f"tweet_{index}",
            "author": username,
            "text": tweet.get("text", ""),
            "posted_at": tweet.get("created_at", ""),
            "like_count": metrics.get("like_count", 0),
            "repost_count": metrics.get("retweet_count", 0),
            "reply_count": metrics.get("reply_count", 0),
            "url": cls._tweet_url(tweet.get("id", ""), username or None),
        }
        if include_ids:
            summary["tweet_id"] = tweet.get("id", "")
            author_id = tweet.get("author_id")
            if author_id is not None:
                summary["author_id"] = author_id
        return summary

    @classmethod
    def _user_summary(
        cls,
        user: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        metrics: dict[str, Any] = user.get("public_metrics") or {}
        summary: dict[str, Any] = {
            "user_ref": f"user_{index}",
            "handle": user.get("username", ""),
            "name": user.get("name", ""),
            "follower_count": metrics.get("followers_count", 0),
            "following_count": metrics.get("following_count", 0),
            "url": f"https://x.com/{user.get('username', '')}" if user.get("username") else "",
        }
        if include_ids:
            summary["user_id"] = user.get("id", "")
        return summary

    @staticmethod
    def _includes_user_lookup(payload: dict[str, Any]) -> dict[str, str]:
        includes: dict[str, Any] = payload.get("includes") or {}
        users: Any = includes.get("users")
        result: dict[str, str] = {}
        if isinstance(users, list):
            users_list = cast("list[Any]", users)
            for user in users_list:
                if isinstance(user, dict):
                    user_dict = cast("dict[str, Any]", user)
                    user_id = user_dict.get("id")
                    username = user_dict.get("username")
                    if isinstance(user_id, str) and isinstance(username, str):
                        result[user_id] = username
        return result

    # MARK: - Users

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_me(self, *, user_fields: list[str] | None = None) -> dict[str, Any]:
        """Return the authenticated user's profile.

        Returns the raw X v2 user resource (``id``, ``username``, ``name``,
        plus any extra ``user_fields`` you request such as
        ``public_metrics``, ``description``). Use this once at startup to
        confirm the bearer token resolves to a user.
        """
        params: dict[str, Any] = {}
        if user_fields is not None:
            params["user.fields"] = ",".join(user_fields)
        return self._client.get("/2/users/me", params=params or None).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(
        self,
        *,
        user_id: str | None = None,
        username: str | None = None,
        user_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Look up one user by ID or @handle.

        Pass ``username`` (without the ``@``) for handle lookups; pass
        ``user_id`` for the internal numeric ID. Returns the X user resource
        with the requested ``user_fields``.
        """
        if not user_id and not username:
            raise ValueError("provide user_id or username")
        params: dict[str, Any] = {}
        if user_fields is not None:
            params["user.fields"] = ",".join(user_fields)
        if user_id is not None:
            return self._client.get(
                f"/2/users/{user_id}",
                params=params or None,
            ).json()
        assert username is not None
        return self._client.get(
            f"/2/users/by/username/{username}",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user_by_ids(self, ids: list[str]) -> dict[str, Any]:
        """Look up up to 100 users by ID in one request.

        Returns ``{"data": [<user>, ...]}``. Useful when you already have a
        batch of X user IDs (for example from follower / following lists).
        """
        if not ids:
            raise ValueError("ids must be non-empty")
        return self._client.get(
            "/2/users",
            params={"ids": ",".join(ids)},
        ).json()

    # MARK: - Tweets

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_tweet(
        self,
        tweet_id: str,
        *,
        tweet_fields: list[str] | None = None,
        expansions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch a single tweet by its ID.

        Returns the raw v2 tweet resource. Use this after
        ``search_recent_tweets(include_ids=True)`` when you need full content
        for one specific tweet.
        """
        if not tweet_id:
            raise ValueError("tweet_id must be a non-empty string")
        params: dict[str, Any] = {}
        if tweet_fields is not None:
            params["tweet.fields"] = ",".join(tweet_fields)
        if expansions is not None:
            params["expansions"] = ",".join(expansions)
        return self._client.get(
            f"/2/tweets/{tweet_id}",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_tweets(self, ids: list[str]) -> dict[str, Any]:
        """Batch-fetch up to 100 tweets by ID.

        Returns ``{"data": [<tweet>, ...]}``. Use when you have a known set
        of tweet IDs and want raw v2 tweet resources.
        """
        if not ids:
            raise ValueError("ids must be non-empty")
        return self._client.get(
            "/2/tweets",
            params={"ids": ",".join(ids)},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_recent_tweets(
        self,
        query: str,
        *,
        max_results: int = 10,
        next_token: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        tweet_fields: list[str] | None = None,
        expansions: list[str] | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search tweets posted in the last 7 days.

        Best first tool for X/Twitter discovery. By default returns compact,
        human-readable summaries: ``tweet_ref`` (stable ``tweet_1``,
        ``tweet_2``, ...), ``author`` (@handle), ``text``, ``posted_at``,
        ``like_count``, ``repost_count``, ``reply_count``, and ``url``. Raw
        X tweet IDs are omitted by default; set ``include_ids=True`` only
        when a follow-up tool (like_post, repost, delete_tweet) needs the
        raw ``tweet_id``. Set ``include_metadata=False`` to return the raw
        v2 API payload as-is.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        if max_results < 10 or max_results > 100:
            raise ValueError("max_results must be between 10 and 100")
        params: dict[str, Any] = {"query": query, "max_results": max_results}
        if next_token is not None:
            params["next_token"] = next_token
        if start_time is not None:
            params["start_time"] = start_time
        if end_time is not None:
            params["end_time"] = end_time
        merged_fields = list(tweet_fields) if tweet_fields else []
        if include_metadata:
            for needed in ("created_at", "public_metrics", "author_id"):
                if needed not in merged_fields:
                    merged_fields.append(needed)
        if merged_fields:
            params["tweet.fields"] = ",".join(merged_fields)
        merged_expansions = list(expansions) if expansions else []
        if include_metadata and "author_id" not in merged_expansions:
            merged_expansions.append("author_id")
        if merged_expansions:
            params["expansions"] = ",".join(merged_expansions)
        payload: dict[str, Any] = self._client.get(
            "/2/tweets/search/recent",
            params=params,
        ).json()
        if not include_metadata:
            return payload
        username_lookup = self._includes_user_lookup(payload)
        summaries: list[dict[str, Any]] = []
        data: Any = payload.get("data", [])
        for index, tweet in enumerate(data, start=1):
            if not isinstance(tweet, dict):
                continue
            tweet_dict = cast("dict[str, Any]", tweet)
            summaries.append(
                self._tweet_summary(
                    tweet_dict,
                    index=index,
                    include_ids=include_ids,
                    username_lookup=username_lookup,
                )
            )
        raw_meta: Any = payload.get("meta")
        meta: dict[str, Any] = {}
        if isinstance(raw_meta, dict):
            meta = cast("dict[str, Any]", raw_meta)
        return {
            "tweets": summaries,
            "next_token": meta.get("next_token"),
            "result_count": meta.get("result_count", len(summaries)),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user_tweets(
        self,
        user_id: str,
        *,
        max_results: int = 10,
        pagination_token: str | None = None,
        exclude: list[str] | None = None,
        tweet_fields: list[str] | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List tweets posted by a single user.

        By default returns compact summaries (``tweet_ref``, ``text``,
        ``posted_at``, like/repost counts, ``url``). Raw IDs are omitted
        unless ``include_ids=True``. Use ``include_metadata=False`` to fall
        back to the raw v2 response.
        """
        if not user_id:
            raise ValueError("user_id must be a non-empty string")
        params: dict[str, Any] = {"max_results": max_results}
        if pagination_token is not None:
            params["pagination_token"] = pagination_token
        if exclude is not None:
            params["exclude"] = ",".join(exclude)
        merged_fields = list(tweet_fields) if tweet_fields else []
        if include_metadata:
            for needed in ("created_at", "public_metrics"):
                if needed not in merged_fields:
                    merged_fields.append(needed)
        if merged_fields:
            params["tweet.fields"] = ",".join(merged_fields)
        payload: dict[str, Any] = self._client.get(
            f"/2/users/{user_id}/tweets",
            params=params,
        ).json()
        if not include_metadata:
            return payload
        summaries: list[dict[str, Any]] = []
        data: Any = payload.get("data", [])
        for index, tweet in enumerate(data, start=1):
            if not isinstance(tweet, dict):
                continue
            tweet_dict = cast("dict[str, Any]", tweet)
            summaries.append(
                self._tweet_summary(
                    tweet_dict,
                    index=index,
                    include_ids=include_ids,
                )
            )
        raw_meta: Any = payload.get("meta")
        meta: dict[str, Any] = {}
        if isinstance(raw_meta, dict):
            meta = cast("dict[str, Any]", raw_meta)
        return {
            "tweets": summaries,
            "next_token": meta.get("next_token"),
            "result_count": meta.get("result_count", len(summaries)),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user_mentions(
        self,
        user_id: str,
        *,
        max_results: int = 10,
        pagination_token: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List tweets mentioning the given user.

        Returns compact summaries by default (same shape as
        ``search_recent_tweets``). Set ``include_metadata=False`` to get the
        raw v2 payload; ``include_ids=True`` exposes raw tweet IDs.
        """
        if not user_id:
            raise ValueError("user_id must be a non-empty string")
        params: dict[str, Any] = {"max_results": max_results}
        if pagination_token is not None:
            params["pagination_token"] = pagination_token
        if include_metadata:
            params["tweet.fields"] = "created_at,public_metrics,author_id"
            params["expansions"] = "author_id"
        payload: dict[str, Any] = self._client.get(
            f"/2/users/{user_id}/mentions",
            params=params,
        ).json()
        if not include_metadata:
            return payload
        username_lookup = self._includes_user_lookup(payload)
        summaries: list[dict[str, Any]] = []
        data: Any = payload.get("data", [])
        for index, tweet in enumerate(data, start=1):
            if not isinstance(tweet, dict):
                continue
            tweet_dict = cast("dict[str, Any]", tweet)
            summaries.append(
                self._tweet_summary(
                    tweet_dict,
                    index=index,
                    include_ids=include_ids,
                    username_lookup=username_lookup,
                )
            )
        raw_meta: Any = payload.get("meta")
        meta: dict[str, Any] = {}
        if isinstance(raw_meta, dict):
            meta = cast("dict[str, Any]", raw_meta)
        return {
            "tweets": summaries,
            "next_token": meta.get("next_token"),
            "result_count": meta.get("result_count", len(summaries)),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def post_tweet(
        self,
        text: str,
        *,
        reply_to_tweet_id: str | None = None,
        quote_tweet_id: str | None = None,
        media_ids: list[str] | None = None,
        reply_settings: str | None = None,
        poll: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Publish a tweet on behalf of the authenticated user.

        Returns the new tweet resource (``id``, ``text``). Always confirm
        the text with the user before calling in an interactive loop.
        """
        if not text and media_ids is None:
            raise ValueError("text or media_ids must be provided")
        body: dict[str, Any] = {"text": text}
        if reply_to_tweet_id is not None:
            body["reply"] = {"in_reply_to_tweet_id": reply_to_tweet_id}
        if quote_tweet_id is not None:
            body["quote_tweet_id"] = quote_tweet_id
        if media_ids is not None:
            body["media"] = {"media_ids": media_ids}
        if reply_settings is not None:
            body["reply_settings"] = reply_settings
        if poll is not None:
            body["poll"] = poll
        return self._client.post("/2/tweets", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_tweet(self, tweet: str | dict[str, Any]) -> dict[str, Any]:
        """Permanently delete a tweet owned by the authenticated user.

        Accepts either a raw ``tweet_id`` string or a tweet/search result
        dict (looks up ``tweet_id`` or ``id``). Destructive and not
        reversible — confirm with the user before calling.
        """
        tweet_id = self._select_tweet_id(tweet)
        return self._client.delete(f"/2/tweets/{tweet_id}").json()

    # MARK: - Likes, follows, retweets

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def like_tweet(
        self,
        *,
        user_id: str,
        tweet: str | dict[str, Any],
    ) -> dict[str, Any]:
        """Like a tweet on behalf of ``user_id``.

        ``tweet`` accepts either a raw ``tweet_id`` string or a tweet/search
        result dict (looks up ``tweet_id`` / ``id``).
        """
        if not user_id:
            raise ValueError("user_id must be non-empty")
        tweet_id = self._select_tweet_id(tweet)
        return self._client.post(
            f"/2/users/{user_id}/likes",
            json={"tweet_id": tweet_id},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def unlike_tweet(
        self,
        *,
        user_id: str,
        tweet: str | dict[str, Any],
    ) -> dict[str, Any]:
        """Remove a like on a tweet.

        Tagged destructive because it removes engagement signal. ``tweet``
        accepts the same shapes as ``like_tweet``.
        """
        if not user_id:
            raise ValueError("user_id must be non-empty")
        tweet_id = self._select_tweet_id(tweet)
        return self._client.delete(
            f"/2/users/{user_id}/likes/{tweet_id}",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def retweet(
        self,
        *,
        user_id: str,
        tweet: str | dict[str, Any],
    ) -> dict[str, Any]:
        """Retweet a tweet on behalf of ``user_id``.

        ``tweet`` accepts a raw ``tweet_id`` string or a tweet dict.
        """
        if not user_id:
            raise ValueError("user_id must be non-empty")
        tweet_id = self._select_tweet_id(tweet)
        return self._client.post(
            f"/2/users/{user_id}/retweets",
            json={"tweet_id": tweet_id},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def unretweet(
        self,
        *,
        user_id: str,
        tweet: str | dict[str, Any],
    ) -> dict[str, Any]:
        """Remove a retweet.

        Tagged destructive because it removes amplification.
        """
        if not user_id:
            raise ValueError("user_id must be non-empty")
        tweet_id = self._select_tweet_id(tweet)
        return self._client.delete(
            f"/2/users/{user_id}/retweets/{tweet_id}",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def follow_user(self, *, user_id: str, target_user_id: str) -> dict[str, Any]:
        """Follow another user on behalf of ``user_id``.

        Both arguments are X internal numeric user IDs (see ``get_user`` to
        resolve from an @handle).
        """
        if not user_id or not target_user_id:
            raise ValueError("user_id and target_user_id must be non-empty")
        return self._client.post(
            f"/2/users/{user_id}/following",
            json={"target_user_id": target_user_id},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def unfollow_user(self, *, user_id: str, target_user_id: str) -> dict[str, Any]:
        """Unfollow a user.

        Destructive because it removes a relationship. Confirm with the user
        before calling.
        """
        if not user_id or not target_user_id:
            raise ValueError("user_id and target_user_id must be non-empty")
        return self._client.delete(
            f"/2/users/{user_id}/following/{target_user_id}",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_followers(
        self,
        user_id: str,
        *,
        max_results: int = 25,
        pagination_token: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List followers of a user.

        By default returns compact summaries: ``user_ref`` (stable
        ``user_1`` ...), ``handle``, ``name``, follower/following counts,
        and ``url``. Raw X user IDs are omitted unless ``include_ids=True``.
        Set ``include_metadata=False`` to receive the raw v2 payload.
        """
        if not user_id:
            raise ValueError("user_id must be a non-empty string")
        params: dict[str, Any] = {"max_results": max_results}
        if pagination_token is not None:
            params["pagination_token"] = pagination_token
        if include_metadata:
            params["user.fields"] = "username,name,public_metrics"
        payload: dict[str, Any] = self._client.get(
            f"/2/users/{user_id}/followers",
            params=params,
        ).json()
        if not include_metadata:
            return payload
        summaries: list[dict[str, Any]] = []
        data: Any = payload.get("data", [])
        for index, user in enumerate(data, start=1):
            if not isinstance(user, dict):
                continue
            user_dict = cast("dict[str, Any]", user)
            summaries.append(self._user_summary(user_dict, index=index, include_ids=include_ids))
        raw_meta: Any = payload.get("meta")
        meta: dict[str, Any] = {}
        if isinstance(raw_meta, dict):
            meta = cast("dict[str, Any]", raw_meta)
        return {
            "users": summaries,
            "next_token": meta.get("next_token"),
            "result_count": meta.get("result_count", len(summaries)),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_following(
        self,
        user_id: str,
        *,
        max_results: int = 25,
        pagination_token: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List accounts a user follows.

        Same return shape as ``get_followers`` (compact ``user_ref``
        summaries by default; ``include_ids=True`` for raw IDs).
        """
        if not user_id:
            raise ValueError("user_id must be a non-empty string")
        params: dict[str, Any] = {"max_results": max_results}
        if pagination_token is not None:
            params["pagination_token"] = pagination_token
        if include_metadata:
            params["user.fields"] = "username,name,public_metrics"
        payload: dict[str, Any] = self._client.get(
            f"/2/users/{user_id}/following",
            params=params,
        ).json()
        if not include_metadata:
            return payload
        summaries: list[dict[str, Any]] = []
        data: Any = payload.get("data", [])
        for index, user in enumerate(data, start=1):
            if not isinstance(user, dict):
                continue
            user_dict = cast("dict[str, Any]", user)
            summaries.append(self._user_summary(user_dict, index=index, include_ids=include_ids))
        raw_meta: Any = payload.get("meta")
        meta: dict[str, Any] = {}
        if isinstance(raw_meta, dict):
            meta = cast("dict[str, Any]", raw_meta)
        return {
            "users": summaries,
            "next_token": meta.get("next_token"),
            "result_count": meta.get("result_count", len(summaries)),
        }

    # MARK: - Lists

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_owned_lists(self, user_id: str) -> dict[str, Any]:
        """List lists owned by a user.

        Returns the raw v2 ``/owned_lists`` payload (``data`` array of list
        resources with ``id`` and ``name``).
        """
        if not user_id:
            raise ValueError("user_id must be a non-empty string")
        return self._client.get(f"/2/users/{user_id}/owned_lists").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_list(
        self,
        *,
        name: str,
        description: str | None = None,
        private: bool = False,
    ) -> dict[str, Any]:
        """Create a new list owned by the authenticated user.

        Returns the new list resource (``id``, ``name``).
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        body: dict[str, Any] = {"name": name, "private": private}
        if description is not None:
            body["description"] = description
        return self._client.post("/2/lists", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_list(self, list_id: str) -> dict[str, Any]:
        """Delete a list owned by the authenticated user.

        Destructive and not reversible — confirm with the user.
        """
        if not list_id:
            raise ValueError("list_id must be a non-empty string")
        return self._client.delete(f"/2/lists/{list_id}").json()

    # MARK: - Direct messages

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def send_dm(self, *, participant_id: str, text: str) -> dict[str, Any]:
        """Send a DM to one user.

        ``participant_id`` is the recipient's internal X user ID (use
        ``get_user`` to resolve from an @handle).
        """
        if not participant_id or not text:
            raise ValueError("participant_id and text must be non-empty")
        return self._client.post(
            f"/2/dm_conversations/with/{participant_id}/messages",
            json={"text": text},
        ).json()
