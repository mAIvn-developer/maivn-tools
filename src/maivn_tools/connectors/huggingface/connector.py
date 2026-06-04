"""Hugging Face Hub + Inference API connector."""

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

# Inference Providers router host. The legacy serverless host
# ``api-inference.huggingface.co`` is no longer supported; serverless
# inference now routes through ``router.huggingface.co``.
_INFERENCE_URL = "https://router.huggingface.co"
# HF Inference provider segment required ahead of the model path under the
# router (legacy layout was the bare ``/models/{model}``).
_HF_INFERENCE_PROVIDER = "hf-inference"


# MARK: Tool set


@toolset(prefix="hf")
class HuggingFaceToolSet:
    """A connector for Hugging Face Hub and Inference."""

    metadata = ProviderMetadata(
        name="huggingface",
        display_name="Hugging Face",
        version="0.1.0",
        description="Models, datasets, spaces, and serverless inference.",
        auth_modes=(AuthMode.BEARER, AuthMode.API_KEY),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://huggingface.co/docs/api-inference/",
        homepage_url="https://huggingface.co/",
        tags=("ai", "ml"),
    )

    def __init__(
        self,
        *,
        token: str,
        hub_url: str = "https://huggingface.co",
        inference_url: str = _INFERENCE_URL,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not token:
            raise ValueError("token is required")
        self.connection = connection
        self._hub = HttpClient(
            base_url=hub_url.rstrip("/"),
            auth=BearerTokenAuth(token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )
        self._inference = HttpClient(
            base_url=inference_url.rstrip("/"),
            auth=BearerTokenAuth(token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def hub_client(self) -> HttpClient:
        return self._hub

    @property
    def inference_client(self) -> HttpClient:
        return self._inference

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_models(
        self,
        *,
        search: str | None = None,
        author: str | None = None,
        filter: str | None = None,
        sort: str = "downloads",
        max_results: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List models on the Hugging Face Hub.

        Best first tool for model discovery. Returns compact summaries with
        a stable ``model_ref`` (``model_1``, ``model_2``, ...), pipeline
        tag, downloads, likes, and last-modified time. The model ``id``
        (``"author/name"``) is included as ``model_name`` because callers
        need it for :meth:`run_inference`. Set ``include_ids=True`` for the
        raw ``id`` field. Default limit: 25.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        params: dict[str, Any] = {"sort": sort, "limit": max_results}
        if search is not None:
            params["search"] = search
        if author is not None:
            params["author"] = author
        if filter is not None:
            params["filter"] = filter
        payload: Any = self._hub.get("/api/models", params=params).json()
        models: list[Any] = cast(list[Any], payload) if isinstance(payload, list) else []
        summaries: list[dict[str, Any]] = []
        for index, model in enumerate(models[:max_results], start=1):
            if not isinstance(model, dict):
                continue
            model_dict = cast(dict[str, Any], model)
            summary: dict[str, Any] = {
                "model_ref": f"model_{index}",
                "model_name": model_dict.get("id", ""),
                "pipeline_tag": model_dict.get("pipeline_tag", ""),
                "downloads": model_dict.get("downloads"),
                "likes": model_dict.get("likes"),
                "last_modified": model_dict.get("lastModified"),
            }
            if include_ids:
                summary["id"] = model_dict.get("id", "")
            summaries.append(summary)
        return {"models": summaries, "total": len(models)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_model(self, model_id: str) -> dict[str, Any]:
        """Return model info from the Hub.

        Returns the raw model resource (``id``, ``pipeline_tag``, ``tags``,
        ``downloads``, ``likes``, ``cardData``).
        """
        if not model_id:
            raise ValueError("model_id must be a non-empty string")
        return self._hub.get(f"/api/models/{model_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_datasets(
        self,
        *,
        search: str | None = None,
        author: str | None = None,
        max_results: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List datasets on the Hugging Face Hub.

        Returns compact summaries with a stable ``dataset_ref``
        (``dataset_1``, ``dataset_2``, ...), tags, downloads, and last
        modification. The dataset ``id`` (``"author/name"``) is included as
        ``dataset_name`` because it is what callers need to load the
        dataset. Set ``include_ids=True`` for the raw ``id`` field.
        Default limit: 25.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        params: dict[str, Any] = {"limit": max_results}
        if search is not None:
            params["search"] = search
        if author is not None:
            params["author"] = author
        payload: Any = self._hub.get("/api/datasets", params=params).json()
        datasets: list[Any] = cast(list[Any], payload) if isinstance(payload, list) else []
        summaries: list[dict[str, Any]] = []
        for index, dataset in enumerate(datasets[:max_results], start=1):
            if not isinstance(dataset, dict):
                continue
            dataset_dict = cast(dict[str, Any], dataset)
            summary: dict[str, Any] = {
                "dataset_ref": f"dataset_{index}",
                "dataset_name": dataset_dict.get("id", ""),
                "tags": dataset_dict.get("tags", []),
                "downloads": dataset_dict.get("downloads"),
                "last_modified": dataset_dict.get("lastModified"),
            }
            if include_ids:
                summary["id"] = dataset_dict.get("id", "")
            summaries.append(summary)
        return {"datasets": summaries, "total": len(datasets)}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def run_inference(
        self,
        *,
        model: str,
        payload: dict[str, Any],
        wait_for_model: bool = True,
    ) -> dict[str, Any]:
        """Call the serverless inference endpoint.

        Routes through the Inference Providers router using the HF Inference
        provider path ``/hf-inference/models/{model}``. Returns ``{"status":
        int, "body": <decoded JSON or text>}``. The body shape depends on the
        model's pipeline (text-generation returns text, classification returns
        labels, etc.). ``model`` is the ``"author/name"`` ID from
        :meth:`list_models`.
        """
        if not model:
            raise ValueError("model must be a non-empty string")
        headers: dict[str, str] = {}
        if wait_for_model:
            headers["x-wait-for-model"] = "true"
        response = self._inference.post(
            f"/{_HF_INFERENCE_PROVIDER}/models/{model}",
            json=payload,
            headers=headers or None,
        )
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text()
        return {"status": response.status, "body": body}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def whoami(self) -> dict[str, Any]:
        """Return account info for the token.

        Returns ``{"name": ..., "fullname": ..., "email": ..., "orgs":
        [...]}``. Use this once at startup to confirm the token is valid.
        """
        return self._hub.get("/api/whoami-v2").json()
