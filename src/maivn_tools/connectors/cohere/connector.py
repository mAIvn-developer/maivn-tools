"""Cohere API v2 connector."""

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

_DEFAULT_LIST_LIMIT = 20


# MARK: ToolSet


@toolset(prefix="cohere")
class CohereToolSet:
    """A connector for the Cohere API."""

    metadata = ProviderMetadata(
        name="cohere",
        display_name="Cohere",
        version="0.1.0",
        description="Chat, embed, rerank, and classify.",
        auth_modes=(AuthMode.BEARER, AuthMode.API_KEY),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.cohere.com/reference/about",
        homepage_url="https://cohere.com/",
        tags=("ai", "llm"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.cohere.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
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

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        stream: bool | None = None,
    ) -> dict[str, Any]:
        """Chat completion.

        Returns the raw Cohere v2 chat response with ``message.content``
        blocks from the assistant. Discover available models via
        :meth:`list_models`.
        """
        if not model or not messages:
            raise ValueError("model and messages must be non-empty")
        body: dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            body["temperature"] = temperature
        if tools is not None:
            body["tools"] = tools
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if stream is not None:
            body["stream"] = stream
        return self._client.post("/v2/chat", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def embed(
        self,
        *,
        texts: list[str],
        model: str,
        input_type: str = "search_document",
        embedding_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Embed text.

        Returns ``{"embeddings": {<type>: [[...], ...]}}``. Use an embed
        model (e.g. ``"embed-english-v3.0"``).
        """
        if not texts or not model:
            raise ValueError("texts and model must be non-empty")
        body: dict[str, Any] = {
            "texts": texts,
            "model": model,
            "input_type": input_type,
        }
        if embedding_types is not None:
            body["embedding_types"] = embedding_types
        return self._client.post("/v2/embed", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def rerank(
        self,
        *,
        model: str,
        query: str,
        documents: list[str] | list[dict[str, Any]],
        top_n: int | None = None,
    ) -> dict[str, Any]:
        """Rerank documents by relevance to a query.

        Returns ``{"results": [{"index": n, "relevance_score": float},
        ...]}`` sorted by score. Use a rerank model (e.g. ``"rerank-v3"``).
        """
        if not model or not query or not documents:
            raise ValueError("model, query, and documents must be non-empty")
        body: dict[str, Any] = {
            "model": model,
            "query": query,
            "documents": documents,
        }
        if top_n is not None:
            body["top_n"] = top_n
        return self._client.post("/v2/rerank", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_models(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List available Cohere models.

        Best first tool for model discovery. Returns compact summaries with
        a stable ``model_ref`` (``model_1``, ``model_2``, ...), endpoints
        the model supports, and context length. The Cohere model ``name``
        is also the value used in :meth:`chat`/:meth:`embed`, so it is
        included as ``model_name``. Set ``include_ids=True`` for the raw
        ``name`` field. Default limit: 20.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        payload: dict[str, Any] = self._client.get(
            "/v1/models",
            params={"page_size": max_results},
        ).json()
        raw_models: object = payload.get("models", [])
        models: list[object] = (
            cast("list[object]", raw_models) if isinstance(raw_models, list) else []
        )
        summaries: list[dict[str, Any]] = []
        for index, model in enumerate(models, start=1):
            if not isinstance(model, dict):
                continue
            model_dict = cast("dict[str, Any]", model)
            summary: dict[str, Any] = {
                "model_ref": f"model_{index}",
                "model_name": model_dict.get("name", ""),
                "endpoints": model_dict.get("endpoints", []),
                "context_length": model_dict.get("context_length"),
            }
            if include_ids:
                summary["name"] = model_dict.get("name", "")
            summaries.append(summary)
        return {
            "models": summaries,
            "next_page_token": payload.get("next_page_token"),
        }
