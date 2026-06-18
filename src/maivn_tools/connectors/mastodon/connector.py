"""Mastodon REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import (
    HASHTAG_TIMELINE_OUTPUT,
    HOME_TIMELINE_OUTPUT,
    PUBLIC_TIMELINE_OUTPUT,
)


@toolset(prefix="mastodon")
class MastodonToolSet:
    """A connector for any Mastodon-compatible instance.

    Args:
        access_token: OAuth 2.0 bearer token issued by the target instance.
        instance_url: Full instance URL, e.g. ``https://mastodon.social``.
    """

    metadata = ProviderMetadata(
        name="mastodon",
        display_name="Mastodon",
        version="0.1.0",
        description="Statuses, timelines, accounts, follows, and notifications.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "read": "Read account, timeline, and notifications.",
            "write": "Post statuses and follow accounts.",
            "follow": "Follow / unfollow.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://docs.joinmastodon.org/api/",
        homepage_url="https://joinmastodon.org/",
        tags=("social-media", "fediverse"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        instance_url: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        if not instance_url:
            raise ValueError("instance_url is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=instance_url.rstrip("/"),
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

    @staticmethod
    def _select_status_id(candidate: Any) -> str:
        """Resolve a Mastodon status ID from a string or a status dict."""
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("status_id must be a non-empty string")
            return candidate
        if isinstance(candidate, dict):
            candidate_dict = cast("dict[str, Any]", candidate)
            for key in ("status_id", "id"):
                value: Any = candidate_dict.get(key)
                if isinstance(value, str) and value:
                    return value
        if isinstance(candidate, list) and candidate:
            candidate_list = cast("list[Any]", candidate)
            return MastodonToolSet._select_status_id(candidate_list[0])
        raise ValueError("could not resolve status_id from input")

    @classmethod
    def _status_summary(
        cls,
        status: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        account_raw: Any = status.get("account") or {}
        account: dict[str, Any] | None = (
            cast("dict[str, Any]", account_raw) if isinstance(account_raw, dict) else None
        )
        acct: Any = account.get("acct", "") if account is not None else ""
        summary: dict[str, Any] = {
            "status_ref": f"status_{index}",
            "author": acct,
            "author_name": account.get("display_name", "") if account is not None else "",
            "content": status.get("content", ""),
            "posted_at": status.get("created_at", ""),
            "spoiler_text": status.get("spoiler_text", ""),
            "visibility": status.get("visibility", ""),
            "favourites_count": status.get("favourites_count", 0),
            "reblogs_count": status.get("reblogs_count", 0),
            "replies_count": status.get("replies_count", 0),
            "url": status.get("url", ""),
        }
        if include_ids:
            summary["status_id"] = status.get("id", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def verify_credentials(self) -> dict[str, Any]:
        """Return the authenticated account.

        Returns the raw Mastodon ``CredentialAccount`` resource.
        Useful as a connection sanity check.
        """
        return self._client.get("/api/v1/accounts/verify_credentials").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_account(self, account_id: str) -> dict[str, Any]:
        """Return an account by its instance-local numeric ID.

        Returns the raw Mastodon account resource.
        """
        if not account_id:
            raise ValueError("account_id is required")
        return self._client.get(f"/api/v1/accounts/{account_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def lookup_account(self, acct: str) -> dict[str, Any]:
        """Look up an account by ``user@instance`` handle.

        Returns the raw Mastodon account resource — useful for resolving
        a handle to its numeric ``id`` (needed for follow/unfollow).
        """
        if not acct:
            raise ValueError("acct is required")
        return self._client.get("/api/v1/accounts/lookup", params={"acct": acct}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(HOME_TIMELINE_OUTPUT)
    def home_timeline(
        self,
        *,
        limit: int = 20,
        max_id: str | None = None,
        since_id: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Return the authenticated user's home timeline.

        Default returns compact summaries: ``status_ref`` (stable
        ``status_1`` ...), ``author`` (acct handle), ``author_name``,
        ``content`` (HTML), ``posted_at``, ``visibility``, favourites/
        reblogs/replies counts, and ``url``. Raw Mastodon status IDs are
        omitted unless ``include_ids=True``. Set ``include_metadata=False``
        for the raw Mastodon response.
        """
        params: dict[str, Any] = {"limit": limit}
        if max_id is not None:
            params["max_id"] = max_id
        if since_id is not None:
            params["since_id"] = since_id
        payload = self._client.get("/api/v1/timelines/home", params=params).json()
        return self._summarize_statuses(payload, include_metadata, include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(PUBLIC_TIMELINE_OUTPUT)
    def public_timeline(
        self,
        *,
        local: bool = False,
        remote: bool = False,
        only_media: bool = False,
        limit: int = 20,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Return the public timeline.

        Same return shape as ``home_timeline`` — compact summaries by
        default, raw response with ``include_metadata=False``.
        """
        payload = self._client.get(
            "/api/v1/timelines/public",
            params={
                "local": str(local).lower(),
                "remote": str(remote).lower(),
                "only_media": str(only_media).lower(),
                "limit": limit,
            },
        ).json()
        return self._summarize_statuses(payload, include_metadata, include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(HASHTAG_TIMELINE_OUTPUT)
    def hashtag_timeline(
        self,
        hashtag: str,
        *,
        limit: int = 20,
        max_id: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Return a hashtag timeline.

        Same return shape as ``home_timeline`` — compact ``status_ref``
        summaries by default.
        """
        if not hashtag:
            raise ValueError("hashtag is required")
        params: dict[str, Any] = {"limit": limit}
        if max_id is not None:
            params["max_id"] = max_id
        payload = self._client.get(f"/api/v1/timelines/tag/{hashtag}", params=params).json()
        return self._summarize_statuses(payload, include_metadata, include_ids)

    def _summarize_statuses(
        self,
        payload: Any,
        include_metadata: bool,
        include_ids: bool,
    ) -> dict[str, Any]:
        if not include_metadata:
            return {"statuses": payload} if isinstance(payload, list) else payload
        statuses_list: list[Any]
        if isinstance(payload, list):
            statuses_list = cast("list[Any]", payload)
        elif isinstance(payload, dict):
            payload_dict = cast("dict[str, Any]", payload)
            statuses_list = payload_dict.get("statuses", [])
        else:
            statuses_list = []
        summaries: list[dict[str, Any]] = []
        for index, status in enumerate(statuses_list, start=1):
            if not isinstance(status, dict):
                continue
            status_dict = cast("dict[str, Any]", status)
            summaries.append(
                self._status_summary(status_dict, index=index, include_ids=include_ids)
            )
        return {"statuses": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_status(self, status_id: str) -> dict[str, Any]:
        """Fetch a single status by ID.

        Returns the raw Mastodon status resource.
        """
        if not status_id:
            raise ValueError("status_id is required")
        return self._client.get(f"/api/v1/statuses/{status_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def post_status(
        self,
        *,
        status: str,
        in_reply_to_id: str | None = None,
        media_ids: list[str] | None = None,
        visibility: str = "public",
        spoiler_text: str | None = None,
        sensitive: bool = False,
        language: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Publish a status.

        Returns the new status resource. Confirm content with the user
        before calling. ``visibility`` must be ``public``, ``unlisted``,
        ``private``, or ``direct``.
        """
        if not status and not media_ids:
            raise ValueError("status or media_ids is required")
        if visibility not in {"public", "unlisted", "private", "direct"}:
            raise ValueError("visibility must be public/unlisted/private/direct")
        body: dict[str, Any] = {
            "status": status,
            "visibility": visibility,
            "sensitive": sensitive,
        }
        if in_reply_to_id is not None:
            body["in_reply_to_id"] = in_reply_to_id
        if media_ids is not None:
            body["media_ids"] = media_ids
        if spoiler_text is not None:
            body["spoiler_text"] = spoiler_text
        if language is not None:
            body["language"] = language
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._client.post("/api/v1/statuses", json=body, headers=headers).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_status(self, status: str | dict[str, Any]) -> dict[str, Any]:
        """Permanently delete a status.

        Accepts a raw ``status_id`` string OR a status dict from a
        timeline/search call (looks up ``status_id`` / ``id``).
        Destructive and not reversible — confirm with the user.
        """
        status_id = self._select_status_id(status)
        return self._client.delete(f"/api/v1/statuses/{status_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def favourite_status(self, status: str | dict[str, Any]) -> dict[str, Any]:
        """Favourite a status.

        Accepts a raw ``status_id`` or a status dict from a timeline.
        """
        status_id = self._select_status_id(status)
        return self._client.post(f"/api/v1/statuses/{status_id}/favourite").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def reblog_status(
        self,
        status: str | dict[str, Any],
        *,
        visibility: str = "public",
    ) -> dict[str, Any]:
        """Boost (reblog) a status.

        Accepts a raw ``status_id`` or a status dict from a timeline.
        """
        status_id = self._select_status_id(status)
        return self._client.post(
            f"/api/v1/statuses/{status_id}/reblog",
            json={"visibility": visibility},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def follow_account(self, account_id: str) -> dict[str, Any]:
        """Follow an account by its numeric ID.

        Use ``lookup_account`` to resolve a ``user@instance`` handle to
        its numeric ID first.
        """
        if not account_id:
            raise ValueError("account_id is required")
        return self._client.post(f"/api/v1/accounts/{account_id}/follow").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def unfollow_account(self, account_id: str) -> dict[str, Any]:
        """Unfollow an account by its numeric ID.

        Confirm with the user before calling.
        """
        if not account_id:
            raise ValueError("account_id is required")
        return self._client.post(f"/api/v1/accounts/{account_id}/unfollow").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_notifications(
        self,
        *,
        types: list[str] | None = None,
        limit: int = 20,
        max_id: str | None = None,
    ) -> dict[str, Any]:
        """List notifications for the authenticated user.

        Returns the raw Mastodon notifications response.
        """
        params: dict[str, Any] = {"limit": limit}
        if types is not None:
            params["types[]"] = types
        if max_id is not None:
            params["max_id"] = max_id
        return self._client.get("/api/v1/notifications", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search(
        self,
        query: str,
        *,
        type: str | None = None,
        resolve: bool = False,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search accounts, hashtags, or statuses.

        Returns the raw Mastodon v2 search response. ``type`` is one of
        ``accounts``, ``hashtags``, ``statuses`` (or ``None`` for all).
        """
        if not query:
            raise ValueError("query is required")
        if type is not None and type not in {"accounts", "hashtags", "statuses"}:
            raise ValueError("type must be accounts/hashtags/statuses")
        params: dict[str, Any] = {
            "q": query,
            "resolve": str(resolve).lower(),
            "limit": limit,
        }
        if type is not None:
            params["type"] = type
        return self._client.get("/api/v2/search", params=params).json()
