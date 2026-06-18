"""Threads (Meta) Graph API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_REPLIES_OUTPUT, LIST_THREADS_OUTPUT


@toolset(prefix="threads")
class ThreadsToolSet:
    """A connector for the Threads (Meta) Graph API.

    Args:
        access_token: User-context access token.
        graph_version: Graph API version (default ``"v1.0"``).
    """

    metadata = ProviderMetadata(
        name="threads",
        display_name="Threads",
        version="0.1.0",
        description="Threads profile, media containers, publish, replies, and insights.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "threads_basic": "Read profile / threads.",
            "threads_content_publish": "Publish threads.",
            "threads_manage_replies": "Reply / hide replies.",
            "threads_read_replies": "Read replies.",
            "threads_manage_insights": "Read insights.",
        },
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developers.facebook.com/docs/threads/",
        homepage_url="https://www.threads.net/",
        tags=("social-media", "meta"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        graph_version: str = "v1.0",
        base_url: str = "https://graph.threads.net",
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

    @classmethod
    def _thread_summary(
        cls,
        thread: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "post_ref": f"post_{index}",
            "author": thread.get("username", ""),
            "text": thread.get("text", ""),
            "posted_at": thread.get("timestamp", ""),
            "media_type": thread.get("media_type", ""),
            "permalink": thread.get("permalink", ""),
        }
        if include_ids:
            summary["post_id"] = thread.get("id", "")
        return summary

    @classmethod
    def _reply_summary(
        cls,
        reply: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "reply_ref": f"reply_{index}",
            "author": reply.get("username", ""),
            "text": reply.get("text", ""),
            "posted_at": reply.get("timestamp", ""),
            "permalink": reply.get("permalink", ""),
        }
        if include_ids:
            summary["reply_id"] = reply.get("id", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_me(self, *, fields: list[str] | None = None) -> dict[str, Any]:
        """Return the authenticated user (``/me``).

        Returns the raw Threads user resource (``id``, ``username``,
        ``name``). Use ``fields`` for additional profile data.
        """
        params: dict[str, Any] = {}
        if fields is not None:
            params["fields"] = ",".join(fields)
        return self._client.get(self._path("/me"), params=params or None).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_THREADS_OUTPUT)
    def list_threads(
        self,
        user_id: str,
        *,
        fields: list[str] | None = None,
        limit: int = 10,
        after: str | None = None,
        since: str | None = None,
        until: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List threads posted by a user.

        Best first tool for Threads triage. Default returns compact
        summaries: ``post_ref`` (stable ``post_1`` ...), ``author``
        username, ``text``, ``posted_at``, ``media_type``, ``permalink``.
        Raw thread IDs are omitted unless ``include_ids=True``. Set
        ``include_metadata=False`` for the raw Graph response.
        """
        if not user_id:
            raise ValueError("user_id is required")
        params: dict[str, Any] = {"limit": limit}
        merged_fields = list(fields) if fields else []
        if include_metadata:
            for needed in ("id", "text", "media_type", "permalink", "timestamp", "username"):
                if needed not in merged_fields:
                    merged_fields.append(needed)
        if merged_fields:
            params["fields"] = ",".join(merged_fields)
        if after is not None:
            params["after"] = after
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        payload: dict[str, Any] = self._client.get(
            self._path(f"/{user_id}/threads"), params=params
        ).json()
        if not include_metadata:
            return payload
        summaries: list[dict[str, Any]] = []
        data: list[Any] = payload.get("data", [])
        for index, thread in enumerate(data, start=1):
            if not isinstance(thread, dict):
                continue
            thread_obj = cast(dict[str, Any], thread)
            summaries.append(self._thread_summary(thread_obj, index=index, include_ids=include_ids))
        return {
            "posts": summaries,
            "paging": payload.get("paging"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_thread(
        self,
        media_id: str,
        *,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch a single thread by media ID.

        Returns the raw Threads media resource. Use after
        ``list_threads(include_ids=True)`` when you need full thread
        details.
        """
        if not media_id:
            raise ValueError("media_id is required")
        params: dict[str, Any] = {}
        if fields is not None:
            params["fields"] = ",".join(fields)
        return self._client.get(self._path(f"/{media_id}"), params=params or None).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_media_container(
        self,
        user_id: str,
        *,
        media_type: str,
        text: str | None = None,
        image_url: str | None = None,
        video_url: str | None = None,
        reply_to_id: str | None = None,
        children: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a media container (step 1 of the two-step publish).

        Returns ``{"id": "<creation_id>"}``. Pass the ``id`` to
        :meth:`publish_media`. ``media_type`` must be ``TEXT``, ``IMAGE``,
        ``VIDEO``, or ``CAROUSEL``.
        """
        if not user_id:
            raise ValueError("user_id is required")
        if media_type not in {"TEXT", "IMAGE", "VIDEO", "CAROUSEL"}:
            raise ValueError("media_type must be TEXT/IMAGE/VIDEO/CAROUSEL")
        if media_type == "IMAGE" and not image_url:
            raise ValueError("image_url is required for IMAGE media")
        if media_type == "VIDEO" and not video_url:
            raise ValueError("video_url is required for VIDEO media")
        if media_type == "CAROUSEL" and not children:
            raise ValueError("children is required for CAROUSEL media")
        body: dict[str, Any] = {"media_type": media_type}
        if text is not None:
            body["text"] = text
        if image_url is not None:
            body["image_url"] = image_url
        if video_url is not None:
            body["video_url"] = video_url
        if reply_to_id is not None:
            body["reply_to_id"] = reply_to_id
        if children is not None:
            body["children"] = ",".join(children)
        return self._client.post(self._path(f"/{user_id}/threads"), params=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def publish_media(self, *, user_id: str, creation_id: str) -> dict[str, Any]:
        """Publish a previously-created media container.

        Returns the new thread media resource (``id``). Confirm with the
        user before calling — this posts publicly.
        """
        if not user_id or not creation_id:
            raise ValueError("user_id and creation_id are required")
        return self._client.post(
            self._path(f"/{user_id}/threads_publish"),
            params={"creation_id": creation_id},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_container_status(self, container_id: str) -> dict[str, Any]:
        """Poll a media container's status.

        Returns ``{"status": "FINISHED" | ..., "error_message": ...}``.
        Poll until status is terminal before calling ``publish_media``.
        """
        if not container_id:
            raise ValueError("container_id is required")
        return self._client.get(
            self._path(f"/{container_id}"),
            params={"fields": "status,error_message"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_REPLIES_OUTPUT)
    def list_replies(
        self,
        media_id: str,
        *,
        fields: list[str] | None = None,
        reverse: bool = False,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List replies to a thread.

        Default returns compact summaries: ``reply_ref``, ``author``
        username, ``text``, ``posted_at``, ``permalink``. Raw reply IDs
        are omitted unless ``include_ids=True``. Set
        ``include_metadata=False`` for the raw Graph response.
        """
        if not media_id:
            raise ValueError("media_id is required")
        params: dict[str, Any] = {"reverse": str(reverse).lower()}
        merged_fields = list(fields) if fields else []
        if include_metadata:
            for needed in ("id", "text", "username", "timestamp", "permalink"):
                if needed not in merged_fields:
                    merged_fields.append(needed)
        if merged_fields:
            params["fields"] = ",".join(merged_fields)
        payload: dict[str, Any] = self._client.get(
            self._path(f"/{media_id}/replies"), params=params
        ).json()
        if not include_metadata:
            return payload
        summaries: list[dict[str, Any]] = []
        data: list[Any] = payload.get("data", [])
        for index, reply in enumerate(data, start=1):
            if not isinstance(reply, dict):
                continue
            reply_obj = cast(dict[str, Any], reply)
            summaries.append(self._reply_summary(reply_obj, index=index, include_ids=include_ids))
        return {
            "replies": summaries,
            "paging": payload.get("paging"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def hide_reply(self, reply_id: str, *, hide: bool = True) -> dict[str, Any]:
        """Hide or unhide a reply.

        Pass ``hide=False`` to unhide. Less destructive than deletion —
        the reply still exists, just hidden from public view.
        """
        if not reply_id:
            raise ValueError("reply_id is required")
        return self._client.post(
            self._path(f"/{reply_id}/manage_reply"),
            params={"hide": str(hide).lower()},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_media_insights(
        self,
        media_id: str,
        *,
        metric: list[str],
    ) -> dict[str, Any]:
        """Return insights for one thread.

        Returns the raw Graph insights response. ``metric`` is the list
        of insight names (e.g. ``["views", "likes", "replies"]``).
        """
        if not media_id or not metric:
            raise ValueError("media_id and metric are required")
        return self._client.get(
            self._path(f"/{media_id}/insights"),
            params={"metric": ",".join(metric)},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user_insights(
        self,
        user_id: str,
        *,
        metric: list[str],
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """Return user-level insights.

        Returns the raw Graph insights response. ``metric`` is the list
        of user-level insight names (e.g. ``["views", "likes"]``).
        ``since`` and ``until`` must be Unix timestamps (epoch seconds,
        earliest allowed 1712991600), not ISO-8601 dates.
        """
        if not user_id or not metric:
            raise ValueError("user_id and metric are required")
        params: dict[str, Any] = {"metric": ",".join(metric)}
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        return self._client.get(self._path(f"/{user_id}/threads_insights"), params=params).json()
