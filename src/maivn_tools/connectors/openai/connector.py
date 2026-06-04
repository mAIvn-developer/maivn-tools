"""OpenAI API connector (Chat, Responses, Embeddings, Files, Batches, Models)."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

_DEFAULT_LIST_LIMIT = 20


def _resolve_id(value: Any, *id_keys: str) -> str:
    """Extract a string identifier from a raw id, dict, or list of dicts.

    Used to make write tools tolerant of natural list/get outputs. Accepts:
    - a plain string id (returned as-is),
    - a dict with one of the ``id_keys`` fields,
    - a list/tuple of strings or dicts (the first valid candidate wins),
    - the typical OpenAI list response ``{"data": [...]}``.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        mapping = cast(dict[str, Any], value)
        data = mapping.get("data")
        if isinstance(data, list) and data:
            items = cast(list[Any], data)
            return _resolve_id(items[0], *id_keys)
        for key in id_keys:
            candidate = mapping.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        raise ValueError(f"could not resolve id from dict (expected one of: {', '.join(id_keys)})")
    if isinstance(value, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", value)
        for item in sequence:
            try:
                return _resolve_id(item, *id_keys)
            except ValueError:
                continue
    raise ValueError("identifier must be a non-empty string, dict, or list")


@toolset(prefix="openai")
class OpenAIToolSet:
    """A connector for the OpenAI REST API.

    Covers Responses, Chat Completions, Embeddings, Files, Batches,
    Models, Images, Audio, Moderations, Fine-tuning jobs, and Vector
    Stores under one API-key credential.

    Args:
        api_key: OpenAI API key.
        organization: Optional ``OpenAI-Organization`` header.
        project: Optional ``OpenAI-Project`` header.
        base_url: API root.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="openai",
        display_name="OpenAI",
        version="0.1.0",
        description="Call OpenAI Chat, Responses, Embeddings, Images, Audio, Files, Batches.",
        auth_modes=(AuthMode.API_KEY, AuthMode.BEARER),
        scopes={"api": "Full API access."},
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.STREAMING,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://platform.openai.com/docs/api-reference",
        homepage_url="https://platform.openai.com/",
        tags=("ai", "llm"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        organization: str | None = None,
        project: str | None = None,
        base_url: str = "https://api.openai.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        headers: dict[str, str] = {"Accept": "application/json"}
        if organization is not None:
            headers["OpenAI-Organization"] = organization
        if project is not None:
            headers["OpenAI-Project"] = project
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(api_key),
            transport=transport,
            default_headers=headers,
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Chat / Responses

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_completion_tokens: int | None = None,
        top_p: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        response_format: dict[str, Any] | None = None,
        seed: int | None = None,
        user: str | None = None,
        stop: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a chat completion (``/v1/chat/completions``).

        Returns the raw OpenAI chat-completion response with generated
        ``choices`` containing the assistant message. Pass ``model`` as the
        model name (e.g. ``"gpt-4o-mini"``) which you can discover via
        :meth:`list_models`.
        """
        if not model:
            raise ValueError("model must be a non-empty string")
        if not messages:
            raise ValueError("messages must be a non-empty list")
        body: dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if max_completion_tokens is not None:
            body["max_completion_tokens"] = max_completion_tokens
        if top_p is not None:
            body["top_p"] = top_p
        if tools is not None:
            body["tools"] = tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        if response_format is not None:
            body["response_format"] = response_format
        if seed is not None:
            body["seed"] = seed
        if user is not None:
            body["user"] = user
        if stop is not None:
            body["stop"] = stop
        return self._client.post("/v1/chat/completions", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def responses_create(
        self,
        *,
        model: str,
        input: Any,
        instructions: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        text: dict[str, Any] | None = None,
        store: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a Response (``/v1/responses``).

        Returns the raw Response object including the assistant ``output``.
        When ``store=True``, the response is persisted server-side and can be
        fetched later by ID using :meth:`get_response`.

        For structured output, pass ``text`` as the Responses-API
        ``text`` config object, e.g.
        ``text={"format": {"type": "json_schema", "name": ..., "schema": ...}}``.
        The Responses API does not accept the Chat Completions
        ``response_format`` parameter.
        """
        if not model:
            raise ValueError("model must be a non-empty string")
        body: dict[str, Any] = {"model": model, "input": input}
        if instructions is not None:
            body["instructions"] = instructions
        if tools is not None:
            body["tools"] = tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        if text is not None:
            body["text"] = text
        if store is not None:
            body["store"] = store
        if metadata is not None:
            body["metadata"] = metadata
        return self._client.post("/v1/responses", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_response(self, response_id: str) -> dict[str, Any]:
        """Return a stored Response by ID.

        ``response_id`` is the raw ``resp_...`` handle returned by
        :meth:`responses_create` when ``store=True``.
        """
        if not response_id:
            raise ValueError("response_id must be a non-empty string")
        return self._client.get(f"/v1/responses/{response_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_response(self, response_id: str) -> dict[str, Any]:
        """Delete a stored Response. Destructive; confirm with the user first."""
        if not response_id:
            raise ValueError("response_id must be a non-empty string")
        return self._client.delete(f"/v1/responses/{response_id}").json()

    # MARK: - Embeddings

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_embedding(
        self,
        *,
        model: str,
        input: str | list[str] | list[int] | list[list[int]],
        encoding_format: str | None = None,
        dimensions: int | None = None,
        user: str | None = None,
    ) -> dict[str, Any]:
        """Create one or more embeddings.

        Returns ``{"data": [{"embedding": [...], "index": n}, ...]}``. Use
        an embedding model (e.g. ``"text-embedding-3-small"``).
        """
        if not model:
            raise ValueError("model must be a non-empty string")
        body: dict[str, Any] = {"model": model, "input": input}
        if encoding_format is not None:
            if encoding_format not in {"float", "base64"}:
                raise ValueError("encoding_format must be 'float' or 'base64'")
            body["encoding_format"] = encoding_format
        if dimensions is not None:
            body["dimensions"] = dimensions
        if user is not None:
            body["user"] = user
        return self._client.post("/v1/embeddings", json=body).json()

    # MARK: - Models

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_models(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List available OpenAI models.

        Best first tool for model discovery. Returns compact summaries with
        a stable ``model_ref`` (``model_1``, ``model_2``, ...) plus the
        model name and owner. The raw provider ``id`` is the model name
        itself, so it is included as ``model_name`` (you need it to call
        chat / embedding / image tools). Set ``include_ids=True`` to also
        get the raw ``id`` field for round-tripping. Default limit: 20.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        payload: Any = self._client.get("/v1/models").json()
        mapping: dict[str, Any] = cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
        models = cast(list[Any], mapping.get("data", []))
        summaries: list[dict[str, Any]] = []
        for index, raw_model in enumerate(models[:max_results], start=1):
            if not isinstance(raw_model, dict):
                continue
            model = cast(dict[str, Any], raw_model)
            summary: dict[str, Any] = {
                "model_ref": f"model_{index}",
                "model_name": model.get("id", ""),
                "owned_by": model.get("owned_by", ""),
                "created": model.get("created"),
            }
            if include_ids:
                summary["id"] = model.get("id", "")
            summaries.append(summary)
        return {"models": summaries, "total": len(models)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_model(self, model: str) -> dict[str, Any]:
        """Return one model by name.

        Returns the raw model resource (``id``, ``owned_by``, ``created``).
        """
        if not model:
            raise ValueError("model must be a non-empty string")
        return self._client.get(f"/v1/models/{model}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_fine_tuned_model(self, model: str) -> dict[str, Any]:
        """Delete a fine-tuned model. Only fine-tunes are deletable.

        Destructive: the underlying weights are removed. Confirm with the
        user first.
        """
        if not model:
            raise ValueError("model must be a non-empty string")
        return self._client.delete(f"/v1/models/{model}").json()

    # MARK: - Images / Audio

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def generate_image(
        self,
        *,
        model: str,
        prompt: str,
        n: int | None = None,
        size: str | None = None,
        quality: str | None = None,
        response_format: str | None = None,
        style: str | None = None,
        user: str | None = None,
    ) -> dict[str, Any]:
        """Generate an image (``/v1/images/generations``).

        Returns ``{"data": [{"url" or "b64_json": ...}, ...]}``. Use
        ``model="gpt-image-1"`` for the latest generator.
        """
        if not model or not prompt:
            raise ValueError("model and prompt must be non-empty")
        body: dict[str, Any] = {"model": model, "prompt": prompt}
        if n is not None:
            body["n"] = n
        if size is not None:
            body["size"] = size
        if quality is not None:
            body["quality"] = quality
        if response_format is not None:
            body["response_format"] = response_format
        if style is not None:
            body["style"] = style
        if user is not None:
            body["user"] = user
        return self._client.post("/v1/images/generations", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def speech(
        self,
        *,
        model: str,
        voice: str,
        input: str,
        response_format: str | None = None,
        speed: float | None = None,
    ) -> dict[str, Any]:
        """Synthesize speech. Returns raw audio bytes in ``body``.

        Returns ``{"status": int, "body": <bytes>}``. Decode/serve the bytes
        directly — they are the audio payload in the requested
        ``response_format`` (default ``mp3``).
        """
        if not model or not voice or not input:
            raise ValueError("model, voice, and input must be non-empty")
        body: dict[str, Any] = {"model": model, "voice": voice, "input": input}
        if response_format is not None:
            body["response_format"] = response_format
        if speed is not None:
            body["speed"] = speed
        response = self._client.post("/v1/audio/speech", json=body)
        return {"status": response.status, "body": response.body}

    # MARK: - Files

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_files(
        self,
        *,
        purpose: str | None = None,
        max_results: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List uploaded files.

        Best first tool for file discovery. Returns compact summaries with a
        stable ``file_ref`` (``file_1``, ``file_2``, ...), plus filename,
        purpose, size, and creation time. Raw ``file-...`` IDs are omitted
        by default because they are internal handles. Set
        ``include_ids=True`` only when a follow-up tool (delete_file,
        create_batch) needs the raw ID. Default limit: 20.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        params = {"purpose": purpose} if purpose else None
        payload: Any = self._client.get("/v1/files", params=params).json()
        mapping: dict[str, Any] = cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
        files = cast(list[Any], mapping.get("data", []))
        summaries: list[dict[str, Any]] = []
        for index, raw_item in enumerate(files[:max_results], start=1):
            if not isinstance(raw_item, dict):
                continue
            item = cast(dict[str, Any], raw_item)
            summary: dict[str, Any] = {
                "file_ref": f"file_{index}",
                "filename": item.get("filename", ""),
                "purpose": item.get("purpose", ""),
                "bytes": item.get("bytes"),
                "created_at": item.get("created_at"),
                "status": item.get("status", ""),
            }
            if include_ids:
                summary["file_id"] = item.get("id", "")
            summaries.append(summary)
        return {"files": summaries, "total": len(files)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_file(self, file_id: Any) -> dict[str, Any]:
        """Return metadata about an uploaded file.

        Accepts a raw ``file-...`` ID string, the dict returned by
        :meth:`list_files` with ``include_ids=True``, or the
        ``{"data": [...]}`` list response. Returns the raw file resource.
        """
        resolved = _resolve_id(file_id, "file_id", "id")
        if not resolved:
            raise ValueError("file_id must be a non-empty string")
        return self._client.get(f"/v1/files/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_file(self, file_id: Any) -> dict[str, Any]:
        """Delete an uploaded file. Destructive; confirm with the user first.

        Accepts the same input shapes as :meth:`get_file` (raw ID, file
        dict, or list response).
        """
        resolved = _resolve_id(file_id, "file_id", "id")
        if not resolved:
            raise ValueError("file_id must be a non-empty string")
        return self._client.delete(f"/v1/files/{resolved}").json()

    # MARK: - Batches

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_batch(
        self,
        *,
        input_file_id: Any,
        endpoint: str,
        completion_window: str = "24h",
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a batch job.

        Returns the new batch resource (``id``, ``status``, etc.).
        ``input_file_id`` accepts a raw ``file-...`` ID string or the file
        dict from :meth:`list_files`/``get_file``.
        """
        resolved_file = _resolve_id(input_file_id, "file_id", "id")
        if not resolved_file or not endpoint:
            raise ValueError("input_file_id and endpoint must be non-empty")
        body: dict[str, Any] = {
            "input_file_id": resolved_file,
            "endpoint": endpoint,
            "completion_window": completion_window,
        }
        if metadata is not None:
            body["metadata"] = metadata
        return self._client.post("/v1/batches", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_batches(
        self,
        *,
        after: str | None = None,
        limit: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List batch jobs.

        Returns compact summaries with a stable ``batch_ref`` (``batch_1``,
        ``batch_2``, ...), endpoint, status, request counts, and creation
        time. Raw ``batch_...`` IDs are omitted by default — set
        ``include_ids=True`` when a follow-up tool (get_batch,
        cancel_batch) needs them. Default limit: 20.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        params: dict[str, Any] = {"limit": limit}
        if after is not None:
            params["after"] = after
        payload: Any = self._client.get("/v1/batches", params=params).json()
        mapping: dict[str, Any] = cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
        batches = cast(list[Any], mapping.get("data", []))
        summaries: list[dict[str, Any]] = []
        for index, raw_batch in enumerate(batches, start=1):
            if not isinstance(raw_batch, dict):
                continue
            batch = cast(dict[str, Any], raw_batch)
            summary: dict[str, Any] = {
                "batch_ref": f"batch_{index}",
                "endpoint": batch.get("endpoint", ""),
                "status": batch.get("status", ""),
                "request_counts": batch.get("request_counts", {}),
                "created_at": batch.get("created_at"),
            }
            if include_ids:
                summary["batch_id"] = batch.get("id", "")
            summaries.append(summary)
        return {"batches": summaries, "has_more": mapping.get("has_more", False)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_batch(self, batch_id: Any) -> dict[str, Any]:
        """Return a batch by ID.

        Accepts a raw ``batch_...`` string, a batch dict from
        :meth:`list_batches` (with ``include_ids=True``), or the
        ``{"data": [...]}`` list response.
        """
        resolved = _resolve_id(batch_id, "batch_id", "id")
        if not resolved:
            raise ValueError("batch_id must be a non-empty string")
        return self._client.get(f"/v1/batches/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def cancel_batch(self, batch_id: Any) -> dict[str, Any]:
        """Cancel a batch. Destructive; confirm with the user first.

        Accepts the same input shapes as :meth:`get_batch` (raw ID, batch
        dict, or list response).
        """
        resolved = _resolve_id(batch_id, "batch_id", "id")
        if not resolved:
            raise ValueError("batch_id must be a non-empty string")
        return self._client.post(f"/v1/batches/{resolved}/cancel").json()

    # MARK: - Moderations

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def moderate(
        self,
        *,
        input: str | list[str],
        model: str = "omni-moderation-latest",
    ) -> dict[str, Any]:
        """Run a moderation check.

        Returns ``{"results": [{"flagged": bool, "categories": {...},
        "category_scores": {...}}, ...]}``.
        """
        return self._client.post(
            "/v1/moderations",
            json={"input": input, "model": model},
        ).json()

    # MARK: - Fine-tuning

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_fine_tuning_job(
        self,
        *,
        training_file: Any,
        model: str,
        validation_file: Any | None = None,
        hyperparameters: dict[str, Any] | None = None,
        suffix: str | None = None,
    ) -> dict[str, Any]:
        """Create a fine-tuning job.

        Returns the new job resource (``id``, ``status``, ``model``).
        ``training_file`` and ``validation_file`` accept raw ``file-...``
        IDs or the file dicts from :meth:`list_files`.
        """
        resolved_training = _resolve_id(training_file, "file_id", "id")
        if not resolved_training or not model:
            raise ValueError("training_file and model must be non-empty")
        body: dict[str, Any] = {"training_file": resolved_training, "model": model}
        if validation_file is not None:
            body["validation_file"] = _resolve_id(validation_file, "file_id", "id")
        if hyperparameters is not None:
            body["hyperparameters"] = hyperparameters
        if suffix is not None:
            body["suffix"] = suffix
        return self._client.post("/v1/fine_tuning/jobs", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_fine_tuning_jobs(
        self,
        *,
        limit: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List fine-tuning jobs.

        Returns compact summaries with a stable ``job_ref`` (``job_1``,
        ``job_2``, ...), the base/fine-tuned model names, status, and
        creation time. Raw ``ftjob_...`` IDs are omitted by default — set
        ``include_ids=True`` when a follow-up tool (cancel_fine_tuning_job)
        needs them. Default limit: 20.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        payload: Any = self._client.get(
            "/v1/fine_tuning/jobs",
            params={"limit": limit},
        ).json()
        mapping: dict[str, Any] = cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
        jobs = cast(list[Any], mapping.get("data", []))
        summaries: list[dict[str, Any]] = []
        for index, raw_job in enumerate(jobs, start=1):
            if not isinstance(raw_job, dict):
                continue
            job = cast(dict[str, Any], raw_job)
            summary: dict[str, Any] = {
                "job_ref": f"job_{index}",
                "model": job.get("model", ""),
                "fine_tuned_model": job.get("fine_tuned_model"),
                "status": job.get("status", ""),
                "created_at": job.get("created_at"),
            }
            if include_ids:
                summary["job_id"] = job.get("id", "")
            summaries.append(summary)
        return {"jobs": summaries, "has_more": mapping.get("has_more", False)}

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def cancel_fine_tuning_job(self, job_id: Any) -> dict[str, Any]:
        """Cancel a running fine-tuning job. Destructive; confirm first.

        Accepts a raw ``ftjob_...`` string, a job dict from
        :meth:`list_fine_tuning_jobs` (with ``include_ids=True``), or the
        list response.
        """
        resolved = _resolve_id(job_id, "job_id", "id")
        if not resolved:
            raise ValueError("job_id must be a non-empty string")
        return self._client.post(f"/v1/fine_tuning/jobs/{resolved}/cancel").json()

    # MARK: - Vector stores

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_vector_store(
        self,
        *,
        name: str,
        file_ids: list[Any] | None = None,
        metadata: dict[str, Any] | None = None,
        expires_after: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a vector store.

        Returns the new vector-store resource (``id``, ``name``,
        ``status``). ``file_ids`` accepts a list of raw ``file-...`` IDs or
        a list of file dicts from :meth:`list_files`.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        body: dict[str, Any] = {"name": name}
        if file_ids is not None:
            body["file_ids"] = [_resolve_id(fid, "file_id", "id") for fid in file_ids]
        if metadata is not None:
            body["metadata"] = metadata
        if expires_after is not None:
            body["expires_after"] = expires_after
        return self._client.post("/v1/vector_stores", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_vector_stores(
        self,
        *,
        limit: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List vector stores.

        Returns compact summaries with a stable ``store_ref`` (``store_1``,
        ``store_2``, ...), name, file counts, status, and creation time.
        Raw ``vs_...`` IDs are omitted by default — set ``include_ids=True``
        when a follow-up tool needs them. Default limit: 20.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        payload: Any = self._client.get("/v1/vector_stores", params={"limit": limit}).json()
        mapping: dict[str, Any] = cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
        stores = cast(list[Any], mapping.get("data", []))
        summaries: list[dict[str, Any]] = []
        for index, raw_store in enumerate(stores, start=1):
            if not isinstance(raw_store, dict):
                continue
            store = cast(dict[str, Any], raw_store)
            summary: dict[str, Any] = {
                "store_ref": f"store_{index}",
                "name": store.get("name", ""),
                "file_counts": store.get("file_counts", {}),
                "status": store.get("status", ""),
                "created_at": store.get("created_at"),
            }
            if include_ids:
                summary["store_id"] = store.get("id", "")
            summaries.append(summary)
        return {"vector_stores": summaries, "has_more": mapping.get("has_more", False)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_vector_store(self, vector_store_id: Any) -> dict[str, Any]:
        """Return one vector store.

        Accepts a raw ``vs_...`` string or a store dict from
        :meth:`list_vector_stores` (with ``include_ids=True``).
        """
        resolved = _resolve_id(vector_store_id, "store_id", "id")
        if not resolved:
            raise ValueError("vector_store_id must be a non-empty string")
        return self._client.get(f"/v1/vector_stores/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_vector_store(self, vector_store_id: Any) -> dict[str, Any]:
        """Delete a vector store. Destructive; confirm with the user first.

        Accepts the same input shapes as :meth:`get_vector_store`.
        """
        resolved = _resolve_id(vector_store_id, "store_id", "id")
        if not resolved:
            raise ValueError("vector_store_id must be a non-empty string")
        return self._client.delete(f"/v1/vector_stores/{resolved}").json()
