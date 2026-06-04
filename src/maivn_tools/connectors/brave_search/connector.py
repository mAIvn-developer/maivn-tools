"""Brave Search API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

_MAX_WEB_RESULTS = 20
_MAX_NEWS_RESULTS = 50
_MAX_IMAGE_RESULTS = 200
_MAX_VIDEO_RESULTS = 50
_MAX_SUGGEST_RESULTS = 10


# MARK: Helpers


def _cap_count(count: int, maximum: int) -> int:
    if count < 1:
        raise ValueError("count must be positive")
    return min(count, maximum)


# MARK: ToolSet


@toolset(prefix="brave")
class BraveSearchToolSet:
    """A connector for the Brave Search API."""

    metadata = ProviderMetadata(
        name="brave_search",
        display_name="Brave Search",
        version="0.1.0",
        description="Web, news, image, and video search via the Brave Search API.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.SEARCH}),
        documentation_url="https://api.search.brave.com/app/documentation",
        homepage_url="https://brave.com/search/api/",
        tags=("search",),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.search.brave.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="X-Subscription-Token"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _search(self, path: str, q: str, params: dict[str, Any]) -> dict[str, Any]:
        if not q:
            raise ValueError("q must be a non-empty string")
        merged = dict(params)
        merged["q"] = q
        payload: dict[str, Any] = self._client.get(path, params=merged).json()
        return payload

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def web_search(
        self,
        q: str,
        *,
        count: int = 10,
        offset: int = 0,
        country: str | None = None,
        search_lang: str | None = None,
        freshness: str | None = None,
    ) -> dict[str, Any]:
        """Run a web search.

        Best first tool for general web research. Returns the raw Brave
        response — the ``web.results[*]`` array has ``title``, ``url``,
        and ``description`` fields safe to show in final answers.
        ``count`` is capped at 20.
        """
        capped_count = _cap_count(count, _MAX_WEB_RESULTS)
        params: dict[str, Any] = {"count": capped_count, "offset": offset}
        if country is not None:
            params["country"] = country
        if search_lang is not None:
            params["search_lang"] = search_lang
        if freshness is not None:
            params["freshness"] = freshness
        return self._search("/res/v1/web/search", q, params)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def news_search(
        self,
        q: str,
        *,
        count: int = 10,
        offset: int = 0,
        freshness: str | None = None,
    ) -> dict[str, Any]:
        """Run a news search.

        Returns the raw Brave news response — ``results[*]`` has
        ``title``, ``url``, ``description``, and ``age``. ``count`` is
        capped at 50. Use ``freshness="pd"`` for past day,
        ``"pw"`` for past week.
        """
        capped_count = _cap_count(count, _MAX_NEWS_RESULTS)
        params: dict[str, Any] = {"count": capped_count, "offset": offset}
        if freshness is not None:
            params["freshness"] = freshness
        return self._search("/res/v1/news/search", q, params)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def image_search(
        self,
        q: str,
        *,
        count: int = 10,
        safesearch: str = "strict",
        country: str | None = None,
        search_lang: str | None = None,
    ) -> dict[str, Any]:
        """Run an image search.

        Returns the raw Brave images response with ``thumbnail`` and
        ``source`` URLs in the top-level ``results`` array. ``count``
        capped at 200; ``safesearch`` defaults to ``"strict"``.
        """
        capped_count = _cap_count(count, _MAX_IMAGE_RESULTS)
        params: dict[str, Any] = {"count": capped_count, "safesearch": safesearch}
        if country is not None:
            params["country"] = country
        if search_lang is not None:
            params["search_lang"] = search_lang
        return self._search("/res/v1/images/search", q, params)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def video_search(
        self,
        q: str,
        *,
        count: int = 10,
        offset: int = 0,
        country: str | None = None,
        search_lang: str | None = None,
        freshness: str | None = None,
    ) -> dict[str, Any]:
        """Run a video search.

        Returns the raw Brave videos response. Each video appears in the
        top-level ``results`` array with ``title``, ``url``, and
        ``description``; ``video.duration`` is present when known.
        ``count`` capped at 50.
        """
        capped_count = _cap_count(count, _MAX_VIDEO_RESULTS)
        params: dict[str, Any] = {"count": capped_count, "offset": offset}
        if country is not None:
            params["country"] = country
        if search_lang is not None:
            params["search_lang"] = search_lang
        if freshness is not None:
            params["freshness"] = freshness
        return self._search("/res/v1/videos/search", q, params)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def suggest(self, q: str, *, count: int = 5) -> dict[str, Any]:
        """Return query suggestions.

        Returns ``{"results": [{"query": ...}, ...]}`` — quick
        autocomplete-style suggestions. ``count`` capped at 10.
        """
        capped_count = _cap_count(count, _MAX_SUGGEST_RESULTS)
        return self._search("/res/v1/suggest/search", q, {"count": capped_count})
