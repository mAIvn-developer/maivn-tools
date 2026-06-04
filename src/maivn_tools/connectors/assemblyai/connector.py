# pyright: strict
"""AssemblyAI API connector."""

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

_DEFAULT_LIST_LIMIT = 10

# AssemblyAI's LeMUR API was fully sunset on 2026-03-31 and replaced by the
# LLM Gateway, an OpenAI-compatible chat-completions endpoint. The gateway lives
# on its own host (not api.assemblyai.com), so requests target the absolute URL.
# The same raw-key Authorization header used for the v2 API authenticates here.
_LLM_GATEWAY_URL = "https://llm-gateway.assemblyai.com/v1/chat/completions"

# Model IDs are exact, versioned strings; shorthand aliases are rejected by the
# gateway. The former LeMUR ``"default"`` alias no longer resolves.
_DEFAULT_LLM_MODEL = "claude-sonnet-4-6"


# MARK: Helpers


def _resolve_id(value: Any, *id_keys: str) -> str:
    """Extract a string identifier from a raw id, dict, or list of dicts."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        mapping = cast(dict[str, Any], value)
        transcripts = mapping.get("transcripts")
        if isinstance(transcripts, list) and transcripts:
            items = cast(list[Any], transcripts)
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


@toolset(prefix="assemblyai")
class AssemblyAIToolSet:
    """A connector for the AssemblyAI API."""

    metadata = ProviderMetadata(
        name="assemblyai",
        display_name="AssemblyAI",
        version="0.1.0",
        description="Transcription, audio intelligence, and LLM tasks over transcripts.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://www.assemblyai.com/docs",
        homepage_url="https://www.assemblyai.com/",
        tags=("ai", "audio"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.assemblyai.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="Authorization"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upload(self, *, audio_bytes: bytes) -> dict[str, Any]:
        """Upload audio bytes for transcription.

        Returns ``{"upload_url": ...}``. Pass the ``upload_url`` as the
        ``audio_url`` argument to :meth:`submit_transcript`.
        """
        if not audio_bytes:
            raise ValueError("audio_bytes must be non-empty")
        return self._client.post(
            "/v2/upload",
            data=audio_bytes,
            headers={"Content-Type": "application/octet-stream"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def submit_transcript(
        self,
        *,
        audio_url: str,
        speaker_labels: bool = False,
        sentiment_analysis: bool = False,
        entity_detection: bool = False,
        summarization: bool = False,
        iab_categories: bool = False,
        language_code: str | None = None,
        webhook_url: str | None = None,
    ) -> dict[str, Any]:
        """Submit a transcript job.

        Returns the new transcript resource (``id``, ``status="queued"``,
        ``audio_url``). Poll status with :meth:`get_transcript` (or use
        ``webhook_url`` for push notification).
        """
        if not audio_url:
            raise ValueError("audio_url must be a non-empty string")
        body: dict[str, Any] = {
            "audio_url": audio_url,
            "speaker_labels": speaker_labels,
            "sentiment_analysis": sentiment_analysis,
            "entity_detection": entity_detection,
            "summarization": summarization,
            "iab_categories": iab_categories,
        }
        if language_code is not None:
            body["language_code"] = language_code
        if webhook_url is not None:
            body["webhook_url"] = webhook_url
        return self._client.post("/v2/transcript", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_transcript(self, transcript_id: Any) -> dict[str, Any]:
        """Return transcript status / result.

        Accepts a raw transcript-id string or a transcript dict returned
        by :meth:`submit_transcript` / :meth:`list_transcripts` (with
        ``include_ids=True``). Returns the raw transcript resource — text
        is at ``text``, words at ``words``, utterances at ``utterances``.
        """
        resolved = _resolve_id(transcript_id, "transcript_id", "id")
        if not resolved:
            raise ValueError("transcript_id must be a non-empty string")
        return self._client.get(f"/v2/transcript/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_transcripts(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List recent transcripts on the account.

        Best first tool for transcript triage. Returns compact summaries
        with a stable ``transcript_ref`` (``transcript_1``, ...), status,
        audio URL, and creation time. Raw transcript IDs are omitted by
        default — set ``include_ids=True`` when a follow-up tool
        (get_transcript, delete_transcript, lemur_task) needs them.
        Default limit: 10.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        payload: object = self._client.get(
            "/v2/transcript",
            params={"limit": max_results},
        ).json()
        payload_dict: dict[str, Any] = (
            cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
        )
        raw_transcripts: object = payload_dict.get("transcripts", [])
        transcripts: list[Any] = (
            cast(list[Any], raw_transcripts) if isinstance(raw_transcripts, list) else []
        )
        summaries: list[dict[str, Any]] = []
        for index, transcript in enumerate(transcripts[:max_results], start=1):
            if not isinstance(transcript, dict):
                continue
            transcript_dict = cast(dict[str, Any], transcript)
            summary: dict[str, Any] = {
                "transcript_ref": f"transcript_{index}",
                "status": transcript_dict.get("status", ""),
                "audio_url": transcript_dict.get("audio_url", ""),
                "created": transcript_dict.get("created", ""),
                "completed": transcript_dict.get("completed", ""),
            }
            if include_ids:
                summary["transcript_id"] = transcript_dict.get("id", "")
            summaries.append(summary)
        return {
            "transcripts": summaries,
            "page_details": payload_dict.get("page_details", {}),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_transcript(self, transcript_id: Any) -> dict[str, Any]:
        """Delete a transcript. Destructive; confirm with the user first.

        Accepts a raw transcript-id string or a transcript dict from
        :meth:`list_transcripts` (with ``include_ids=True``).
        """
        resolved = _resolve_id(transcript_id, "transcript_id", "id")
        if not resolved:
            raise ValueError("transcript_id must be a non-empty string")
        return self._client.delete(f"/v2/transcript/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def lemur_task(
        self,
        *,
        transcript_ids: list[Any],
        prompt: str,
        final_model: str = _DEFAULT_LLM_MODEL,
        max_output_size: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Run an LLM task over one or more transcripts.

        Asks ``final_model`` to answer ``prompt`` using the transcript text as
        context. Returns ``{"response": ..., "request_id": ...}``.

        ``transcript_ids`` accepts a list of raw IDs or a list of transcript
        dicts from :meth:`list_transcripts` (with ``include_ids=True``).
        ``final_model`` must be an exact, versioned model id (e.g.
        ``"claude-sonnet-4-6"``); shorthand aliases are rejected.

        The legacy LeMUR API this method previously used was sunset on
        2026-03-31; it now calls AssemblyAI's OpenAI-compatible LLM Gateway,
        fetching each transcript's text and embedding it as context.
        """
        if not transcript_ids or not prompt:
            raise ValueError("transcript_ids and prompt must be non-empty")
        if not final_model:
            raise ValueError("final_model must be a non-empty model id")
        resolved_ids = [_resolve_id(tid, "transcript_id", "id") for tid in transcript_ids]
        context_blocks: list[str] = []
        for resolved in resolved_ids:
            transcript: object = self._client.get(f"/v2/transcript/{resolved}").json()
            text: Any = (
                cast(dict[str, Any], transcript).get("text", "")
                if isinstance(transcript, dict)
                else ""
            )
            context_blocks.append(f"Transcript {resolved}:\n{text}")
        transcript_context = "\n\n".join(context_blocks)
        user_content = f"{prompt}\n\n---\n\n{transcript_context}"
        body: dict[str, Any] = {
            "model": final_model,
            "messages": [{"role": "user", "content": user_content}],
        }
        if max_output_size is not None:
            body["max_tokens"] = max_output_size
        if temperature is not None:
            body["temperature"] = temperature
        payload: object = self._client.post(_LLM_GATEWAY_URL, json=body).json()
        payload_dict: dict[str, Any] = (
            cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
        )
        raw_choices: object = payload_dict.get("choices", [])
        choices: list[Any] = cast(list[Any], raw_choices) if isinstance(raw_choices, list) else []
        response_text: Any = ""
        if choices and isinstance(choices[0], dict):
            message: Any = cast(dict[str, Any], choices[0]).get("message")
            if isinstance(message, dict):
                response_text = cast(dict[str, Any], message).get("content", "") or ""
        request_id: Any = payload_dict.get("id", "")
        return {"response": response_text, "request_id": request_id}
