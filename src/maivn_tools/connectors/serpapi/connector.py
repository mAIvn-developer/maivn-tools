"""SerpAPI connector (Google + many other search engines)."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

_MAX_SEARCH_RESULTS = 10


# MARK: ToolSet


@toolset(prefix="serpapi")
class SerpAPIToolSet:
    """A connector for SerpAPI."""

    metadata = ProviderMetadata(
        name="serpapi",
        display_name="SerpAPI",
        version="0.1.0",
        description="Scrape search-engine results pages (Google, Bing, etc.).",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.SEARCH}),
        documentation_url="https://serpapi.com/search-api",
        homepage_url="https://serpapi.com/",
        tags=("search",),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://serpapi.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, query_param="api_key"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search(
        self,
        q: str,
        *,
        engine: str = "google",
        location: str | None = None,
        hl: str | None = None,
        gl: str | None = None,
        num: int = 10,
        start: int | None = None,
    ) -> dict[str, Any]:
        """Run a search-engine results scrape.

        Best first tool for SERP-style research. Returns the raw SerpAPI
        response with ``organic_results[*]`` containing ``title``,
        ``link``, and ``snippet`` — all safe to show in final answers.
        ``num`` (result count) is capped at 10. Use ``engine`` to choose
        the source (``google``, ``bing``, ``duckduckgo``, etc.).
        """
        if not q:
            raise ValueError("q must be a non-empty string")
        if num < 1:
            raise ValueError("num must be positive")
        capped_num = min(num, _MAX_SEARCH_RESULTS)
        params: dict[str, Any] = {"q": q, "engine": engine, "num": capped_num}
        if location is not None:
            params["location"] = location
        if hl is not None:
            params["hl"] = hl
        if gl is not None:
            params["gl"] = gl
        if start is not None:
            params["start"] = start
        return cast("dict[str, Any]", self._client.get("/search", params=params).json())

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def location_search(self, query: str) -> dict[str, Any]:
        """Look up canonical SerpAPI locations.

        Returns a list of location records suitable for passing as the
        ``location`` argument to :meth:`search` (Google requires this
        format).
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        return cast(
            "dict[str, Any]",
            self._client.get("/locations.json", params={"q": query}).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_account(self) -> dict[str, Any]:
        """Return account / plan info.

        Returns ``{"account_email": ..., "plan_id": ...,
        "searches_per_month": ..., "this_month_usage": ...}`` — useful for
        quota checks.
        """
        return cast("dict[str, Any]", self._client.get("/account.json").json())
