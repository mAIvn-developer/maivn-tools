"""TikTok Content Posting + Display API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_VIDEOS_OUTPUT


@toolset(prefix="tiktok")
class TikTokToolSet:
    """A connector for TikTok's Content Posting + Display APIs.

    Args:
        access_token: OAuth 2.0 access token (user-context).
        base_url: API root. The default targets
            ``open.tiktokapis.com``.
    """

    metadata = ProviderMetadata(
        name="tiktok",
        display_name="TikTok",
        version="0.1.0",
        description="Creator info, content upload, video management, and user info.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "user.info.basic": "Basic user profile.",
            "user.info.profile": "Full profile.",
            "user.info.stats": "Follower / video stats.",
            "video.list": "Read the user's videos.",
            "video.upload": "Upload videos.",
            "video.publish": "Publish videos.",
        },
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developers.tiktok.com/doc/login-kit-web",
        homepage_url="https://www.tiktok.com/",
        tags=("social-media", "video"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        base_url: str = "https://open.tiktokapis.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(access_token),
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

    @classmethod
    def _video_summary(
        cls,
        video: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        username = video.get("username", "")
        video_id = video.get("id", "")
        share_url = video.get("share_url", "")
        if not share_url and username and video_id:
            share_url = f"https://www.tiktok.com/@{username}/video/{video_id}"
        summary: dict[str, Any] = {
            "video_ref": f"video_{index}",
            "title": video.get("title", "") or video.get("video_description", ""),
            "author": username,
            "posted_at": video.get("create_time", ""),
            "view_count": video.get("view_count", 0),
            "like_count": video.get("like_count", 0),
            "comment_count": video.get("comment_count", 0),
            "share_count": video.get("share_count", 0),
            "duration": video.get("duration", 0),
            "url": share_url,
        }
        if include_ids:
            summary["video_id"] = video_id
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user_info(self, *, fields: list[str] | None = None) -> dict[str, Any]:
        """Return the authenticated user's profile.

        Returns the raw TikTok user info response. ``fields`` selects
        which user fields are returned (e.g. ``["open_id", "username",
        "display_name", "avatar_url"]``).
        """
        params: dict[str, Any] = {}
        if fields is not None:
            params["fields"] = ",".join(fields)
        return self._client.get(
            "/v2/user/info/",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_VIDEOS_OUTPUT)
    def list_videos(
        self,
        *,
        fields: list[str] | None = None,
        cursor: int = 0,
        max_count: int = 10,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List the authenticated user's videos.

        Best first tool for TikTok video triage. Default returns compact
        summaries: ``video_ref`` (stable ``video_1``, ``video_2``, ...),
        ``title``, ``author`` username, ``posted_at``, ``view_count``,
        ``like_count``, ``comment_count``, ``share_count``, ``duration``,
        and ``url``. Raw TikTok video IDs are omitted unless
        ``include_ids=True``. ``include_metadata=False`` returns the raw
        TikTok response. ``max_count`` is capped at 20 by the TikTok API.
        """
        if max_count < 1 or max_count > 20:
            raise ValueError("max_count must be between 1 and 20")
        merged_fields = list(fields) if fields else []
        if include_metadata:
            for needed in (
                "id",
                "title",
                "video_description",
                "username",
                "create_time",
                "view_count",
                "like_count",
                "comment_count",
                "share_count",
                "duration",
                "share_url",
            ):
                if needed not in merged_fields:
                    merged_fields.append(needed)
        if not merged_fields:
            raise ValueError("fields must be non-empty")
        payload: dict[str, Any] = self._client.post(
            "/v2/video/list/",
            params={"fields": ",".join(merged_fields)},
            json={"cursor": cursor, "max_count": max_count},
        ).json()
        if not include_metadata:
            return payload
        raw_data: Any = payload.get("data") or {}
        data: dict[str, Any] = (
            cast("dict[str, Any]", raw_data) if isinstance(raw_data, dict) else {}
        )
        raw_videos: Any = data.get("videos", [])
        videos: list[Any] = cast("list[Any]", raw_videos) if isinstance(raw_videos, list) else []
        summaries: list[dict[str, Any]] = []
        for index, video in enumerate(videos, start=1):
            if not isinstance(video, dict):
                continue
            video_dict: dict[str, Any] = cast("dict[str, Any]", video)
            summaries.append(self._video_summary(video_dict, index=index, include_ids=include_ids))
        return {
            "videos": summaries,
            "cursor": data.get("cursor"),
            "has_more": data.get("has_more"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def query_videos(
        self,
        *,
        video_ids: list[str],
        fields: list[str],
    ) -> dict[str, Any]:
        """Look up specific videos by ID.

        Returns the raw TikTok response. Use when you already have a known
        list of TikTok video IDs (for example from prior ``list_videos``
        responses with ``include_ids=True``).
        """
        if not video_ids:
            raise ValueError("video_ids must be non-empty")
        if not fields:
            raise ValueError("fields must be non-empty")
        return self._client.post(
            "/v2/video/query/",
            params={"fields": ",".join(fields)},
            json={"filters": {"video_ids": video_ids}},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_creator_info(self) -> dict[str, Any]:
        """Query creator posting limits + available privacy options.

        Returns the raw creator info response. Call this before
        ``init_video_upload`` to honour the creator's allowed
        ``privacy_level`` values and posting rate limits.
        """
        return self._client.post("/v2/post/publish/creator_info/query/", json={}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def init_video_upload(
        self,
        *,
        post_info: dict[str, Any],
        source_info: dict[str, Any],
    ) -> dict[str, Any]:
        """Initiate a direct-from-URL or chunked video upload.

        Returns ``{"data": {"publish_id": ...}}``. Use the ``publish_id``
        to poll ``get_publish_status`` until the post finishes uploading
        and publishing.
        """
        if not post_info or not source_info:
            raise ValueError("post_info and source_info must be non-empty")
        return self._client.post(
            "/v2/post/publish/video/init/",
            json={"post_info": post_info, "source_info": source_info},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def init_inbox_upload(self, source_info: dict[str, Any]) -> dict[str, Any]:
        """Upload a video to the user's inbox for manual review.

        Returns ``{"data": {"publish_id": ...}}``. The video is delivered
        to the user's TikTok inbox; they choose whether and when to
        publish.
        """
        if not source_info:
            raise ValueError("source_info must be non-empty")
        return self._client.post(
            "/v2/post/publish/inbox/video/init/",
            json={"source_info": source_info},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_publish_status(self, publish_id: str) -> dict[str, Any]:
        """Check the status of an upload/publish initiated by ``init_*``.

        Returns ``{"data": {"status": "..."}}``. Poll until status is a
        terminal value (``PUBLISH_COMPLETE`` / ``FAILED``) before
        considering the upload complete.
        """
        if not publish_id:
            raise ValueError("publish_id must be a non-empty string")
        return self._client.post(
            "/v2/post/publish/status/fetch/",
            json={"publish_id": publish_id},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def init_photo_publish(
        self,
        *,
        post_info: dict[str, Any],
        photo_images: list[str],
    ) -> dict[str, Any]:
        """Publish a photo carousel by URL.

        Returns ``{"data": {"publish_id": ...}}``. ``photo_images`` is a
        list of image URLs accessible from TikTok's servers. Poll
        ``get_publish_status`` with the returned ``publish_id``.
        """
        if not post_info or not photo_images:
            raise ValueError("post_info and photo_images must be non-empty")
        return self._client.post(
            "/v2/post/publish/content/init/",
            json={
                "post_info": post_info,
                "source_info": {
                    "source": "PULL_FROM_URL",
                    "photo_images": photo_images,
                    "photo_cover_index": 0,
                },
                "post_mode": "DIRECT_POST",
                "media_type": "PHOTO",
            },
        ).json()
