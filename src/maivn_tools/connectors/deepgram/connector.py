"""Deepgram API connector."""

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


@toolset(prefix="deepgram")
class DeepgramToolSet:
    """A connector for the Deepgram API."""

    metadata = ProviderMetadata(
        name="deepgram",
        display_name="Deepgram",
        version="0.1.0",
        description="Pre-recorded and live speech-to-text, plus TTS.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developers.deepgram.com/reference",
        homepage_url="https://deepgram.com/",
        tags=("ai", "audio"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepgram.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="Authorization", prefix="Token"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def transcribe_url(
        self,
        *,
        audio_url: str,
        model: str = "nova-2",
        language: str | None = None,
        smart_format: bool = True,
        diarize: bool = False,
        punctuate: bool = True,
    ) -> dict[str, Any]:
        """Transcribe a remote audio URL.

        Returns the raw Deepgram transcript response. The transcript text
        is under ``results.channels[0].alternatives[0].transcript``.
        """
        if not audio_url:
            raise ValueError("audio_url must be a non-empty string")
        params: dict[str, Any] = {
            "model": model,
            "smart_format": str(smart_format).lower(),
            "diarize": str(diarize).lower(),
            "punctuate": str(punctuate).lower(),
        }
        if language is not None:
            params["language"] = language
        return self._client.post(
            "/v1/listen",
            params=params,
            json={"url": audio_url},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def transcribe_bytes(
        self,
        *,
        audio_bytes: bytes,
        mime_type: str,
        model: str = "nova-2",
        language: str | None = None,
        smart_format: bool = True,
    ) -> dict[str, Any]:
        """Transcribe raw audio bytes.

        Returns the raw Deepgram transcript response. ``mime_type`` is the
        Content-Type for the audio (e.g. ``"audio/wav"``).
        """
        if not audio_bytes or not mime_type:
            raise ValueError("audio_bytes and mime_type must be non-empty")
        params: dict[str, Any] = {"model": model, "smart_format": str(smart_format).lower()}
        if language is not None:
            params["language"] = language
        return self._client.post(
            "/v1/listen",
            params=params,
            data=audio_bytes,
            headers={"Content-Type": mime_type},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def speak(
        self,
        *,
        text: str,
        model: str = "aura-asteria-en",
        encoding: str = "mp3",
    ) -> dict[str, Any]:
        """Text-to-speech.

        Returns ``{"status": int, "body": <audio bytes>}`` in the chosen
        ``encoding`` (e.g. ``mp3``, ``wav``).
        """
        if not text:
            raise ValueError("text must be a non-empty string")
        response = self._client.post(
            "/v1/speak",
            params={"model": model, "encoding": encoding},
            json={"text": text},
        )
        return {"status": response.status, "body": response.body}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_projects(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List projects on the account.

        Returns compact summaries with a stable ``project_ref``
        (``project_1``, ``project_2``, ...), display name, and company.
        Raw ``project_id`` values are omitted by default — they are
        internal handles. Set ``include_ids=True`` only when a follow-up
        Deepgram tool needs the raw ID. Default limit: 25.
        """
        if max_results < 1:
            raise ValueError("max_results must be positive")
        payload: Any = self._client.get("/v1/projects").json()
        payload_dict: dict[str, Any] = (
            cast("dict[str, Any]", payload) if isinstance(payload, dict) else {}
        )
        raw_projects: Any = payload_dict.get("projects", [])
        projects: list[Any] = (
            cast("list[Any]", raw_projects) if isinstance(raw_projects, list) else []
        )
        summaries: list[dict[str, Any]] = []
        for index, project in enumerate(projects[:max_results], start=1):
            if not isinstance(project, dict):
                continue
            project_dict: dict[str, Any] = cast("dict[str, Any]", project)
            summary: dict[str, Any] = {
                "project_ref": f"project_{index}",
                "name": project_dict.get("name", ""),
                "company": project_dict.get("company", ""),
            }
            if include_ids:
                summary["project_id"] = project_dict.get("project_id", "")
            summaries.append(summary)
        return {"projects": summaries, "total": len(projects)}
