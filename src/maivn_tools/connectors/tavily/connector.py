"""Tavily AI search API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

_MAX_SEARCH_RESULTS = 10


# MARK: ToolSet


@toolset(prefix="tavily")
class TavilyToolSet:
    """A connector for the Tavily API (search, extract, crawl)."""

    metadata = ProviderMetadata(
        name="tavily",
        display_name="Tavily",
        version="0.1.0",
        description="AI-optimized web search, extract, and crawl.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.SEARCH}),
        documentation_url="https://docs.tavily.com/",
        homepage_url="https://www.tavily.com/",
        tags=("search", "ai"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.tavily.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._api_key = api_key
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
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

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search(
        self,
        query: str,
        *,
        search_depth: str = "basic",
        topic: str = "general",
        max_results: int = 5,
        include_answer: bool | str = False,
        include_raw_content: bool = False,
        include_images: bool = False,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        days: int | None = None,
        time_range: str | None = None,
    ) -> dict[str, Any]:
        """Run a Tavily web search.

        Best first tool for web research. Returns ``{"results":
        [{"title": ..., "url": ..., "content": ...}, ...], "answer": ...,
        "query": ...}``. The ``title``/``url``/``content`` fields are
        human-facing summaries safe to show in final answers. ``max_results``
        is capped at 10 to keep agent runs fast. Use ``include_answer=True``
        to also get an LLM-generated synthesis of the top hits.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        if search_depth not in {"basic", "advanced"}:
            raise ValueError("search_depth must be 'basic' or 'advanced'")
        if max_results < 1:
            raise ValueError("max_results must be positive")
        capped_max_results = min(max_results, _MAX_SEARCH_RESULTS)
        body: dict[str, Any] = {
            "query": query,
            "search_depth": search_depth,
            "topic": topic,
            "max_results": capped_max_results,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
            "include_images": include_images,
        }
        if include_domains is not None:
            body["include_domains"] = include_domains
        if exclude_domains is not None:
            body["exclude_domains"] = exclude_domains
        if days is not None:
            body["days"] = days
        if time_range is not None:
            body["time_range"] = time_range
        # ``.json()`` is untyped (Any) at the HTTP boundary; narrow via runtime guard.
        result: object = cast("object", self._client.post("/search", json=body).json())
        if isinstance(result, dict) and capped_max_results != max_results:
            narrowed = cast("dict[str, Any]", result)
            narrowed["requestedMaxResults"] = max_results
            narrowed["maxResultsCap"] = _MAX_SEARCH_RESULTS
            return narrowed
        return cast("dict[str, Any]", result)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def extract(
        self,
        urls: list[str],
        *,
        extract_depth: str = "basic",
        include_images: bool = False,
    ) -> dict[str, Any]:
        """Extract clean text content from one or more URLs.

        Returns ``{"results": [{"url": ..., "raw_content": ...}, ...]}``.
        Use after :meth:`search` when an LLM needs the full page text, not
        just snippets.
        """
        if not urls:
            raise ValueError("urls must be non-empty")
        return cast(
            "dict[str, Any]",
            self._client.post(
                "/extract",
                json={
                    "urls": urls,
                    "extract_depth": extract_depth,
                    "include_images": include_images,
                },
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def crawl(
        self,
        url: str,
        *,
        max_depth: int = 1,
        max_breadth: int = 20,
        limit: int = 50,
        instructions: str | None = None,
    ) -> dict[str, Any]:
        """Crawl a domain following internal links.

        Returns ``{"results": [{"url": ..., "raw_content": ...}, ...]}``.
        Use ``instructions`` to scope the crawl (e.g. ``"only docs
        pages"``). ``limit`` caps total pages returned.
        """
        if not url:
            raise ValueError("url must be a non-empty string")
        body: dict[str, Any] = {
            "url": url,
            "max_depth": max_depth,
            "max_breadth": max_breadth,
            "limit": limit,
        }
        if instructions is not None:
            body["instructions"] = instructions
        return cast("dict[str, Any]", self._client.post("/crawl", json=body).json())
