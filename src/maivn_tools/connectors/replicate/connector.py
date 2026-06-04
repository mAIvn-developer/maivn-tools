"""Replicate API connector."""

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


# MARK: Helpers


def _extract_results(payload: Any) -> list[Any]:
    """Return the ``results`` list from a paginated payload, or ``[]``."""
    if isinstance(payload, dict):
        results = cast(dict[str, Any], payload).get("results", [])
        return cast(list[Any], results)
    return []


def _resolve_id(value: Any, *id_keys: str) -> str:
    """Extract a string identifier from a raw id, dict, or list of dicts."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        mapping = cast(dict[str, Any], value)
        results = mapping.get("results")
        if isinstance(results, list) and results:
            items = cast(list[Any], results)
            return _resolve_id(items[0], *id_keys)
        for key in id_keys:
            candidate = mapping.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        raise ValueError(f"could not resolve id from dict (expected one of: {', '.join(id_keys)})")
    if isinstance(value, list | tuple):
        for item in cast("list[Any] | tuple[Any, ...]", value):
            try:
                return _resolve_id(item, *id_keys)
            except ValueError:
                continue
    raise ValueError("identifier must be a non-empty string, dict, or list")


# MARK: Tool set


@toolset(prefix="replicate")
class ReplicateToolSet:
    """A connector for the Replicate REST API."""

    metadata = ProviderMetadata(
        name="replicate",
        display_name="Replicate",
        version="0.1.0",
        description="Models, predictions, deployments, collections.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://replicate.com/docs/reference/http",
        homepage_url="https://replicate.com/",
        tags=("ai", "ml"),
    )

    def __init__(
        self,
        *,
        api_token: str,
        base_url: str = "https://api.replicate.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_token:
            raise ValueError("api_token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_token, header="Authorization", prefix="Bearer"),
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
    def list_models(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List public models on Replicate.

        Best first tool for model discovery. Returns compact summaries with
        a stable ``model_ref`` (``model_1``, ``model_2``, ...), owner,
        name, description, and run count. The Replicate model name
        ``"owner/name"`` is included as ``model_name`` because callers
        need it for :meth:`create_prediction`. Set ``include_ids=True``
        for the raw latest-version ``id``. Default limit: 25.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        payload: Any = self._client.get("/v1/models").json()
        models: list[Any] = _extract_results(payload)
        summaries: list[dict[str, Any]] = []
        for index, model in enumerate(models[:max_results], start=1):
            if not isinstance(model, dict):
                continue
            entry = cast(dict[str, Any], model)
            owner = entry.get("owner", "")
            name = entry.get("name", "")
            summary: dict[str, Any] = {
                "model_ref": f"model_{index}",
                "model_name": f"{owner}/{name}" if owner and name else (name or ""),
                "owner": owner,
                "name": name,
                "description": entry.get("description", ""),
                "run_count": entry.get("run_count"),
                "visibility": entry.get("visibility", ""),
            }
            if include_ids:
                latest: Any = entry.get("latest_version") or {}
                summary["latest_version_id"] = (
                    cast(dict[str, Any], latest).get("id", "") if isinstance(latest, dict) else ""
                )
            summaries.append(summary)
        return {"models": summaries, "next": payload.get("next")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_model(self, *, owner: str, name: str) -> dict[str, Any]:
        """Return one model by ``owner/name``.

        Returns the raw model resource including ``latest_version`` (used
        as the ``version`` argument to :meth:`create_prediction`).
        """
        if not owner or not name:
            raise ValueError("owner and name must be non-empty")
        return self._client.get(f"/v1/models/{owner}/{name}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_prediction(
        self,
        *,
        version: str | None = None,
        model: str | None = None,
        input: dict[str, Any],
        webhook: str | None = None,
        stream: bool | None = None,
    ) -> dict[str, Any]:
        """Create a prediction (by version ID or by ``owner/name`` model).

        Returns the new prediction resource (``id``, ``status``,
        ``output``). Use ``version`` for a pinned model version (from
        :meth:`get_model`), or ``model`` (``"owner/name"``) for the latest
        version.
        """
        if not input or (version is None and model is None):
            raise ValueError("input and one of version/model are required")
        body: dict[str, Any] = {"input": input}
        if version is not None:
            body["version"] = version
        if webhook is not None:
            body["webhook"] = webhook
        if stream is not None:
            body["stream"] = stream
        path = "/v1/predictions" if version is not None else f"/v1/models/{model}/predictions"
        return self._client.post(path, json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_prediction(self, prediction_id: Any) -> dict[str, Any]:
        """Return prediction status / output.

        Accepts a raw prediction-id string or a prediction dict returned by
        :meth:`create_prediction`.
        """
        resolved = _resolve_id(prediction_id, "prediction_id", "id")
        if not resolved:
            raise ValueError("prediction_id must be a non-empty string")
        return self._client.get(f"/v1/predictions/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def cancel_prediction(self, prediction_id: Any) -> dict[str, Any]:
        """Cancel an in-progress prediction. Destructive; confirm first.

        Accepts the same input shapes as :meth:`get_prediction` (raw ID
        string or prediction dict).
        """
        resolved = _resolve_id(prediction_id, "prediction_id", "id")
        if not resolved:
            raise ValueError("prediction_id must be a non-empty string")
        return self._client.post(
            f"/v1/predictions/{resolved}/cancel",
            json={},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_predictions(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List recent predictions.

        Returns compact summaries with a stable ``prediction_ref``
        (``prediction_1``, ``prediction_2``, ...), model version, status,
        and timestamps. Raw prediction IDs are omitted by default. Set
        ``include_ids=True`` when a follow-up tool (get_prediction,
        cancel_prediction) needs them. Default limit: 25.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        payload: Any = self._client.get("/v1/predictions").json()
        predictions: list[Any] = _extract_results(payload)
        summaries: list[dict[str, Any]] = []
        for index, prediction in enumerate(predictions[:max_results], start=1):
            if not isinstance(prediction, dict):
                continue
            entry = cast(dict[str, Any], prediction)
            summary: dict[str, Any] = {
                "prediction_ref": f"prediction_{index}",
                "version": entry.get("version", ""),
                "status": entry.get("status", ""),
                "created_at": entry.get("created_at"),
                "completed_at": entry.get("completed_at"),
            }
            if include_ids:
                summary["prediction_id"] = entry.get("id", "")
            summaries.append(summary)
        return {"predictions": summaries, "next": payload.get("next")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_deployments(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List deployments.

        Returns compact summaries with a stable ``deployment_ref``
        (``deployment_1``, ``deployment_2``, ...), owner/name (needed for
        :meth:`predict_deployment`), and current version. Default
        limit: 25.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        payload: Any = self._client.get("/v1/deployments").json()
        deployments: list[Any] = _extract_results(payload)
        summaries: list[dict[str, Any]] = []
        for index, deployment in enumerate(deployments[:max_results], start=1):
            if not isinstance(deployment, dict):
                continue
            entry = cast(dict[str, Any], deployment)
            owner = entry.get("owner", "")
            name = entry.get("name", "")
            current_release: Any = entry.get("current_release")
            summary: dict[str, Any] = {
                "deployment_ref": f"deployment_{index}",
                "owner": owner,
                "name": name,
                "deployment_path": f"{owner}/{name}" if owner and name else "",
                "current_release_version": cast(dict[str, Any], current_release).get("version", "")
                if isinstance(current_release, dict)
                else "",
            }
            if include_ids:
                summary["id"] = entry.get("id", "")
            summaries.append(summary)
        return {"deployments": summaries, "next": payload.get("next")}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def predict_deployment(
        self,
        *,
        owner: str,
        name: str,
        input: dict[str, Any],
    ) -> dict[str, Any]:
        """Run a deployment prediction.

        Returns the new prediction resource (``id``, ``status``,
        ``output``). Use :meth:`list_deployments` to find the
        ``owner`` and ``name``.
        """
        if not owner or not name or not input:
            raise ValueError("owner, name, and input must be non-empty")
        return self._client.post(
            f"/v1/deployments/{owner}/{name}/predictions",
            json={"input": input},
        ).json()
