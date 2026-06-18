"""YouTube Data API v3 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from ..google_workspace._shared import TokenSource, make_bearer_auth
from .output_schemas import (
    LIST_COMMENT_THREADS_OUTPUT,
    LIST_VIDEOS_OUTPUT,
    SEARCH_OUTPUT,
)


@toolset(prefix="youtube")
class YouTubeToolSet:
    """A connector for the YouTube Data API v3."""

    metadata = ProviderMetadata(
        name="youtube",
        display_name="YouTube",
        version="0.1.0",
        description="Channels, videos, playlists, search, comments.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "https://www.googleapis.com/auth/youtube.readonly": "Read-only.",
            "https://www.googleapis.com/auth/youtube": "Manage own account.",
            "https://www.googleapis.com/auth/youtube.upload": "Upload videos.",
            "https://www.googleapis.com/auth/youtube.force-ssl": "Comments / channel write.",
        },
        capabilities=frozenset(
            {ProviderCapability.READ, ProviderCapability.WRITE, ProviderCapability.SEARCH}
        ),
        documentation_url="https://developers.google.com/youtube/v3/docs",
        homepage_url="https://www.youtube.com/",
        tags=("social-media", "video"),
    )

    def __init__(
        self,
        *,
        token: TokenSource,
        base_url: str = "https://www.googleapis.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=make_bearer_auth(token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Internal helpers

    @staticmethod
    def _select_video_id(candidate: object) -> str:
        """Resolve a video ID from a string or a video dict from search/list."""
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("video_id must be a non-empty string")
            return candidate
        if isinstance(candidate, dict):
            mapping = cast(dict[str, Any], candidate)
            for key in ("video_id", "videoId", "id"):
                value: object = mapping.get(key)
                if isinstance(value, str) and value:
                    return value
                if isinstance(value, dict):
                    nested: object = cast(dict[str, Any], value).get("videoId")
                    if isinstance(nested, str) and nested:
                        return nested
        if isinstance(candidate, list) and candidate:
            first: object = cast(list[object], candidate)[0]
            return YouTubeToolSet._select_video_id(first)
        raise ValueError("could not resolve video_id from input")

    @classmethod
    def _video_summary(
        cls,
        item: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        snippet: dict[str, Any] = item.get("snippet") or {}
        statistics: dict[str, Any] = item.get("statistics") or {}
        content_details: dict[str, Any] = item.get("contentDetails") or {}
        video_id_field: object = item.get("id")
        if isinstance(video_id_field, dict):
            id_map = cast(dict[str, Any], video_id_field)
            video_id = id_map.get("videoId", "") or id_map.get("playlistId", "")
        else:
            video_id = video_id_field or ""
        summary: dict[str, Any] = {
            "video_ref": f"video_{index}",
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "posted_at": snippet.get("publishedAt", ""),
            "description": snippet.get("description", ""),
            "view_count": int(statistics.get("viewCount", 0)) if statistics.get("viewCount") else 0,
            "like_count": int(statistics.get("likeCount", 0)) if statistics.get("likeCount") else 0,
            "comment_count": int(statistics.get("commentCount", 0))
            if statistics.get("commentCount")
            else 0,
            "duration": content_details.get("duration", ""),
            "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
        }
        if include_ids:
            summary["video_id"] = video_id
            channel_id = snippet.get("channelId", "")
            if channel_id:
                summary["channel_id"] = channel_id
        return summary

    @classmethod
    def _comment_thread_summary(
        cls,
        thread: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        snippet: dict[str, Any] = thread.get("snippet") or {}
        top_comment: dict[str, Any] = snippet.get("topLevelComment") or {}
        comment_snippet: dict[str, Any] = top_comment.get("snippet") or {}
        summary: dict[str, Any] = {
            "comment_ref": f"comment_{index}",
            "author": comment_snippet.get("authorDisplayName", ""),
            "text": comment_snippet.get("textDisplay", "")
            or comment_snippet.get("textOriginal", ""),
            "posted_at": comment_snippet.get("publishedAt", ""),
            "like_count": comment_snippet.get("likeCount", 0),
            "reply_count": snippet.get("totalReplyCount", 0),
        }
        if include_ids:
            summary["thread_id"] = thread.get("id", "")
            summary["comment_id"] = top_comment.get("id", "")
        return summary

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_channels(
        self,
        *,
        mine: bool | None = None,
        id: list[str] | None = None,
        for_handle: str | None = None,
        for_username: str | None = None,
        part: list[str] | None = None,
    ) -> dict[str, Any]:
        """List YouTube channels matching a filter.

        Returns the raw YouTube channels response. Provide exactly one of
        ``mine=True`` (the authenticated user), ``id`` (channel IDs),
        ``for_handle`` (``@`` handle), or ``for_username`` (legacy
        username).
        """
        params: dict[str, Any] = {"part": ",".join(part or ["snippet", "statistics"])}
        if mine is not None:
            params["mine"] = str(mine).lower()
        if id is not None:
            params["id"] = ",".join(id)
        if for_handle is not None:
            params["forHandle"] = for_handle
        if for_username is not None:
            params["forUsername"] = for_username
        result: dict[str, Any] = self._client.get("/youtube/v3/channels", params=params).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_VIDEOS_OUTPUT)
    def list_videos(
        self,
        *,
        id: list[str],
        part: list[str] | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Look up videos by ID.

        Default returns compact summaries: ``video_ref`` (stable
        ``video_1``, ``video_2``, ...), ``title``, ``channel``,
        ``posted_at``, ``description``, view/like/comment counts,
        ``duration``, and ``url``. Raw video IDs are omitted unless
        ``include_ids=True``. Set ``include_metadata=False`` for the raw
        YouTube response.
        """
        if not id:
            raise ValueError("id must be non-empty")
        payload: dict[str, Any] = self._client.get(
            "/youtube/v3/videos",
            params={
                "id": ",".join(id),
                "part": ",".join(part or ["snippet", "statistics", "contentDetails"]),
            },
        ).json()
        if not include_metadata:
            return payload
        summaries: list[dict[str, Any]] = []
        items: list[Any] = payload.get("items", [])
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            video_item = cast(dict[str, Any], item)
            summaries.append(self._video_summary(video_item, index=index, include_ids=include_ids))
        return {
            "videos": summaries,
            "next_page_token": payload.get("nextPageToken"),
            "page_info": payload.get("pageInfo"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(SEARCH_OUTPUT)
    def search(
        self,
        *,
        q: str | None = None,
        channel_id: str | None = None,
        type: list[str] | None = None,
        order: str | None = None,
        max_results: int = 10,
        page_token: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Run a YouTube search.

        Best first tool for YouTube discovery. Default returns compact
        summaries: ``video_ref``, ``title``, ``channel`` name,
        ``posted_at``, ``description``, and ``url``. Raw YouTube video IDs
        are omitted unless ``include_ids=True``. Set
        ``include_metadata=False`` for the raw YouTube ``search.list``
        response.
        """
        params: dict[str, Any] = {
            "part": "snippet",
            "maxResults": max_results,
        }
        if q is not None:
            params["q"] = q
        if channel_id is not None:
            params["channelId"] = channel_id
        if type is not None:
            params["type"] = ",".join(type)
        if order is not None:
            params["order"] = order
        if page_token is not None:
            params["pageToken"] = page_token
        payload: dict[str, Any] = self._client.get("/youtube/v3/search", params=params).json()
        if not include_metadata:
            return payload
        summaries: list[dict[str, Any]] = []
        items: list[Any] = payload.get("items", [])
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            video_item = cast(dict[str, Any], item)
            summaries.append(self._video_summary(video_item, index=index, include_ids=include_ids))
        return {
            "videos": summaries,
            "next_page_token": payload.get("nextPageToken"),
            "page_info": payload.get("pageInfo"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_playlists(
        self,
        *,
        mine: bool | None = None,
        channel_id: str | None = None,
        id: list[str] | None = None,
        max_results: int = 25,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List playlists for the authenticated user or a channel.

        Returns the raw YouTube playlists response. Provide ``mine=True``,
        ``channel_id``, or ``id`` to scope the list.
        """
        params: dict[str, Any] = {"part": "snippet,contentDetails", "maxResults": max_results}
        if mine is not None:
            params["mine"] = str(mine).lower()
        if channel_id is not None:
            params["channelId"] = channel_id
        if id is not None:
            params["id"] = ",".join(id)
        if page_token is not None:
            params["pageToken"] = page_token
        result: dict[str, Any] = self._client.get("/youtube/v3/playlists", params=params).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_playlist_items(
        self,
        playlist_id: str,
        *,
        max_results: int = 25,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List items in a playlist.

        Returns the raw YouTube ``playlistItems.list`` response. Each item
        carries ``snippet.resourceId.videoId`` to use with ``list_videos``.
        """
        if not playlist_id:
            raise ValueError("playlist_id must be a non-empty string")
        params: dict[str, Any] = {
            "playlistId": playlist_id,
            "part": "snippet,contentDetails",
            "maxResults": max_results,
        }
        if page_token is not None:
            params["pageToken"] = page_token
        result: dict[str, Any] = self._client.get(
            "/youtube/v3/playlistItems",
            params=params,
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_to_playlist(
        self,
        *,
        playlist_id: str,
        video_id: str,
        position: int | None = None,
    ) -> dict[str, Any]:
        """Append a video to a playlist.

        Returns the new playlist item resource (``id``,
        ``snippet.playlistId``, ``snippet.resourceId.videoId``). Pass
        ``position`` to insert at a specific zero-based index.
        """
        if not playlist_id or not video_id:
            raise ValueError("playlist_id and video_id must be non-empty")
        snippet: dict[str, Any] = {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        }
        if position is not None:
            snippet["position"] = position
        result: dict[str, Any] = self._client.post(
            "/youtube/v3/playlistItems",
            params={"part": "snippet"},
            json={"snippet": snippet},
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_playlist_item(self, playlist_item_id: str) -> dict[str, Any]:
        """Remove an item from a playlist.

        Destructive: the playlist item is removed and cannot be recovered
        without re-adding the video.
        """
        if not playlist_item_id:
            raise ValueError("playlist_item_id must be a non-empty string")
        response = self._client.delete(
            "/youtube/v3/playlistItems",
            params={"id": playlist_item_id},
        )
        return {"id": playlist_item_id, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_video(
        self,
        *,
        video_id: str,
        snippet: dict[str, Any] | None = None,
        status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update an existing video's snippet and/or status.

        Returns the updated video resource. This is a full-replace on the
        parts you provide — fields you omit are reset to defaults on those
        parts.
        """
        if not video_id:
            raise ValueError("video_id must be a non-empty string")
        body: dict[str, Any] = {"id": video_id}
        parts: list[str] = []
        if snippet is not None:
            body["snippet"] = snippet
            parts.append("snippet")
        if status is not None:
            body["status"] = status
            parts.append("status")
        if not parts:
            raise ValueError("provide snippet or status")
        result: dict[str, Any] = self._client.put(
            "/youtube/v3/videos",
            params={"part": ",".join(parts)},
            json=body,
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_video(self, video: str | dict[str, Any]) -> dict[str, Any]:
        """Permanently delete a video.

        Accepts a raw ``video_id`` string OR a video/search result dict
        (looks up ``video_id`` / ``id.videoId`` / ``id``). Destructive and
        not reversible — confirm with the user.
        """
        video_id = self._select_video_id(video)
        response = self._client.delete(
            "/youtube/v3/videos",
            params={"id": video_id},
        )
        return {"id": video_id, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_COMMENT_THREADS_OUTPUT)
    def list_comment_threads(
        self,
        *,
        video_id: str | None = None,
        channel_id: str | None = None,
        max_results: int = 10,
        page_token: str | None = None,
        order: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List top-level comment threads on a video or channel.

        Default returns compact summaries: ``comment_ref``, ``author``,
        ``text``, ``posted_at``, ``like_count``, ``reply_count``. Raw IDs
        are omitted unless ``include_ids=True``. Set
        ``include_metadata=False`` for the raw YouTube response.
        """
        params: dict[str, Any] = {
            "part": "snippet,replies",
            "maxResults": max_results,
        }
        if video_id is not None:
            params["videoId"] = video_id
        elif channel_id is not None:
            params["channelId"] = channel_id
        else:
            raise ValueError("provide video_id or channel_id")
        if page_token is not None:
            params["pageToken"] = page_token
        if order is not None:
            params["order"] = order
        payload: dict[str, Any] = self._client.get(
            "/youtube/v3/commentThreads",
            params=params,
        ).json()
        if not include_metadata:
            return payload
        summaries: list[dict[str, Any]] = []
        items: list[Any] = payload.get("items", [])
        for index, thread in enumerate(items, start=1):
            if not isinstance(thread, dict):
                continue
            thread_item = cast(dict[str, Any], thread)
            summaries.append(
                self._comment_thread_summary(thread_item, index=index, include_ids=include_ids)
            )
        return {
            "comments": summaries,
            "next_page_token": payload.get("nextPageToken"),
            "page_info": payload.get("pageInfo"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def post_comment(
        self,
        *,
        video_id: str | None = None,
        channel_id: str | None = None,
        text: str,
    ) -> dict[str, Any]:
        """Post a top-level comment on a video or channel.

        Returns the new comment thread resource. For a video comment, pass
        BOTH ``video_id`` and ``channel_id`` (the uploading channel's ID) —
        the YouTube ``commentThreads.insert`` API requires both. For a
        channel-page comment, pass ``channel_id`` alone.
        """
        if not text:
            raise ValueError("text must be a non-empty string")
        if video_id is None and channel_id is None:
            raise ValueError("provide video_id or channel_id")
        if video_id is not None and channel_id is None:
            raise ValueError("channel_id is required alongside video_id for a video comment")
        snippet: dict[str, Any] = {
            "topLevelComment": {"snippet": {"textOriginal": text}},
        }
        if video_id is not None:
            snippet["videoId"] = video_id
        if channel_id is not None:
            snippet["channelId"] = channel_id
        result: dict[str, Any] = self._client.post(
            "/youtube/v3/commentThreads",
            params={"part": "snippet"},
            json={"snippet": snippet},
        ).json()
        return result
