"""Google Gemini API v1beta connector."""

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

_DEFAULT_LIST_LIMIT = 25


# MARK: ToolSet


@toolset(prefix="gemini")
class GeminiToolSet:
    """A connector for the Google Gemini Generative Language API v1beta."""

    metadata = ProviderMetadata(
        name="gemini",
        display_name="Google Gemini",
        version="0.1.0",
        description="Generate content, embeddings, count tokens, list models.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://ai.google.dev/api/rest",
        homepage_url="https://ai.google.dev/",
        tags=("ai", "llm", "google-cloud"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://generativelanguage.googleapis.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="x-goog-api-key"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def generate_content(
        self,
        *,
        model: str,
        contents: list[dict[str, Any]],
        system_instruction: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        generation_config: dict[str, Any] | None = None,
        safety_settings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run ``generateContent`` on a Gemini model.

        Returns the raw Gemini response. ``model`` is the full resource
        name (e.g. ``"models/gemini-1.5-pro"``); discover available models
        via :meth:`list_models`.
        """
        if not model or not contents:
            raise ValueError("model and contents must be non-empty")
        body: dict[str, Any] = {"contents": contents}
        if system_instruction is not None:
            body["systemInstruction"] = system_instruction
        if tools is not None:
            body["tools"] = tools
        if generation_config is not None:
            body["generationConfig"] = generation_config
        if safety_settings is not None:
            body["safetySettings"] = safety_settings
        result: dict[str, Any] = self._client.post(
            f"/v1beta/{model}:generateContent",
            json=body,
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def count_tokens(
        self,
        *,
        model: str,
        contents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Count tokens for a prospective ``generateContent`` request.

        Returns ``{"totalTokens": int}``.
        """
        if not model or not contents:
            raise ValueError("model and contents must be non-empty")
        result: dict[str, Any] = self._client.post(
            f"/v1beta/{model}:countTokens",
            json={"contents": contents},
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def embed_content(
        self,
        *,
        model: str,
        content: dict[str, Any],
        task_type: str | None = None,
        embed_content_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate an embedding.

        Returns ``{"embedding": {"values": [...]}}``. Use an embedding model
        (e.g. ``"models/text-embedding-004"``).

        Prefer ``embed_content_config`` (the current ``embedContentConfig``
        object carrying ``taskType``, ``title``, ``outputDimensionality``).
        The top-level ``task_type`` argument is accepted for backward
        compatibility but maps to the deprecated top-level ``taskType`` field.
        """
        if not model or not content:
            raise ValueError("model and content must be non-empty")
        body: dict[str, Any] = {"content": content}
        if embed_content_config is not None:
            body["embedContentConfig"] = embed_content_config
        if task_type is not None:
            body["taskType"] = task_type
        result: dict[str, Any] = self._client.post(
            f"/v1beta/{model}:embedContent",
            json=body,
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_models(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List available Gemini models.

        Best first tool for model discovery. Returns compact summaries with
        a stable ``model_ref`` (``model_1``, ``model_2``, ...), display
        name, supported methods, and token limits. The Gemini model name
        (``models/...``) is included as ``model_name`` because callers need
        it for :meth:`generate_content`. Set ``include_ids=True`` for the
        full raw ``name`` field. Default limit: 25.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        payload: object = self._client.get(
            "/v1beta/models",
            params={"pageSize": max_results},
        ).json()
        payload_dict: dict[str, Any] = (
            cast("dict[str, Any]", payload) if isinstance(payload, dict) else {}
        )
        raw_models: object = payload_dict.get("models", [])
        models: list[object] = (
            cast("list[object]", raw_models) if isinstance(raw_models, list) else []
        )
        summaries: list[dict[str, Any]] = []
        for index, model in enumerate(models, start=1):
            if not isinstance(model, dict):
                continue
            model_dict: dict[str, Any] = cast("dict[str, Any]", model)
            summary: dict[str, Any] = {
                "model_ref": f"model_{index}",
                "model_name": model_dict.get("name", ""),
                "display_name": model_dict.get("displayName", ""),
                "supported_methods": model_dict.get("supportedGenerationMethods", []),
                "input_token_limit": model_dict.get("inputTokenLimit"),
                "output_token_limit": model_dict.get("outputTokenLimit"),
            }
            if include_ids:
                summary["name"] = model_dict.get("name", "")
            summaries.append(summary)
        return {
            "models": summaries,
            "nextPageToken": payload_dict.get("nextPageToken"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_model(self, model_name: str) -> dict[str, Any]:
        """Return one model by full resource name (``models/...``).

        Returns the raw model resource (``name``, ``displayName``,
        ``supportedGenerationMethods``, token limits).
        """
        if not model_name:
            raise ValueError("model_name must be a non-empty string")
        result: dict[str, Any] = self._client.get(f"/v1beta/{model_name}").json()
        return result
