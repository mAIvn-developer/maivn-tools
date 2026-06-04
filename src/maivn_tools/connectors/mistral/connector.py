"""Mistral AI La Plateforme connector."""

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

_DEFAULT_LIST_LIMIT = 25


# MARK: ToolSet


@toolset(prefix="mistral")
class MistralToolSet:
    """A connector for Mistral La Plateforme."""

    metadata = ProviderMetadata(
        name="mistral",
        display_name="Mistral AI",
        version="0.1.0",
        description="Chat, embeddings, FIM completions, agents.",
        auth_modes=(AuthMode.BEARER, AuthMode.API_KEY),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.mistral.ai/api/",
        homepage_url="https://mistral.ai/",
        tags=("ai", "llm"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.mistral.ai",
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
    def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        response_format: dict[str, Any] | None = None,
        random_seed: int | None = None,
    ) -> dict[str, Any]:
        """Chat completion.

        Returns the raw chat-completion response with ``choices``.
        Discover available models via :meth:`list_models`.
        """
        if not model or not messages:
            raise ValueError("model and messages must be non-empty")
        body: dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if tools is not None:
            body["tools"] = tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        if response_format is not None:
            body["response_format"] = response_format
        if random_seed is not None:
            body["random_seed"] = random_seed
        return self._client.post("/v1/chat/completions", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def embeddings(
        self,
        *,
        model: str,
        input: list[str] | str,
    ) -> dict[str, Any]:
        """Create embeddings.

        Returns ``{"data": [{"embedding": [...], "index": n}, ...]}``. Use
        an embedding model such as ``"mistral-embed"``.
        """
        if not model:
            raise ValueError("model must be a non-empty string")
        return self._client.post(
            "/v1/embeddings",
            json={"model": model, "input": input},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def fim_completion(
        self,
        *,
        model: str,
        prompt: str,
        suffix: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Fill-in-the-middle completion (codestral models).

        Returns the raw FIM completion response. ``prompt`` is the text
        before the gap and ``suffix`` is the text after — Mistral fills the
        middle.
        """
        if not model or not prompt:
            raise ValueError("model and prompt must be non-empty")
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "suffix": suffix,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        return self._client.post("/v1/fim/completions", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_models(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List available Mistral models.

        Best first tool for model discovery. Returns compact summaries with
        a stable ``model_ref`` (``model_1``, ``model_2``, ...). The
        Mistral model ID is also the model name used by
        :meth:`chat_completion`, so it is included as ``model_name``. Set
        ``include_ids=True`` for the raw ``id`` field. Default limit: 25.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        payload: dict[str, Any] = self._client.get("/v1/models").json()
        raw_models: Any = payload.get("data", [])
        models: list[Any] = cast("list[Any]", raw_models) if isinstance(raw_models, list) else []
        summaries: list[dict[str, Any]] = []
        for index, model in enumerate(models[:max_results], start=1):
            if not isinstance(model, dict):
                continue
            model_dict = cast("dict[str, Any]", model)
            summary: dict[str, Any] = {
                "model_ref": f"model_{index}",
                "model_name": model_dict.get("id", ""),
                "owned_by": model_dict.get("owned_by", ""),
                "created": model_dict.get("created"),
            }
            if include_ids:
                summary["id"] = model_dict.get("id", "")
            summaries.append(summary)
        return {"models": summaries, "total": len(models)}
