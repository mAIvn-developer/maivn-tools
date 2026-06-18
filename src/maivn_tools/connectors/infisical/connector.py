"""Infisical v3 REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_PROJECTS_OUTPUT, LIST_SECRETS_OUTPUT


@toolset(prefix="infisical")
class InfisicalToolSet:
    """A connector for the Infisical v3 REST API.

    Args:
        access_token: Service-token or machine-identity access token.
        base_url: API root (default ``"https://app.infisical.com"``, a
            working legacy alias for Infisical Cloud). For region-pinned
            Infisical Cloud, pass ``"https://us.infisical.com"`` or
            ``"https://eu.infisical.com"``; for self-hosted, pass your
            instance URL.
    """

    metadata = ProviderMetadata(
        name="infisical",
        display_name="Infisical",
        version="0.1.0",
        description="Projects, environments, secrets, and access tokens.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://infisical.com/docs/api-reference/overview",
        homepage_url="https://infisical.com/",
        tags=("security", "secrets"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        base_url: str = "https://app.infisical.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(access_token),
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
            "name": project.get("name", ""),
            "slug": project.get("slug", ""),
            "environments": [
                cast(dict[str, Any], env).get("slug", "") if isinstance(env, dict) else ""
                for env in cast(list[Any], project.get("environments", []))
                if env
            ],
        }
        if include_ids:
            summary["workspace_id"] = project.get("id", "")
        return summary

    @staticmethod
    def _secret_summary(
        secret: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        # CRITICAL: never include "secretValue" in the summary.
        summary: dict[str, Any] = {
            "secret_ref": f"secret_{index}",
            "key": secret.get("secretKey", "") or secret.get("key", ""),
            "type": secret.get("type", ""),
            "comment": secret.get("secretComment", ""),
            "updated_at": secret.get("updatedAt", ""),
        }
        if include_ids:
            summary["secret_id"] = secret.get("id", "")
            summary["secret_path"] = secret.get("secretPath", "")
        return summary

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_PROJECTS_OUTPUT)
    def list_projects(
        self,
        *,
        organization_id: str,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Infisical projects (workspaces) for an organization.

        Returns ``{"projects": [...]}`` with ``project_ref``, ``name``,
        ``slug``, and ``environments``. Raw ``workspace_id`` is omitted
        by default — set ``include_ids=True`` for follow-up tools that
        address a workspace.
        """
        if not organization_id:
            raise ValueError("organization_id is required")
        payload: object = self._client.get(
            f"/api/v2/organizations/{organization_id}/workspaces"
        ).json()
        raw_workspaces: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            workspaces_field: object = cast(dict[str, Any], payload).get("workspaces", [])
            if isinstance(workspaces_field, list):
                items = cast(list[Any], workspaces_field)
                raw_workspaces = [w for w in items if isinstance(w, dict)]
        elif isinstance(payload, list):
            raw_workspaces = [w for w in cast(list[Any], payload) if isinstance(w, dict)]
        summaries = [
            self._project_summary(workspace, index=index, include_ids=include_ids)
            for index, workspace in enumerate(raw_workspaces, start=1)
        ]
        return {"projects": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_project(self, workspace_id: str) -> dict[str, Any]:
        """Return one workspace.

        Returns the raw workspace resource (``id``, ``name``, ``slug``,
        ``environments``, ``createdAt``).
        """
        if not workspace_id:
            raise ValueError("workspace_id is required")
        return self._client.get(f"/api/v1/workspace/{workspace_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_SECRETS_OUTPUT)
    def list_secrets(
        self,
        *,
        workspace_id: str,
        environment: str,
        secret_path: str = "/",
        recursive: bool = False,
        include_ids: bool = False,
        include_values: bool = False,
    ) -> dict[str, Any]:
        """List secrets in an environment/path (metadata only by default).

        Returns ``{"secrets": [...]}`` with ``secret_ref``, ``key``,
        ``type``, ``comment``, ``updated_at``. NEVER returns secret
        values unless you opt in with ``include_values=True``. Use
        get_secret for a single targeted read.
        """
        if not workspace_id or not environment:
            raise ValueError("workspace_id and environment are required")
        payload: object = self._client.get(
            "/api/v3/secrets/raw",
            params={
                "workspaceId": workspace_id,
                "environment": environment,
                "secretPath": secret_path,
                "recursive": str(recursive).lower(),
            },
        ).json()
        if include_values:
            return cast(dict[str, Any], payload)
        raw_secrets: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            secrets_field: object = cast(dict[str, Any], payload).get("secrets", [])
            if isinstance(secrets_field, list):
                items = cast(list[Any], secrets_field)
                raw_secrets = [s for s in items if isinstance(s, dict)]
        summaries = [
            self._secret_summary(secret, index=index, include_ids=include_ids)
            for index, secret in enumerate(raw_secrets, start=1)
        ]
        return {
            "secrets": summaries,
            "workspace_id": workspace_id,
            "environment": environment,
            "secret_path": secret_path,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_secret(
        self,
        secret_name: str,
        *,
        workspace_id: str,
        environment: str,
        secret_path: str = "/",
        include_imports: bool = False,
    ) -> dict[str, Any]:
        """Return one secret by name (includes the value).

        Returns the raw Infisical secret payload. Treat as sensitive —
        do not echo into a final user-facing answer.
        """
        if not secret_name or not workspace_id or not environment:
            raise ValueError("secret_name, workspace_id, and environment are required")
        return self._client.get(
            f"/api/v3/secrets/raw/{secret_name}",
            params={
                "workspaceId": workspace_id,
                "environment": environment,
                "secretPath": secret_path,
                "include_imports": str(include_imports).lower(),
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_secret(
        self,
        secret_name: str,
        *,
        workspace_id: str,
        environment: str,
        secret_value: str,
        secret_path: str = "/",
        secret_comment: str | None = None,
    ) -> dict[str, Any]:
        """Create a secret.

        Returns the new secret resource. Confirm with the user before
        creating secrets that grant access to live systems.
        """
        if not secret_name or not workspace_id or not environment:
            raise ValueError(
                "secret_name, workspace_id, environment, and secret_value are required"
            )
        body: dict[str, Any] = {
            "workspaceId": workspace_id,
            "environment": environment,
            "secretPath": secret_path,
            "secretValue": secret_value,
        }
        if secret_comment is not None:
            body["secretComment"] = secret_comment
        return self._client.post(f"/api/v3/secrets/raw/{secret_name}", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_secret(
        self,
        secret_name: str,
        *,
        workspace_id: str,
        environment: str,
        secret_value: str,
        secret_path: str = "/",
    ) -> dict[str, Any]:
        """Update a secret's value.

        Returns the updated secret resource. Confirm with the user before
        rotating production secrets.
        """
        if not secret_name or not workspace_id or not environment:
            raise ValueError("secret_name, workspace_id, and environment are required")
        return self._client.patch(
            f"/api/v3/secrets/raw/{secret_name}",
            json={
                "workspaceId": workspace_id,
                "environment": environment,
                "secretPath": secret_path,
                "secretValue": secret_value,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_secret(
        self,
        secret_name: str,
        *,
        workspace_id: str,
        environment: str,
        secret_path: str = "/",
    ) -> dict[str, Any]:
        """Permanently delete a secret.

        Destructive and unrecoverable. Confirm with the user.
        """
        if not secret_name or not workspace_id or not environment:
            raise ValueError("secret_name, workspace_id, and environment are required")
        return self._client.delete(
            f"/api/v3/secrets/raw/{secret_name}",
            json={
                "workspaceId": workspace_id,
                "environment": environment,
                "secretPath": secret_path,
            },
        ).json()
