"""AWS Bedrock + Bedrock Runtime connector.

AWS calls require SigV4 signing. This connector takes an
:class:`AuthStrategy` so callers plug in their own signer.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.base import AuthStrategy, NoAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

_DEFAULT_LIST_LIMIT = 25


# MARK: ToolSet


@toolset(prefix="bedrock")
class BedrockToolSet:
    """A connector for AWS Bedrock + Bedrock Runtime."""

    metadata = ProviderMetadata(
        name="bedrock",
        display_name="AWS Bedrock",
        version="0.1.0",
        description="Models, model invocation, knowledge bases, agents, guardrails.",
        auth_modes=(AuthMode.CUSTOM,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.aws.amazon.com/bedrock/",
        homepage_url="https://aws.amazon.com/bedrock/",
        tags=("ai", "llm", "aws"),
    )

    def __init__(
        self,
        *,
        region: str,
        auth: AuthStrategy | None = None,
        runtime_url: str | None = None,
        control_url: str | None = None,
        agent_url: str | None = None,
        agent_runtime_url: str | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not region:
            raise ValueError("region is required")
        self.connection = connection
        rt = runtime_url or f"https://bedrock-runtime.{region}.amazonaws.com"
        ctl = control_url or f"https://bedrock.{region}.amazonaws.com"
        agent = agent_url or f"https://bedrock-agent.{region}.amazonaws.com"
        agent_rt = agent_runtime_url or f"https://bedrock-agent-runtime.{region}.amazonaws.com"
        self._runtime = HttpClient(
            base_url=rt.rstrip("/"),
            auth=auth or NoAuth(),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )
        self._control = HttpClient(
            base_url=ctl.rstrip("/"),
            auth=auth or NoAuth(),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )
        self._agent = HttpClient(
            base_url=agent.rstrip("/"),
            auth=auth or NoAuth(),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )
        self._agent_runtime = HttpClient(
            base_url=agent_rt.rstrip("/"),
            auth=auth or NoAuth(),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def runtime_client(self) -> HttpClient:
        return self._runtime

    @property
    def control_client(self) -> HttpClient:
        return self._control

    @property
    def agent_client(self) -> HttpClient:
        return self._agent

    @property
    def agent_runtime_client(self) -> HttpClient:
        return self._agent_runtime

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_foundation_models(
        self,
        *,
        by_provider: str | None = None,
        by_output_modality: str | None = None,
        max_results: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List foundation models available in Bedrock.

        Best first tool for model discovery. Returns compact summaries with
        a stable ``model_ref`` (``model_1``, ``model_2``, ...), provider,
        model name, and input/output modalities. The Bedrock
        ``modelId`` is included as ``model_name`` because callers need it
        for :meth:`converse` / :meth:`invoke_model`. Set
        ``include_ids=True`` for the raw ``modelArn``. Default limit: 25.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        params: dict[str, Any] = {}
        if by_provider is not None:
            params["byProvider"] = by_provider
        if by_output_modality is not None:
            params["byOutputModality"] = by_output_modality
        payload: dict[str, Any] = cast(
            "dict[str, Any]",
            self._control.get(
                "/foundation-models",
                params=params or None,
            ).json(),
        )
        raw_models: object = payload.get("modelSummaries", [])
        models: list[Any] = cast("list[Any]", raw_models) if isinstance(raw_models, list) else []
        summaries: list[dict[str, Any]] = []
        for index, model in enumerate(models[:max_results], start=1):
            if not isinstance(model, dict):
                continue
            model_dict = cast("dict[str, Any]", model)
            summary: dict[str, Any] = {
                "model_ref": f"model_{index}",
                "model_name": model_dict.get("modelId", ""),
                "provider": model_dict.get("providerName", ""),
                "input_modalities": model_dict.get("inputModalities", []),
                "output_modalities": model_dict.get("outputModalities", []),
                "model_lifecycle": model_dict.get("modelLifecycle", {}),
            }
            if include_ids:
                summary["model_arn"] = model_dict.get("modelArn", "")
            summaries.append(summary)
        return {"models": summaries, "total": len(models)}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def converse(
        self,
        *,
        model_id: str,
        messages: list[dict[str, Any]],
        system: list[dict[str, Any]] | None = None,
        inference_config: dict[str, Any] | None = None,
        tool_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the Converse API on a foundation model.

        Returns the raw Converse response containing ``output.message`` with
        the assistant turn. ``model_id`` is the Bedrock ``modelId`` from
        :meth:`list_foundation_models` (e.g.
        ``"anthropic.claude-3-5-sonnet-20240620-v1:0"``).
        """
        if not model_id or not messages:
            raise ValueError("model_id and messages must be non-empty")
        body: dict[str, Any] = {"messages": messages}
        if system is not None:
            body["system"] = system
        if inference_config is not None:
            body["inferenceConfig"] = inference_config
        if tool_config is not None:
            body["toolConfig"] = tool_config
        return cast(
            "dict[str, Any]",
            self._runtime.post(
                f"/model/{model_id}/converse",
                json=body,
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def invoke_model(
        self,
        *,
        model_id: str,
        body: dict[str, Any],
        accept: str = "application/json",
    ) -> dict[str, Any]:
        """Invoke a model with the provider-native payload.

        Returns ``{"status": int, "body": <decoded JSON or text>}``. Prefer
        :meth:`converse` for portable chat behavior; use this when the
        provider needs its native format.
        """
        if not model_id:
            raise ValueError("model_id must be a non-empty string")
        response = self._runtime.post(
            f"/model/{model_id}/invoke",
            json=body,
            headers={"Accept": accept},
        )
        try:
            payload: Any = response.json()
        except ValueError:
            payload = response.text()
        return {"status": response.status, "body": payload}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_knowledge_bases(
        self,
        *,
        max_results: int = 10,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List knowledge bases.

        Returns compact summaries with a stable ``kb_ref`` (``kb_1``,
        ``kb_2``, ...), name, description, and status. The raw
        ``knowledgeBaseId`` is included as ``knowledge_base_id`` because
        callers need it for :meth:`retrieve`. Set ``include_ids=True`` for
        the full raw ARN. Default limit: 10.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        payload: dict[str, Any] = cast(
            "dict[str, Any]",
            self._agent.post(
                "/knowledgebases/",
                json={"maxResults": max_results},
            ).json(),
        )
        raw_kbs: object = payload.get("knowledgeBaseSummaries", [])
        kbs: list[Any] = cast("list[Any]", raw_kbs) if isinstance(raw_kbs, list) else []
        summaries: list[dict[str, Any]] = []
        for index, kb in enumerate(kbs, start=1):
            if not isinstance(kb, dict):
                continue
            kb_dict = cast("dict[str, Any]", kb)
            summary: dict[str, Any] = {
                "kb_ref": f"kb_{index}",
                "knowledge_base_id": kb_dict.get("knowledgeBaseId", ""),
                "name": kb_dict.get("name", ""),
                "description": kb_dict.get("description", ""),
                "status": kb_dict.get("status", ""),
                "updated_at": kb_dict.get("updatedAt"),
            }
            if include_ids:
                summary["knowledge_base_arn"] = kb_dict.get("knowledgeBaseArn", "")
            summaries.append(summary)
        return {
            "knowledge_bases": summaries,
            "nextToken": payload.get("nextToken"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def retrieve(
        self,
        *,
        knowledge_base_id: str,
        query: dict[str, Any],
        number_of_results: int = 5,
    ) -> dict[str, Any]:
        """Retrieve from a knowledge base (Bedrock Agent runtime).

        Returns ``{"retrievalResults": [{"content": {"text": ...},
        "location": {...}, "score": ...}, ...]}``. ``query`` is typically
        ``{"text": "your question"}``.
        """
        if not knowledge_base_id:
            raise ValueError("knowledge_base_id must be a non-empty string")
        return cast(
            "dict[str, Any]",
            self._agent_runtime.post(
                f"/knowledgebases/{knowledge_base_id}/retrieve",
                json={
                    "retrievalQuery": query,
                    "retrievalConfiguration": {
                        "vectorSearchConfiguration": {"numberOfResults": number_of_results}
                    },
                },
            ).json(),
        )
