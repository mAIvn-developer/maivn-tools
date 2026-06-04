"""ElevenLabs API connector."""

# pyright: strict

from __future__ import annotations

import uuid
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


def _encode_multipart(
    fields: dict[str, str],
    file_field: str,
    filename: str,
    file_bytes: bytes,
    content_type: str,
) -> tuple[bytes, str]:
    """Encode ``fields`` and a single file into a ``multipart/form-data`` body.

    Returns ``(body, content_type_header)`` where ``content_type_header``
    includes the generated boundary. The ElevenLabs speech-to-text endpoint
    mandates ``multipart/form-data``; the runtime transport only forwards raw
    bytes, so the encoding is done here.
    """
    boundary = f"----maivnboundary{uuid.uuid4().hex}"
    crlf = b"\r\n"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(b"--" + boundary.encode("ascii"))
        parts.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        parts.append(b"")
        parts.append(value.encode("utf-8"))
    parts.append(b"--" + boundary.encode("ascii"))
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"'.encode()
    )
    parts.append(f"Content-Type: {content_type}".encode("ascii"))
    parts.append(b"")
    parts.append(file_bytes)
    parts.append(b"--" + boundary.encode("ascii") + b"--")
    parts.append(b"")
    body = crlf.join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


# MARK: ToolSet


@toolset(prefix="elevenlabs")
class ElevenLabsToolSet:
    """A connector for the ElevenLabs API (TTS, STT, voices)."""

    metadata = ProviderMetadata(
        name="elevenlabs",
        display_name="ElevenLabs",
        version="0.1.0",
        description="Text-to-speech, speech-to-text, voices, models, history.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://elevenlabs.io/docs/api-reference",
        homepage_url="https://elevenlabs.io/",
        tags=("ai", "audio"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.elevenlabs.io",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="xi-api-key"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def text_to_speech(
        self,
        *,
        voice_id: str,
        text: str,
        model_id: str = "eleven_multilingual_v2",
        output_format: str = "mp3_44100_128",
        voice_settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Synthesize audio for ``text``.

        Returns ``{"status": int, "body": <audio bytes>}``. ``voice_id``
        is the ElevenLabs voice handle from :meth:`list_voices`.
        """
        if not voice_id or not text:
            raise ValueError("voice_id and text must be non-empty")
        body: dict[str, Any] = {"text": text, "model_id": model_id}
        if voice_settings is not None:
            body["voice_settings"] = voice_settings
        response = self._client.post(
            f"/v1/text-to-speech/{voice_id}",
            params={"output_format": output_format},
            json=body,
        )
        return {"status": response.status, "body": response.body}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def speech_to_text(
        self,
        *,
        audio_bytes: bytes,
        model_id: str = "scribe_v2",
        diarize: bool = False,
        language_code: str | None = None,
    ) -> dict[str, Any]:
        """Transcribe audio bytes.

        Returns the raw transcript resource including ``text`` (the full
        transcript) and ``words`` (per-word timing) if ``diarize=True``.

        The request is sent as ``multipart/form-data``: the audio is the
        ``file`` form field and ``model_id`` / ``diarize`` / ``language_code``
        are form fields, as required by the ElevenLabs API.
        """
        if not audio_bytes:
            raise ValueError("audio_bytes must be non-empty")
        fields: dict[str, str] = {"model_id": model_id, "diarize": str(diarize).lower()}
        if language_code is not None:
            fields["language_code"] = language_code
        body, content_type = _encode_multipart(
            fields,
            file_field="file",
            filename="audio",
            file_bytes=audio_bytes,
            content_type="application/octet-stream",
        )
        return self._client.post(
            "/v1/speech-to-text",
            data=body,
            headers={"Content-Type": content_type},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_voices(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List voices available to the account.

        Best first tool for voice discovery. Returns compact summaries with
        a stable ``voice_ref`` (``voice_1``, ``voice_2``, ...), human name,
        category, and basic labels. The ElevenLabs ``voice_id`` is
        included as ``voice_id`` because callers need it for
        :meth:`text_to_speech` and :meth:`get_voice`. Set
        ``include_ids=True`` for the redundant raw ``voice_id`` field.
        Default limit: 25.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        payload: object = self._client.get("/v1/voices").json()
        mapping: dict[str, Any] = (
            cast("dict[str, Any]", payload) if isinstance(payload, dict) else {}
        )
        raw_voices: object = mapping.get("voices", [])
        voices: list[object] = (
            cast("list[object]", raw_voices) if isinstance(raw_voices, list) else []
        )
        summaries: list[dict[str, Any]] = []
        for index, item in enumerate(voices[:max_results], start=1):
            if not isinstance(item, dict):
                continue
            voice: dict[str, Any] = cast("dict[str, Any]", item)
            summary: dict[str, Any] = {
                "voice_ref": f"voice_{index}",
                "name": voice.get("name", ""),
                "voice_id": voice.get("voice_id", ""),
                "category": voice.get("category", ""),
                "labels": voice.get("labels", {}),
                "description": voice.get("description", ""),
            }
            if include_ids:
                summary["id"] = voice.get("voice_id", "")
            summaries.append(summary)
        return {"voices": summaries, "total": len(voices)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_voice(self, voice_id: str) -> dict[str, Any]:
        """Return one voice.

        Returns the raw voice resource (``voice_id``, ``name``,
        ``labels``, ``description``, ``samples``, ``preview_url``).
        """
        if not voice_id:
            raise ValueError("voice_id must be a non-empty string")
        return self._client.get(f"/v1/voices/{voice_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_models(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List TTS models available to the account.

        Returns compact summaries with a stable ``model_ref`` (``model_1``,
        ``model_2``, ...), display name, language support, and quality.
        The ElevenLabs ``model_id`` is included as ``model_name`` because
        callers need it for :meth:`text_to_speech`. Set
        ``include_ids=True`` for the raw ``model_id`` field. Default
        limit: 25.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        payload: object = self._client.get("/v1/models").json()
        models: list[object] = cast("list[object]", payload) if isinstance(payload, list) else []
        summaries: list[dict[str, Any]] = []
        for index, item in enumerate(models[:max_results], start=1):
            if not isinstance(item, dict):
                continue
            model: dict[str, Any] = cast("dict[str, Any]", item)
            raw_languages: object = model.get("languages", [])
            languages: list[object] = (
                cast("list[object]", raw_languages) if isinstance(raw_languages, list) else []
            )
            summary: dict[str, Any] = {
                "model_ref": f"model_{index}",
                "model_name": model.get("model_id", ""),
                "name": model.get("name", ""),
                "languages": [
                    cast("dict[str, Any]", lang).get("language_id", "")
                    for lang in languages
                    if isinstance(lang, dict)
                ],
                "can_do_text_to_speech": model.get("can_do_text_to_speech"),
                "can_use_style": model.get("can_use_style"),
            }
            if include_ids:
                summary["model_id"] = model.get("model_id", "")
            summaries.append(summary)
        return {"models": summaries, "total": len(models)}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self) -> dict[str, Any]:
        """Return account information.

        Returns ``{"subscription": {...}, "is_new_user": bool,
        "xi_api_key": ...}`` — useful for confirming the API key at
        startup.
        """
        return self._client.get("/v1/user").json()
