"""Instagram Graph API (Business / Creator accounts) connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

_API_VERSION = "v25.0"


@toolset(prefix="instagram")
class InstagramToolSet:
    """A connector for the Instagram Graph API.

    Requires a Business or Creator Instagram account linked to a
    Facebook Page. The access token is a Page access token with
    ``instagram_basic`` / ``instagram_content_publish`` scopes.
    """

    metadata = ProviderMetadata(
        name="instagram",
        display_name="Instagram",
        version="0.1.0",
        description="Media, stories, comments, insights, and content publishing.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "instagram_basic": "Read media + profile.",
            "instagram_content_publish": "Publish photos / videos / reels.",
            "instagram_manage_comments": "Reply to / delete comments.",
            "instagram_manage_insights": "Read insights.",
        },
        capabilities=frozenset(
            {ProviderCapability.READ, ProviderCapability.WRITE, ProviderCapability.PAGINATION}
        ),
        documentation_url="https://developers.facebook.com/docs/instagram-platform/",
        homepage_url="https://www.instagram.com/",
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

    @classmethod
    def _media_summary(
        cls,
        media: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "media_ref": f"media_{index}",
            "caption": media.get("caption", ""),
            "media_type": media.get("media_type", ""),
            "permalink": media.get("permalink", ""),
            "posted_at": media.get("timestamp", ""),
            "like_count": media.get("like_count", 0),
            "comments_count": media.get("comments_count", 0),
        }
        if include_ids:
            summary["media_id"] = media.get("id", "")
        return summary

    @classmethod
    def _comment_summary(
        cls,
        comment: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        username = comment.get("username", "") or comment.get("from", {}).get("username", "")
        summary: dict[str, Any] = {
            "comment_ref": f"comment_{index}",
            "author": username,
            "text": comment.get("text", ""),
            "posted_at": comment.get("timestamp", ""),
            "like_count": comment.get("like_count", 0),
        }
        if include_ids:
            summary["comment_id"] = comment.get("id", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_account(self, ig_user_id: str, *, fields: list[str] | None = None) -> dict[str, Any]:
        """Return profile info for an Instagram Business / Creator account.

        Returns the IG user resource (``id``, ``username``, ``name``,
        ``profile_picture_url``, and any extra ``fields`` such as
        ``followers_count``, ``media_count``).
        """
        if not ig_user_id:
            raise ValueError("ig_user_id must be a non-empty string")
        params: dict[str, Any] = {}
        if fields is not None:
            params["fields"] = ",".join(fields)
        return self._client.get(
            self._path(f"/{ig_user_id}"),
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_media(
        self,
        ig_user_id: str,
        *,
        limit: int = 10,
        after: str | None = None,
        fields: list[str] | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List media (posts and reels) on an Instagram account.

        Best first tool for Instagram triage. Default returns compact
        summaries: ``media_ref`` (stable ``media_1``, ``media_2``, ...),
        ``caption``, ``media_type``, ``permalink``, ``posted_at``, like/
        comment counts. Raw IG media IDs are omitted by default; set
        ``include_ids=True`` only when a follow-up tool needs the raw
        ``media_id`` (``get_media``, ``get_media_insights``,
        ``list_comments``). Set ``include_metadata=False`` for the raw
        Graph response.
        """
        if not ig_user_id:
            raise ValueError("ig_user_id must be a non-empty string")
        params: dict[str, Any] = {"limit": limit}
        if after is not None:
            params["after"] = after
        merged_fields = list(fields) if fields else []
        if include_metadata:
            for needed in (
                "caption",
                "media_type",
                "permalink",
                "timestamp",
                "like_count",
                "comments_count",
            ):
                if needed not in merged_fields:
                    merged_fields.append(needed)
        if merged_fields:
            params["fields"] = ",".join(merged_fields)
        payload: dict[str, Any] = self._client.get(
            self._path(f"/{ig_user_id}/media"),
            params=params,
        ).json()
        if not include_metadata:
            return payload
        summaries: list[dict[str, Any]] = []
        data: list[Any] = payload.get("data", [])
        for index, media in enumerate(data, start=1):
            if not isinstance(media, dict):
                continue
            media_obj = cast(dict[str, Any], media)
            summaries.append(self._media_summary(media_obj, index=index, include_ids=include_ids))
        return {
            "media": summaries,
            "paging": payload.get("paging"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_media(self, media_id: str, *, fields: list[str] | None = None) -> dict[str, Any]:
        """Fetch one media item by its IG internal ID.

        Returns the raw Graph media resource. Use after
        ``list_media(include_ids=True)`` when you need full media details.
        """
        if not media_id:
            raise ValueError("media_id must be a non-empty string")
        params: dict[str, Any] = {}
        if fields is not None:
            params["fields"] = ",".join(fields)
        return self._client.get(
            self._path(f"/{media_id}"),
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_media_container(
        self,
        ig_user_id: str,
        *,
        image_url: str | None = None,
        video_url: str | None = None,
        caption: str | None = None,
        media_type: str | None = None,
        is_carousel_item: bool | None = None,
        children: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a media container as step 1 of the two-step publish flow.

        Returns ``{"id": "<creation_id>"}``. Pass the ``id`` to
        :meth:`publish_media` to actually publish the post. For carousels,
        first call this once per child (with ``is_carousel_item=True``),
        then again with ``media_type="CAROUSEL"`` and ``children=[<ids>]``.
        """
        if not ig_user_id:
            raise ValueError("ig_user_id must be a non-empty string")
        if image_url is None and video_url is None and not children:
            raise ValueError("provide image_url, video_url, or children")
        body: dict[str, Any] = {}
        if image_url is not None:
            body["image_url"] = image_url
        if video_url is not None:
            body["video_url"] = video_url
        if caption is not None:
            body["caption"] = caption
        if media_type is not None:
            body["media_type"] = media_type
        if is_carousel_item is not None:
            body["is_carousel_item"] = is_carousel_item
        if children is not None:
            body["children"] = ",".join(children)
        return self._client.post(
            self._path(f"/{ig_user_id}/media"),
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def publish_media(self, ig_user_id: str, *, creation_id: str) -> dict[str, Any]:
        """Publish a previously-created media container.

        Returns the new media resource (``id``). Confirm with the user
        before calling — this posts publicly to the account's grid.
        """
        if not ig_user_id or not creation_id:
            raise ValueError("ig_user_id and creation_id must be non-empty")
        return self._client.post(
            self._path(f"/{ig_user_id}/media_publish"),
            json={"creation_id": creation_id},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_container_status(self, container_id: str) -> dict[str, Any]:
        """Check the upload/processing status of a media container.

        Returns ``{"status_code": "FINISHED" | "IN_PROGRESS" | "ERROR" |
        ...}``. Poll until ``FINISHED`` before calling ``publish_media``.
        """
        if not container_id:
            raise ValueError("container_id must be a non-empty string")
        return self._client.get(
            self._path(f"/{container_id}"),
            params={"fields": "status_code,status"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_comments(
        self,
        media_id: str,
        *,
        limit: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List comments on a media item.

        Default returns compact summaries (``comment_ref``, ``author``
        username, ``text``, ``posted_at``, ``like_count``). Raw comment IDs
        are omitted unless ``include_ids=True``. Set
        ``include_metadata=False`` for the raw Graph response.
        """
        if not media_id:
            raise ValueError("media_id must be a non-empty string")
        params: dict[str, Any] = {"limit": limit}
        if include_metadata:
            params["fields"] = "username,text,timestamp,like_count"
        payload: dict[str, Any] = self._client.get(
            self._path(f"/{media_id}/comments"),
            params=params,
        ).json()
        if not include_metadata:
            return payload
        summaries: list[dict[str, Any]] = []
        data: list[Any] = payload.get("data", [])
        for index, comment in enumerate(data, start=1):
            if not isinstance(comment, dict):
                continue
            comment_obj = cast(dict[str, Any], comment)
            summaries.append(
                self._comment_summary(comment_obj, index=index, include_ids=include_ids)
            )
        return {
            "comments": summaries,
            "paging": payload.get("paging"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def reply_to_comment(self, comment_id: str, *, message: str) -> dict[str, Any]:
        """Reply to an Instagram comment.

        Returns the new reply resource (``id``). ``comment_id`` is the
        Graph internal ID returned by ``list_comments(include_ids=True)``.
        """
        if not comment_id or not message:
            raise ValueError("comment_id and message must be non-empty")
        return self._client.post(
            self._path(f"/{comment_id}/replies"),
            json={"message": message},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_comment(self, comment_id: str) -> dict[str, Any]:
        """Permanently delete an Instagram comment.

        Destructive and not reversible. Confirm with the user before
        calling.
        """
        if not comment_id:
            raise ValueError("comment_id must be a non-empty string")
        return self._client.delete(self._path(f"/{comment_id}")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def hide_comment(self, comment_id: str, *, hide: bool = True) -> dict[str, Any]:
        """Hide or unhide a comment.

        Less destructive than ``delete_comment`` — the comment is still
        retrievable. Pass ``hide=False`` to unhide.
        """
        if not comment_id:
            raise ValueError("comment_id must be a non-empty string")
        return self._client.post(
            self._path(f"/{comment_id}"),
            json={"hide": hide},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_media_insights(
        self,
        media_id: str,
        *,
        metric: list[str],
    ) -> dict[str, Any]:
        """Get insights for one media item.

        ``metric`` is the list of insight names (e.g. ``["impressions",
        "reach", "engagement"]``). Returns the raw Graph insights response.
        """
        if not media_id or not metric:
            raise ValueError("media_id and metric must be non-empty")
        return self._client.get(
            self._path(f"/{media_id}/insights"),
            params={"metric": ",".join(metric)},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_account_insights(
        self,
        ig_user_id: str,
        *,
        metric: list[str],
        period: str = "day",
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """Get account-level insights.

        Returns the raw Graph insights response. ``metric`` is the list of
        account-level insight names (e.g. ``["reach", "impressions"]``).
        """
        if not ig_user_id or not metric:
            raise ValueError("ig_user_id and metric must be non-empty")
        params: dict[str, Any] = {"metric": ",".join(metric), "period": period}
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        return self._client.get(
            self._path(f"/{ig_user_id}/insights"),
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_stories(self, ig_user_id: str) -> dict[str, Any]:
        """List currently-active stories for an Instagram account.

        Returns the raw Graph response. Stories are ephemeral (24 hours),
        so the list will be short.
        """
        if not ig_user_id:
            raise ValueError("ig_user_id must be a non-empty string")
        return self._client.get(self._path(f"/{ig_user_id}/stories")).json()
