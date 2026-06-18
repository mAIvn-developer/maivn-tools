"""Hex API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_PROJECTS_OUTPUT


@toolset(prefix="hex")
class HexToolSet:
    """A connector for Hex's v1 REST API.

    Args:
        api_token: Hex personal access token.
    """

    metadata = ProviderMetadata(
        name="hex",
        display_name="Hex",
        version="0.1.0",
        description="Projects, runs, and embedded notebook execution.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://learn.hex.tech/docs/api/api-reference",
        homepage_url="https://hex.tech/",
        tags=("bi", "notebooks"),
    )

    def __init__(
        self,
        *,
        api_token: str,
        base_url: str = "https://app.hex.tech",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_token:
            raise ValueError("api_token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(api_token),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Internal helpers

    @staticmethod
    def _project_summary(
        project: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        raw_creator: Any = project.get("creator")
        creator: dict[str, Any] = (
            cast("dict[str, Any]", raw_creator) if isinstance(raw_creator, dict) else {}
        )
        summary: dict[str, Any] = {
            "project_ref": f"project_{index}",
            "title": project.get("title", ""),
            "description": project.get("description", "") or "",
            "creator_email": creator.get("email", ""),
            "last_edited_at": project.get("lastEditedAt", ""),
            "archived": project.get("archivedAt") is not None,
        }
        if include_ids:
            summary["project_id"] = project.get("id", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_PROJECTS_OUTPUT)
    def list_projects(
        self,
        *,
        limit: int = 25,
        after: str | None = None,
        include_archived: bool = False,
        include_trashed: bool = False,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Hex projects.

        Best first tool for project discovery. Returns compact summaries
        with ``project_ref`` (``project_1``, ``project_2``, ...), title,
        description, creator email, ``last_edited_at``, and archived
        state. Raw Hex project IDs are omitted unless ``include_ids=True``
        — they are internal handles. Set it only when a follow-up call
        (:meth:`get_project`, :meth:`run_project`) needs the raw ID.
        """
        params: dict[str, Any] = {
            "limit": limit,
            "includeArchived": str(include_archived).lower(),
            "includeTrashed": str(include_trashed).lower(),
        }
        if after is not None:
            params["after"] = after
        raw_payload: Any = self._client.get("/api/v1/projects", params=params).json()
        if not isinstance(raw_payload, dict):
            return cast("dict[str, Any]", raw_payload)
        payload = cast("dict[str, Any]", raw_payload)
        values: Any = payload.get("values")
        if not isinstance(values, list):
            return payload
        value_list = cast("list[Any]", values)
        summaries: list[dict[str, Any]] = [
            self._project_summary(
                cast("dict[str, Any]", project), index=index, include_ids=include_ids
            )
            for index, project in enumerate(value_list, start=1)
            if isinstance(project, dict)
        ]
        pagination: Any = payload.get("pagination")
        next_after: Any = (
            cast("dict[str, Any]", pagination).get("after")
            if isinstance(pagination, dict)
            else None
        )
        return {
            "projects": summaries,
            "nextAfter": next_after,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_project(self, project_id: str) -> dict[str, Any]:
        """Return one Hex project by ID.

        ``project_id`` is the raw Hex project ID returned by
        ``list_projects(include_ids=True)``. The ID is an internal handle
        and should not appear in final answers.
        """
        if not project_id:
            raise ValueError("project_id is required")
        return self._client.get(f"/api/v1/projects/{project_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def run_project(
        self,
        project_id: str,
        *,
        input_params: dict[str, Any] | None = None,
        update_published_results: bool = False,
        notifications: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Trigger a Hex project run.

        Returns the run resource with a ``runId`` that you can poll via
        :meth:`get_run_status`. Set ``update_published_results=True`` to
        publish the result of this run.
        """
        if not project_id:
            raise ValueError("project_id is required")
        body: dict[str, Any] = {
            "updatePublishedResults": update_published_results,
        }
        if input_params is not None:
            body["inputParams"] = input_params
        if notifications is not None:
            body["notifications"] = notifications
        return self._client.post(f"/api/v1/projects/{project_id}/runs", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_run_status(
        self,
        *,
        project_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        """Return one project run's status.

        Use after :meth:`run_project` to poll. Returns ``{"status": ...,
        "startTime": ..., "endTime": ..., ...}``.
        """
        if not project_id or not run_id:
            raise ValueError("project_id and run_id are required")
        return self._client.get(f"/api/v1/projects/{project_id}/runs/{run_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_project_runs(
        self,
        project_id: str,
        *,
        limit: int = 25,
        offset: int = 0,
        status_filter: str | None = None,
    ) -> dict[str, Any]:
        """List runs for a project.

        Returns the raw Hex run-list payload. Use ``status_filter`` to
        narrow by ``"OK"``, ``"ERRORED"``, ``"KILLED"``, etc.
        """
        if not project_id:
            raise ValueError("project_id is required")
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status_filter is not None:
            params["statusFilter"] = status_filter
        return self._client.get(f"/api/v1/projects/{project_id}/runs", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def cancel_run(
        self,
        *,
        project_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        """Cancel a running Hex project.

        Destructive — confirm with the user before calling. Returns
        ``{"run_id": ..., "cancelled": True, "status": <http_status>}``.
        """
        if not project_id or not run_id:
            raise ValueError("project_id and run_id are required")
        response = self._client.delete(f"/api/v1/projects/{project_id}/runs/{run_id}")
        return {"run_id": run_id, "cancelled": True, "status": response.status}
