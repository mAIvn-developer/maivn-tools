"""LinkedIn REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast
from urllib.parse import quote

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# LinkedIn uses monthly API versions (YYYYMM) with a ~12-month rolling support
# window. 202410 was sunset on 2025-10-15; keep this pinned to a currently
# active version moniker.
_API_VERSION = "202605"


@toolset(prefix="linkedin")
class LinkedInToolSet:
    """A connector for the LinkedIn REST API.

    Args:
        access_token: OAuth 2.0 bearer token. The required scopes depend
            on which endpoints you call (``profile``, ``email``,
            ``w_member_social``, ``r_organization_social``,
            ``w_organization_social``, etc.).
        linkedin_version: Versioning header. LinkedIn now uses monthly
            versions (e.g. ``"202605"``).
    """

    metadata = ProviderMetadata(
        name="linkedin",
        display_name="LinkedIn",
        version="0.1.0",
        description="Profile, posts, comments, and organization endpoints.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "openid": "User identity (OIDC).",
            "profile": "Basic profile.",
            "email": "Primary email.",
            "w_member_social": "Post on behalf of member.",
            "r_organization_social": "Read organization posts.",
            "w_organization_social": "Post on behalf of organization.",
        },
        capabilities=frozenset(
            {ProviderCapability.READ, ProviderCapability.WRITE, ProviderCapability.PAGINATION}
        ),
        documentation_url="https://learn.microsoft.com/en-us/linkedin/",
        homepage_url="https://www.linkedin.com/",
        tags=("social-media", "professional"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        linkedin_version: str = _API_VERSION,
        base_url: str = "https://api.linkedin.com",
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
                "LinkedIn-Version": linkedin_version,
                "X-Restli-Protocol-Version": "2.0.0",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Internal helpers

    @staticmethod
    def _select_post_urn(candidate: Any) -> str:
        """Resolve a post URN from a string or a post dict returned by listings."""
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("post_urn must be a non-empty string")
            return candidate
        if isinstance(candidate, dict):
            candidate_dict = cast(dict[str, Any], candidate)
            for key in ("post_urn", "urn", "id"):
                value: Any = candidate_dict.get(key)
                if isinstance(value, str) and value:
                    return value
        if isinstance(candidate, list) and candidate:
            first = cast(Any, candidate[0])
            return LinkedInToolSet._select_post_urn(first)
        raise ValueError("could not resolve post_urn from input")

    @classmethod
    def _post_summary(
        cls,
        post: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        urn = post.get("id", "") or post.get("urn", "")
        commentary = post.get("commentary", "")
        author = post.get("author", "")
        summary: dict[str, Any] = {
            "post_ref": f"post_{index}",
            "author": author,
            "commentary": commentary,
            "posted_at": post.get("publishedAt", "") or post.get("createdAt", ""),
            "visibility": post.get("visibility", ""),
            "lifecycle_state": post.get("lifecycleState", ""),
        }
        if include_ids:
            summary["post_urn"] = urn
        return summary

    @classmethod
    def _comment_summary(
        cls,
        comment: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        message: Any = comment.get("message") or {}
        text: Any = (
            cast(dict[str, Any], message).get("text", "") if isinstance(message, dict) else ""
        )
        summary: dict[str, Any] = {
            "comment_ref": f"comment_{index}",
            "actor": comment.get("actor", ""),
            "text": text,
            "posted_at": comment.get("createdAt", ""),
        }
        if include_ids:
            summary["comment_id"] = comment.get("id", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_userinfo(self) -> dict[str, Any]:
        """Return OIDC-style userinfo for the authenticated member.

        Returns the OIDC userinfo claims (``sub``, ``name``, ``email``,
        ``picture``). Cheap, useful as a connection sanity check.
        """
        return self._client.get("/v2/userinfo").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_me(self, *, projection: str | None = None) -> dict[str, Any]:
        """Return the lite member profile (v2 ``/me``).

        Returns the raw v2 ``/me`` resource. ``projection`` is a LinkedIn
        projection string (e.g. ``"(id,localizedFirstName)"``) for
        field-selecting the response.
        """
        params: dict[str, Any] = {}
        if projection is not None:
            params["projection"] = projection
        return self._client.get("/v2/me", params=params or None).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_post(
        self,
        *,
        author_urn: str,
        commentary: str,
        visibility: str = "PUBLIC",
        media: list[dict[str, Any]] | None = None,
        feed_distribution: str = "MAIN_FEED",
        lifecycle_state: str = "PUBLISHED",
    ) -> dict[str, Any]:
        """Publish a post via the ``/rest/posts`` endpoint.

        Returns the new post resource (``id`` is the new post URN, e.g.
        ``urn:li:share:123...``). ``author_urn`` is the URN of the member
        or organization publishing the post (``urn:li:person:...`` or
        ``urn:li:organization:...``).
        """
        if not author_urn or not commentary:
            raise ValueError("author_urn and commentary must be non-empty")
        if visibility not in {"PUBLIC", "CONNECTIONS", "LOGGED_IN"}:
            raise ValueError("visibility must be PUBLIC/CONNECTIONS/LOGGED_IN")
        body: dict[str, Any] = {
            "author": author_urn,
            "commentary": commentary,
            "visibility": visibility,
            "distribution": {
                "feedDistribution": feed_distribution,
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": lifecycle_state,
            "isReshareDisabledByAuthor": False,
        }
        if media is not None:
            body["content"] = (
                {"multiImage": {"images": media}} if len(media) > 1 else {"media": media[0]}
            )
        return self._client.post("/rest/posts", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_post(self, post_urn: str) -> dict[str, Any]:
        """Fetch one post by URN (e.g. ``urn:li:share:1234``).

        Returns the raw LinkedIn post resource. Use after
        ``list_posts_for_author(include_ids=True)`` when you need the full
        body of one specific post.
        """
        if not post_urn:
            raise ValueError("post_urn must be a non-empty string")
        return self._client.get(f"/rest/posts/{quote(post_urn, safe='')}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_post(self, post: str | dict[str, Any]) -> dict[str, Any]:
        """Permanently delete a LinkedIn post.

        Accepts a raw URN string OR a post dict from
        ``list_posts_for_author`` (looks up ``post_urn`` / ``urn`` /
        ``id``). Destructive and not reversible — confirm with the user.
        """
        post_urn = self._select_post_urn(post)
        response = self._client.delete(f"/rest/posts/{quote(post_urn, safe='')}")
        return {"urn": post_urn, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_posts_for_author(
        self,
        *,
        author_urn: str,
        count: int = 10,
        start: int = 0,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List posts authored by a member or organization.

        Best first tool for LinkedIn author triage. Default returns compact
        summaries: ``post_ref`` (stable ``post_1``, ``post_2``, ...),
        ``author`` (URN), ``commentary``, ``posted_at``, ``visibility``,
        ``lifecycle_state``. Raw post URNs are omitted unless
        ``include_ids=True``. Set ``include_metadata=False`` to receive the
        raw REST response.
        """
        if not author_urn:
            raise ValueError("author_urn must be a non-empty string")
        payload: dict[str, Any] = self._client.get(
            "/rest/posts",
            params={
                "q": "author",
                "author": author_urn,
                "count": count,
                "start": start,
            },
            headers={"X-RestLi-Method": "FINDER"},
        ).json()
        if not include_metadata:
            return payload
        elements: list[Any] = payload.get("elements", [])
        summaries: list[dict[str, Any]] = []
        for index, post in enumerate(elements, start=1):
            if not isinstance(post, dict):
                continue
            post_dict = cast(dict[str, Any], post)
            summaries.append(self._post_summary(post_dict, index=index, include_ids=include_ids))
        return {
            "posts": summaries,
            "paging": payload.get("paging"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_comment(
        self,
        *,
        post_urn: str,
        actor_urn: str,
        message: str,
    ) -> dict[str, Any]:
        """Comment on a post.

        Returns the new comment resource (``id``, ``actor``, ``message``).
        ``post_urn`` is the URN of the post being commented on;
        ``actor_urn`` is who is commenting.
        """
        if not post_urn or not actor_urn or not message:
            raise ValueError("post_urn, actor_urn, and message must be non-empty")
        return self._client.post(
            f"/rest/socialActions/{quote(post_urn, safe='')}/comments",
            json={
                "actor": actor_urn,
                "object": post_urn,
                "message": {"text": message},
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_comments(
        self,
        post_urn: str,
        *,
        count: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List comments on a post.

        Default returns compact summaries (``comment_ref``, ``actor``,
        ``text``, ``posted_at``). Set ``include_ids=True`` to expose raw
        comment IDs and ``include_metadata=False`` for the raw REST
        response.
        """
        if not post_urn:
            raise ValueError("post_urn must be a non-empty string")
        payload: dict[str, Any] = self._client.get(
            f"/rest/socialActions/{quote(post_urn, safe='')}/comments",
            params={"count": count},
        ).json()
        if not include_metadata:
            return payload
        elements: list[Any] = payload.get("elements", [])
        summaries: list[dict[str, Any]] = []
        for index, comment in enumerate(elements, start=1):
            if not isinstance(comment, dict):
                continue
            comment_dict = cast(dict[str, Any], comment)
            summaries.append(
                self._comment_summary(comment_dict, index=index, include_ids=include_ids)
            )
        return {
            "comments": summaries,
            "paging": payload.get("paging"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_organization(self, organization_id: str) -> dict[str, Any]:
        """Return an organization by numeric ID.

        Returns the raw LinkedIn organization resource (name, description,
        industry, vanity name, etc.).
        """
        if not organization_id:
            raise ValueError("organization_id must be a non-empty string")
        return self._client.get(
            f"/rest/organizations/{organization_id}",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_organization_acls(self) -> dict[str, Any]:
        """List organizations the authenticated user can administer.

        Returns the raw ``organizationAcls`` response — each element has
        an ``organization`` URN and ``role`` (e.g. ``ADMINISTRATOR``).
        """
        return self._client.get(
            "/rest/organizationAcls",
            params={"q": "roleAssignee"},
        ).json()
