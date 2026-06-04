"""Buffer GraphQL API connector.

Buffer replaced its legacy REST API (``https://api.bufferapp.com/1/*.json``,
authenticated with an ``access_token`` query parameter) with a single
unversioned GraphQL endpoint at ``https://api.buffer.com``, authenticated via
an ``Authorization: Bearer`` header. Resources were renamed: the old
``profiles`` are now ``channels`` and the old ``updates`` are now ``posts``.
Pagination shifted from offset-based (``page``/``count`` + ``total``) to
cursor-based (``first``/``after`` + ``pageInfo``).

The public tool surface keeps its historical method names (``list_profiles``,
``list_pending_updates``, ...) so existing callers keep working; internally each
method issues the corresponding GraphQL query/mutation against the new schema.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# Buffer's current public API is a single unversioned GraphQL endpoint.
_API_BASE_URL = "https://api.buffer.com"

# MARK: - GraphQL documents

_ACCOUNT_QUERY = """
query Account {
  account {
    id
    name
    email
  }
}
"""

_CHANNELS_QUERY = """
query Channels {
  channels {
    id
    name
    service
    serviceId
    avatar
  }
}
"""

_CHANNEL_QUERY = """
query Channel($id: ID!) {
  channel(id: $id) {
    id
    name
    service
    serviceId
    avatar
  }
}
"""

_POSTS_QUERY = """
query Posts($channelId: ID!, $status: PostStatus!, $first: Int!, $after: String) {
  posts(channelId: $channelId, status: $status, first: $first, after: $after) {
    edges {
      node {
        id
        text
        status
        scheduledAt
        sentAt
        service
        channelId
        author { name }
      }
      cursor
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

_POST_QUERY = """
query Post($id: ID!) {
  post(id: $id) {
    id
    text
    status
    scheduledAt
    sentAt
    service
    channelId
    author { name }
  }
}
"""

_CREATE_POST_MUTATION = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    posts {
      id
      text
      status
      scheduledAt
      channelId
    }
  }
}
"""

_UPDATE_POST_MUTATION = """
mutation UpdatePost($input: UpdatePostInput!) {
  updatePost(input: $input) {
    post {
      id
      text
      status
      scheduledAt
    }
  }
}
"""

_SHARE_POST_MUTATION = """
mutation SharePostNow($id: ID!) {
  sharePostNow(id: $id) {
    post {
      id
      status
      sentAt
    }
  }
}
"""

_DELETE_POST_MUTATION = """
mutation DeletePost($id: ID!) {
  deletePost(id: $id) {
    deletedId
  }
}
"""

_POST_INTERACTIONS_QUERY = """
query PostInteractions($id: ID!, $event: String!, $first: Int!, $after: String) {
  post(id: $id) {
    interactions(event: $event, first: $first, after: $after) {
      edges {
        node {
          id
          event
          text
          createdAt
          author { name }
        }
        cursor
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""


@toolset(prefix="buffer")
class BufferToolSet:
    """A connector for Buffer's social scheduling GraphQL API.

    Args:
        api_key: Buffer API key (or OAuth 2.0 access token), sent as
            ``Authorization: Bearer <api_key>``.
        base_url: GraphQL endpoint. Defaults to ``https://api.buffer.com``.
    """

    metadata = ProviderMetadata(
        name="buffer",
        display_name="Buffer",
        version="0.1.0",
        description="Channels, queues, posts, drafts, and analytics.",
        auth_modes=(AuthMode.BEARER, AuthMode.OAUTH2_AUTH_CODE),
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developers.buffer.com/guides/graphql-intro.html",
        homepage_url="https://buffer.com/",
        tags=("social-media", "scheduling"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = _API_BASE_URL,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._endpoint = base_url.rstrip("/")
        self._client = HttpClient(
            base_url="",
            auth=BearerTokenAuth(api_key),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Internal helpers

    def _execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST a GraphQL document and return the ``data`` envelope.

        Raises ``ValueError`` when the response carries a GraphQL ``errors``
        array so failures are not silently treated as success payloads.
        """
        payload: dict[str, Any] = {"query": query}
        if variables is not None:
            payload["variables"] = variables
        response: object = self._client.post(self._endpoint, json=payload).json()
        if isinstance(response, dict):
            envelope = cast(dict[str, Any], response)
            if envelope.get("errors"):
                raise ValueError(f"Buffer GraphQL error: {envelope['errors']}")
            data = envelope.get("data")
            if isinstance(data, dict):
                return cast(dict[str, Any], data)
        return {}

    @staticmethod
    def _select_update_id(candidate: object) -> str:
        """Resolve a Buffer post ID from a string or a post dict."""
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("update_id must be a non-empty string")
            return candidate
        if isinstance(candidate, dict):
            mapping = cast(dict[str, Any], candidate)
            for key in ("update_id", "id", "_id"):
                value = mapping.get(key)
                if isinstance(value, str) and value:
                    return value
        if isinstance(candidate, list) and candidate:
            items = cast(list[Any], candidate)
            return BufferToolSet._select_update_id(items[0])
        raise ValueError("could not resolve update_id from input")

    @classmethod
    def _update_summary(
        cls,
        post: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        author: object = post.get("author") or {}
        author_name: str = ""
        if isinstance(author, dict):
            name = cast(dict[str, Any], author).get("name", "")
            author_name = name if isinstance(name, str) else ""
        summary: dict[str, Any] = {
            "update_ref": f"update_{index}",
            "text": post.get("text", ""),
            "status": post.get("status", ""),
            "scheduled_at": post.get("scheduledAt", 0),
            "sent_at": post.get("sentAt", 0),
            "service": post.get("service", ""),
            "author": author_name,
        }
        if include_ids:
            summary["update_id"] = post.get("id", "")
            channel_id = post.get("channelId")
            if channel_id:
                summary["profile_id"] = channel_id
        return summary

    def _list_posts(
        self,
        profile_id: str,
        *,
        status: str,
        first: int,
        after: str | None,
        include_metadata: bool,
        include_ids: bool,
    ) -> dict[str, Any]:
        if not profile_id:
            raise ValueError("profile_id is required")
        variables: dict[str, Any] = {
            "channelId": profile_id,
            "status": status,
            "first": first,
        }
        if after is not None:
            variables["after"] = after
        data = self._execute(_POSTS_QUERY, variables)
        raw_connection: object = data.get("posts", {})
        connection: dict[str, Any] = (
            cast(dict[str, Any], raw_connection) if isinstance(raw_connection, dict) else {}
        )
        raw_edges: object = connection.get("edges", [])
        edges: list[Any] = cast(list[Any], raw_edges) if isinstance(raw_edges, list) else []
        raw_page_info: object = connection.get("pageInfo", {})
        page_info: dict[str, Any] = (
            cast(dict[str, Any], raw_page_info) if isinstance(raw_page_info, dict) else {}
        )
        nodes: list[dict[str, Any]] = []
        for edge in edges:
            if isinstance(edge, dict):
                node = cast(dict[str, Any], edge).get("node")
                if isinstance(node, dict):
                    nodes.append(cast(dict[str, Any], node))
        if not include_metadata:
            return connection
        summaries: list[dict[str, Any]] = [
            self._update_summary(node, index=index, include_ids=include_ids)
            for index, node in enumerate(nodes, start=1)
        ]
        return {
            "updates": summaries,
            "has_next_page": page_info.get("hasNextPage", False),
            "end_cursor": page_info.get("endCursor"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self) -> dict[str, Any]:
        """Return the authenticated Buffer account.

        Returns the GraphQL ``account`` resource (``id``, ``name``,
        ``email``).
        """
        return self._execute(_ACCOUNT_QUERY)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_profiles(self) -> dict[str, Any]:
        """List social channels connected to the Buffer account.

        Returns the GraphQL ``channels`` array. Each channel carries the
        ``id`` you need for queue/post operations and the ``service``
        (``twitter``, ``facebook``, ``linkedin``, ...).
        """
        return self._execute(_CHANNELS_QUERY)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_profile(self, profile_id: str) -> dict[str, Any]:
        """Fetch one Buffer channel by ID.

        Returns the GraphQL ``channel`` resource. Use after
        ``list_profiles`` when you want metadata for one specific channel.
        """
        if not profile_id:
            raise ValueError("profile_id is required")
        return self._execute(_CHANNEL_QUERY, {"id": profile_id})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_pending_updates(
        self,
        profile_id: str,
        *,
        first: int = 10,
        after: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List queued (not-yet-sent) posts on a channel.

        Best first tool for triaging a channel's scheduled queue. Default
        returns compact summaries: ``update_ref`` (stable ``update_1`` ...),
        ``text``, ``status``, ``scheduled_at``, ``sent_at``, ``service``,
        ``author``. Raw Buffer post IDs are omitted unless
        ``include_ids=True``. Set ``include_metadata=False`` for the raw
        GraphQL connection. Pass ``after`` (an ``end_cursor``) to page.
        """
        return self._list_posts(
            profile_id,
            status="pending",
            first=first,
            after=after,
            include_metadata=include_metadata,
            include_ids=include_ids,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_sent_updates(
        self,
        profile_id: str,
        *,
        first: int = 10,
        after: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List recently-sent posts on a channel.

        Same return shape as ``list_pending_updates`` — compact
        summaries by default; raw connection with
        ``include_metadata=False``.
        """
        return self._list_posts(
            profile_id,
            status="sent",
            first=first,
            after=after,
            include_metadata=include_metadata,
            include_ids=include_ids,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_update(self, update_id: str) -> dict[str, Any]:
        """Fetch one post by Buffer internal ID.

        Returns the GraphQL ``post`` resource.
        """
        if not update_id:
            raise ValueError("update_id is required")
        return self._execute(_POST_QUERY, {"id": update_id})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_update(
        self,
        *,
        profile_ids: list[str],
        text: str,
        media: dict[str, Any] | None = None,
        scheduled_at: int | None = None,
        shorten: bool = True,
        now: bool = False,
        top: bool = False,
    ) -> dict[str, Any]:
        """Queue a post across one or more Buffer channels.

        Returns the GraphQL ``createPost`` payload (``posts``). Pass
        ``now=True`` to share immediately, or ``scheduled_at`` (Unix seconds)
        to schedule.
        """
        if not profile_ids or not text:
            raise ValueError("profile_ids and text are required")
        post_input: dict[str, Any] = {
            "channelIds": list(profile_ids),
            "text": text,
            "shorten": shorten,
        }
        if media is not None:
            post_input["media"] = media
        if scheduled_at is not None:
            post_input["scheduledAt"] = scheduled_at
        if now:
            post_input["now"] = True
        if top:
            post_input["top"] = True
        return self._execute(_CREATE_POST_MUTATION, {"input": post_input})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_update(
        self,
        update: str | dict[str, Any],
        *,
        text: str | None = None,
        scheduled_at: int | None = None,
        media: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Edit an existing queued post.

        ``update`` accepts a raw ``update_id`` string OR a post dict
        from ``list_pending_updates`` (looks up ``update_id`` / ``id``).
        """
        update_id = self._select_update_id(update)
        post_input: dict[str, Any] = {"id": update_id}
        if text is not None:
            post_input["text"] = text
        if scheduled_at is not None:
            post_input["scheduledAt"] = scheduled_at
        if media is not None:
            post_input["media"] = media
        if len(post_input) == 1:
            raise ValueError("at least one of text/scheduled_at/media is required")
        return self._execute(_UPDATE_POST_MUTATION, {"input": post_input})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def share_update_now(self, update: str | dict[str, Any]) -> dict[str, Any]:
        """Share a queued post immediately, bypassing the schedule.

        ``update`` accepts a raw ``update_id`` string OR a post dict
        from ``list_pending_updates``. Confirm with the user before
        calling — this publishes publicly.
        """
        update_id = self._select_update_id(update)
        return self._execute(_SHARE_POST_MUTATION, {"id": update_id})

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def destroy_update(self, update: str | dict[str, Any]) -> dict[str, Any]:
        """Delete a post from the queue (or revoke if already sent).

        Accepts a raw ``update_id`` string OR a post dict from
        ``list_pending_updates``/``list_sent_updates``. Destructive and
        not reversible — confirm with the user.
        """
        update_id = self._select_update_id(update)
        return self._execute(_DELETE_POST_MUTATION, {"id": update_id})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_update_interactions(
        self,
        update_id: str,
        *,
        event: str = "mention",
        first: int = 20,
        after: str | None = None,
    ) -> dict[str, Any]:
        """List interactions (mentions / retweets / etc.) for one post.

        Returns the GraphQL ``post.interactions`` connection. ``event`` is
        the Buffer event type (``mention``, ``retweet``, ``like``, etc.).
        Pass ``after`` (an ``endCursor``) to page.
        """
        if not update_id:
            raise ValueError("update_id is required")
        variables: dict[str, Any] = {
            "id": update_id,
            "event": event,
            "first": first,
        }
        if after is not None:
            variables["after"] = after
        return self._execute(_POST_INTERACTIONS_QUERY, variables)
