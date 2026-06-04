"""Azure OpenAI Service connector."""
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
_API_VERSION = "2024-10-21"


# MARK: ToolSet


@toolset(prefix="azure_openai")
class AzureOpenAIToolSet:
    """A connector for Azure OpenAI Service.

    Args:
        endpoint: Resource endpoint, e.g. ``https://my-resource.openai.azure.com``.
        api_key: Resource API key (sent via ``api-key`` header).
        api_version: Azure-OpenAI API version (e.g. ``"2024-10-21"``).
    """

    metadata = ProviderMetadata(
        name="azure_openai",
        display_name="Azure OpenAI",
        version="0.1.0",
        description="Chat completions, embeddings, and image generation via Azure deployments.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://learn.microsoft.com/en-us/azure/ai-services/openai/reference",
        homepage_url="https://azure.microsoft.com/en-us/products/ai-services/openai-service",
        tags=("ai", "llm", "microsoft", "azure"),
    )

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        api_version: str = _API_VERSION,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not endpoint or not api_key:
            raise ValueError("endpoint and api_key are required")
        self.connection = connection
        self._api_version = api_version
        self._client = HttpClient(
            base_url=endpoint.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="api-key"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def chat_completion(
        self,
        *,
        deployment: str,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        response_format: dict[str, Any] | None = None,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Chat completion against a deployment.

        Returns the raw chat-completion response. ``deployment`` is the
        Azure deployment name (not the underlying model name) — discover it
        via :meth:`list_models`.
        """
        if not deployment or not messages:
            raise ValueError("deployment and messages must be non-empty")
        body: dict[str, Any] = {"messages": messages}
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
        if seed is not None:
            body["seed"] = seed
        return self._client.post(
            f"/openai/deployments/{deployment}/chat/completions",
            params={"api-version": self._api_version},
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def embeddings(
        self,
        *,
        deployment: str,
        input: str | list[str],
        dimensions: int | None = None,
    ) -> dict[str, Any]:
        """Generate embeddings.

        Returns ``{"data": [{"embedding": [...], "index": n}, ...]}``.
        """
        if not deployment:
            raise ValueError("deployment must be a non-empty string")
        body: dict[str, Any] = {"input": input}
        if dimensions is not None:
            body["dimensions"] = dimensions
        return self._client.post(
            f"/openai/deployments/{deployment}/embeddings",
            params={"api-version": self._api_version},
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def generate_image(
        self,
        *,
        deployment: str,
        prompt: str,
        n: int | None = None,
        size: str | None = None,
        quality: str | None = None,
        style: str | None = None,
        response_format: str | None = None,
    ) -> dict[str, Any]:
        """Generate an image.

        Returns ``{"data": [{"url" or "b64_json": ...}, ...]}``.
        """
        if not deployment or not prompt:
            raise ValueError("deployment and prompt must be non-empty")
        body: dict[str, Any] = {"prompt": prompt}
        if n is not None:
            body["n"] = n
        if size is not None:
            body["size"] = size
        if quality is not None:
            body["quality"] = quality
        if style is not None:
            body["style"] = style
        if response_format is not None:
            body["response_format"] = response_format
        return self._client.post(
            f"/openai/deployments/{deployment}/images/generations",
            params={"api-version": self._api_version},
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_models(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List models available to the resource.

        Best first tool for deployment discovery. Returns compact summaries
        with a stable ``model_ref`` (``model_1``, ``model_2``, ...) plus
        the deployment/model name and capabilities. The raw ``id`` is the
        same as the model name and is included as ``model_name`` because
        callers need it for :meth:`chat_completion`. Set
        ``include_ids=True`` for the raw ``id`` field. Default limit: 25.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        payload: object = self._client.get(
            "/openai/models",
            params={"api-version": self._api_version},
        ).json()
        models: list[object] = (
            cast(list[object], cast(dict[str, Any], payload).get("data", []))
            if isinstance(payload, dict)
            else []
        )
        summaries: list[dict[str, Any]] = []
        for index, model in enumerate(models[:max_results], start=1):
            if not isinstance(model, dict):
                continue
            model = cast(dict[str, Any], model)
            summary: dict[str, Any] = {
                "model_ref": f"model_{index}",
                "model_name": model.get("id", ""),
                "capabilities": model.get("capabilities", {}),
                "lifecycle_status": model.get("lifecycle_status", ""),
            }
            if include_ids:
                summary["id"] = model.get("id", "")
            summaries.append(summary)
        return {"models": summaries, "total": len(models)}
