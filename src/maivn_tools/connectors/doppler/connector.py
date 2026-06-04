"""Doppler v3 REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="doppler")
class DopplerToolSet:
    """A connector for the Doppler v3 REST API.

    Args:
        token: Service token or workplace token.
    """

    metadata = ProviderMetadata(
        name="doppler",
        display_name="Doppler",
        version="0.1.0",
        description="Workplaces, projects, configs, secrets, and downloads.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.doppler.com/reference/api",
        homepage_url="https://www.doppler.com/",
        tags=("security", "secrets"),
    )

    def __init__(
        self,
        *,
        token: str,
        base_url: str = "https://api.doppler.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not token:
            raise ValueError("token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(token),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Summary helpers

    @staticmethod
    def _project_summary(
        project: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "project_ref": f"project_{index}",
            "name": project.get("name", "") or project.get("slug", ""),
            "description": project.get("description", ""),
            "created_at": project.get("created_at", ""),
        }
        if include_ids:
            summary["project_slug"] = project.get("slug", "") or project.get("id", "")
        return summary

    @staticmethod
    def _config_summary(
        config: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "config_ref": f"config_{index}",
            "name": config.get("name", ""),
            "environment": config.get("environment", ""),
            "root": bool(config.get("root", False)),
            "locked": bool(config.get("locked", False)),
        }
        if include_ids:
            summary["config_slug"] = config.get("name", "")
        return summary

    @staticmethod
    def _summarize_secrets(secrets_payload: Any) -> list[dict[str, Any]]:
        """Strip secret values; keep only key + type metadata."""
        if not isinstance(secrets_payload, dict):
            return []
        secrets_map = cast(dict[str, Any], secrets_payload)
        summaries: list[dict[str, Any]] = []
        for index, (key, info) in enumerate(secrets_map.items(), start=1):
            entry: dict[str, Any] = {
                "secret_ref": f"secret_{index}",
                "key": key,
            }
            if isinstance(info, dict):
                info_map = cast(dict[str, Any], info)
                # Doppler's response carries computed/raw values; never include them.
                value_kind: Any = info_map.get("type") or info_map.get("computedValueType")
                if isinstance(value_kind, dict):
                    entry["value_type"] = cast(dict[str, Any], value_kind).get("type", "")
                elif isinstance(value_kind, str):
                    entry["value_type"] = value_kind
                note: Any = info_map.get("note")
                if isinstance(note, str) and note:
                    entry["note"] = note
            summaries.append(entry)
        return summaries

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_projects(
        self,
        *,
        page: int = 1,
        per_page: int = 20,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Doppler projects.

        Returns ``{"projects": [...]}`` with ``project_ref``, ``name``,
        ``description``, ``created_at``. Raw ``project_slug`` is omitted
        by default — set ``include_ids=True`` when a follow-up tool needs
        the slug to address the project.
        """
        payload: Any = self._client.get(
            "/v3/projects",
            params={"page": page, "per_page": per_page},
        ).json()
        raw_projects: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            projects_field: Any = cast(dict[str, Any], payload).get("projects", [])
            if isinstance(projects_field, list):
                raw_projects = [
                    cast(dict[str, Any], p)
                    for p in cast(list[Any], projects_field)
                    if isinstance(p, dict)
                ]
        summaries = [
            self._project_summary(project, index=index, include_ids=include_ids)
            for index, project in enumerate(raw_projects, start=1)
        ]
        result: dict[str, Any] = {"projects": summaries}
        if isinstance(payload, dict) and "page" in payload:
            result["page"] = payload["page"]
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_project(
        self,
        *,
        name: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a Doppler project."""
        if not name:
            raise ValueError("name is required")
        body: dict[str, Any] = {"name": name}
        if description is not None:
            body["description"] = description
        return self._client.post("/v3/projects", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_project(self, project: str) -> dict[str, Any]:
        """Permanently delete a project (and all its configs + secrets).

        Destructive and unrecoverable. Confirm with the user before
        calling.
        """
        if not project:
            raise ValueError("project is required")
        return self._client.delete("/v3/projects/project", json={"project": project}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_configs(
        self,
        *,
        project: str,
        environment: str | None = None,
        page: int = 1,
        per_page: int = 20,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List configs in a project.

        Returns ``{"configs": [...]}`` with ``config_ref``, ``name``,
        ``environment``, ``root``, ``locked``.
        """
        if not project:
            raise ValueError("project is required")
        params: dict[str, Any] = {
            "project": project,
            "page": page,
            "per_page": per_page,
        }
        if environment is not None:
            params["environment"] = environment
        payload: Any = self._client.get("/v3/configs", params=params).json()
        raw_configs: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            configs_field: Any = cast(dict[str, Any], payload).get("configs", [])
            if isinstance(configs_field, list):
                raw_configs = [
                    cast(dict[str, Any], c)
                    for c in cast(list[Any], configs_field)
                    if isinstance(c, dict)
                ]
        summaries = [
            self._config_summary(config, index=index, include_ids=include_ids)
            for index, config in enumerate(raw_configs, start=1)
        ]
        return {"configs": summaries, "project": project}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_secrets(
        self,
        *,
        project: str,
        config: str,
        include_managed_secrets: bool = True,
        include_dynamic_secrets: bool = True,
        include_values: bool = False,
    ) -> dict[str, Any]:
        """List secrets in a config (metadata only by default).

        Returns ``{"secrets": [...]}`` with ``secret_ref``, ``key``, and
        (when available) ``value_type``/``note``. NEVER returns secret
        values unless you opt in with ``include_values=True`` (which is
        an explicit, intentional choice — treat the result as sensitive).
        Use get_secret for a single targeted read.
        """
        if not project or not config:
            raise ValueError("project and config are required")
        payload: Any = self._client.get(
            "/v3/configs/config/secrets",
            params={
                "project": project,
                "config": config,
                "include_managed_secrets": str(include_managed_secrets).lower(),
                "include_dynamic_secrets": str(include_dynamic_secrets).lower(),
            },
        ).json()
        if include_values:
            return payload
        secrets_field: Any = (
            cast(dict[str, Any], payload).get("secrets") if isinstance(payload, dict) else None
        )
        return {
            "secrets": self._summarize_secrets(secrets_field),
            "project": project,
            "config": config,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_secret(
        self,
        *,
        project: str,
        config: str,
        name: str,
    ) -> dict[str, Any]:
        """Fetch a single secret's value.

        Returns the raw Doppler payload with the ``value`` block. Treat
        as sensitive — do not echo into a final user-facing answer.
        """
        if not project or not config or not name:
            raise ValueError("project, config, and name are required")
        return self._client.get(
            "/v3/configs/config/secret",
            params={"project": project, "config": config, "name": name},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_secrets(
        self,
        *,
        project: str,
        config: str,
        secrets: dict[str, str | None],
    ) -> dict[str, Any]:
        """Bulk update secrets (``None`` deletes a key).

        Returns the Doppler response. Confirm with the user before
        rotating production secrets.
        """
        if not project or not config or not secrets:
            raise ValueError("project, config, and secrets are required")
        return self._client.post(
            "/v3/configs/config/secrets",
            json={
                "project": project,
                "config": config,
                "secrets": secrets,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def download_secrets(
        self,
        *,
        project: str,
        config: str,
        format: str = "json",
    ) -> dict[str, Any]:
        """Download all secret values for a config (sensitive).

        Returns the raw Doppler payload in the requested format. Treat as
        sensitive — do not echo into a final user-facing answer.
        """
        if not project or not config:
            raise ValueError("project and config are required")
        if format not in {"json", "env", "docker", "yaml", "env-no-quotes"}:
            raise ValueError("format must be json/env/docker/yaml/env-no-quotes")
        return self._client.get(
            "/v3/configs/config/secrets/download",
            params={"project": project, "config": config, "format": format},
        ).json()
