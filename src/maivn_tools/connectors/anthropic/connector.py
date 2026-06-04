# pyright: strict
"""Anthropic API connector (Messages, Models, Batches, Files)."""

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

_DEFAULT_LIST_LIMIT = 20


# MARK: Helpers


def _resolve_id(value: Any, *id_keys: str) -> str:
    """Extract a string identifier from a raw id, dict, or list of dicts."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        mapping = cast("dict[str, Any]", value)
        data: object = mapping.get("data")
        if isinstance(data, list) and data:
            first: object = cast("list[object]", data)[0]
            return _resolve_id(first, *id_keys)
        for key in id_keys:
            candidate: object = mapping.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        raise ValueError(f"could not resolve id from dict (expected one of: {', '.join(id_keys)})")
    if isinstance(value, list | tuple):
        items = cast("list[object] | tuple[object, ...]", value)
        for item in items:
            try:
                return _resolve_id(item, *id_keys)
            except ValueError:
                continue
    raise ValueError("identifier must be a non-empty string, dict, or list")


# MARK: ToolSet


@toolset(prefix="anthropic")
class AnthropicToolSet:
    """A connector for the Anthropic REST API."""

    metadata = ProviderMetadata(
        name="anthropic",
        display_name="Anthropic",
        version="0.1.0",
        description="Messages, Models, Batches, Files for Claude models.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset(
            {ProviderCapability.READ, ProviderCapability.WRITE, ProviderCapability.STREAMING}
        ),
        documentation_url="https://docs.anthropic.com/en/api/",
        homepage_url="https://www.anthropic.com/",
        tags=("ai", "llm"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        anthropic_version: str = "2023-06-01",
        base_url: str = "https://api.anthropic.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="x-api-key"),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "anthropic-version": anthropic_version,
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_message(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        system: str | list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        stream: bool | None = None,
    ) -> dict[str, Any]:
        """Create a message (chat completion).

        Returns the raw Claude message response including ``content`` blocks
        (text or tool-use). ``model`` is a model name such as
        ``"claude-3-5-sonnet-latest"``; discover available ones via
        :meth:`list_models`.
        """
        if not model or not messages or max_tokens < 1:
            raise ValueError("model, messages, and max_tokens > 0 are required")
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if system is not None:
            body["system"] = system
        if temperature is not None:
            body["temperature"] = temperature
        if tools is not None:
            body["tools"] = tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        if stop_sequences is not None:
            body["stop_sequences"] = stop_sequences
        if metadata is not None:
            body["metadata"] = metadata
        if stream is not None:
            body["stream"] = stream
        return self._client.post("/v1/messages", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def count_tokens(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        system: str | list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Count input tokens for a prospective request.

        Returns ``{"input_tokens": int}``. Useful for budget planning before
        calling :meth:`create_message`.
        """
        if not model or not messages:
            raise ValueError("model and messages must be non-empty")
        body: dict[str, Any] = {"model": model, "messages": messages}
        if system is not None:
            body["system"] = system
        if tools is not None:
            body["tools"] = tools
        return self._client.post(
            "/v1/messages/count_tokens",
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_models(
        self,
        *,
        limit: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List available Claude models.

        Best first tool for model discovery. Returns compact summaries with
        a stable ``model_ref`` (``model_1``, ``model_2``, ...), display
        name, and creation time. The Anthropic model ID is also the model
        name used in :meth:`create_message`, so it is included as
        ``model_name``. Set ``include_ids=True`` for the raw ``id`` field.
        Default limit: 20.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        payload: dict[str, Any] = self._client.get("/v1/models", params={"limit": limit}).json()
        raw_models: object = payload.get("data", [])
        models: list[object] = (
            cast("list[object]", raw_models) if isinstance(raw_models, list) else []
        )
        summaries: list[dict[str, Any]] = []
        for index, model in enumerate(models, start=1):
            if not isinstance(model, dict):
                continue
            entry = cast("dict[str, Any]", model)
            summary: dict[str, Any] = {
                "model_ref": f"model_{index}",
                "model_name": entry.get("id", ""),
                "display_name": entry.get("display_name", ""),
                "created_at": entry.get("created_at"),
            }
            if include_ids:
                summary["id"] = entry.get("id", "")
            summaries.append(summary)
        return {"models": summaries, "has_more": payload.get("has_more", False)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_model(self, model_id: str) -> dict[str, Any]:
        """Return one model.

        Returns the raw model resource (``id``, ``display_name``,
        ``created_at``).
        """
        if not model_id:
            raise ValueError("model_id must be a non-empty string")
        return self._client.get(f"/v1/models/{model_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_message_batch(
        self,
        requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create a Message Batches job.

        Returns the new batch resource (``id``, ``processing_status``,
        ``request_counts``). The ``requests`` payload follows the Anthropic
        batch input schema (each entry has ``custom_id`` and ``params``).
        """
        if not requests:
            raise ValueError("requests must be non-empty")
        return self._client.post(
            "/v1/messages/batches",
            json={"requests": requests},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_batch(self, batch_id: Any) -> dict[str, Any]:
        """Return a batch.

        Accepts a raw ``msgbatch_...`` string or a batch dict returned by
        :meth:`create_message_batch`.
        """
        resolved = _resolve_id(batch_id, "batch_id", "id")
        if not resolved:
            raise ValueError("batch_id must be a non-empty string")
        return self._client.get(f"/v1/messages/batches/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def cancel_batch(self, batch_id: Any) -> dict[str, Any]:
        """Cancel a batch. Destructive; confirm with the user first.

        Accepts a raw ``msgbatch_...`` string or a batch dict returned by
        :meth:`create_message_batch` / :meth:`get_batch`.
        """
        resolved = _resolve_id(batch_id, "batch_id", "id")
        if not resolved:
            raise ValueError("batch_id must be a non-empty string")
        return self._client.post(f"/v1/messages/batches/{resolved}/cancel").json()
