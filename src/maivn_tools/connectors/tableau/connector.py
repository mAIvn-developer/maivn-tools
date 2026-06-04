"""Tableau Server / Cloud REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

_API_VERSION = "3.24"


@toolset(prefix="tableau")
class TableauToolSet:
    """A connector for Tableau Server / Cloud REST API.

    Args:
        server_url: Tableau server URL (e.g.
            ``"https://us-east-1.online.tableau.com"``).
        site_id: Site UUID returned from a sign-in response.
        auth_token: ``X-Tableau-Auth`` token (returned by sign-in).
        api_version: REST API version (default ``"3.24"``).

    Sign-in (personal access token / username+password) is left to the
    caller; supply ``auth_token`` + ``site_id`` already exchanged.
    """

    metadata = ProviderMetadata(
        name="tableau",
        display_name="Tableau",
        version="0.1.0",
        description="Workbooks, views, datasources, projects, and refresh jobs.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url=("https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api.htm"),
        homepage_url="https://www.tableau.com/",
        tags=("bi", "analytics"),
    )

    def __init__(
        self,
        *,
        server_url: str,
        site_id: str,
        auth_token: str,
        api_version: str = _API_VERSION,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not server_url or not site_id or not auth_token:
            raise ValueError("server_url, site_id, and auth_token are required")
        self.connection = connection
        self._site_id = site_id
        self._api_version = api_version
        self._client = HttpClient(
            base_url=server_url.rstrip("/"),
            auth=ApiKeyAuth(auth_token, header="X-Tableau-Auth"),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _site_path(self, suffix: str) -> str:
        return f"/api/{self._api_version}/sites/{self._site_id}{suffix}"

    # MARK: - Internal helpers

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
            "description": project.get("description", "") or "",
            "content_permissions": project.get("contentPermissions", ""),
        }
        if include_ids:
            summary["project_id"] = project.get("id", "")
        return summary

    @staticmethod
    def _nested_name(record: dict[str, Any], field: str) -> Any:
        """Return ``record[field]["name"]`` when ``field`` is a dict, else ``""``."""
        nested: Any = record.get(field)
        if isinstance(nested, dict):
            nested_dict = cast("dict[str, Any]", nested)
            return nested_dict.get("name", "")
        return ""

    @staticmethod
    def _workbook_summary(
        workbook: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "workbook_ref": f"workbook_{index}",
            "name": workbook.get("name", ""),
            "description": workbook.get("description", "") or "",
            "owner_name": TableauToolSet._nested_name(workbook, "owner"),
            "project_name": TableauToolSet._nested_name(workbook, "project"),
            "updated_at": workbook.get("updatedAt", ""),
        }
        if include_ids:
            summary["workbook_id"] = workbook.get("id", "")
        return summary

    @staticmethod
    def _view_summary(
        view: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "view_ref": f"view_{index}",
            "name": view.get("name", ""),
            "content_url": view.get("contentUrl", ""),
            "view_url_name": view.get("viewUrlName", ""),
        }
        if include_ids:
            summary["view_id"] = view.get("id", "")
        return summary

    @staticmethod
    def _datasource_summary(
        datasource: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "datasource_ref": f"datasource_{index}",
            "name": datasource.get("name", ""),
            "type": datasource.get("type", ""),
            "owner_name": TableauToolSet._nested_name(datasource, "owner"),
            "project_name": TableauToolSet._nested_name(datasource, "project"),
            "updated_at": datasource.get("updatedAt", ""),
        }
        if include_ids:
            summary["datasource_id"] = datasource.get("id", "")
        return summary

    @staticmethod
    def _extract_records(
        payload: dict[str, Any],
        *,
        container_key: str,
        item_key: str,
    ) -> list[Any] | None:
        """Pull ``payload[container_key][item_key]`` as a list, else ``None``.

        Returns ``None`` when the nested shape is not a list so callers can
        fall back to returning the raw payload.
        """
        container: object = payload.get(container_key) or {}
        if not isinstance(container, dict):
            return []
        container_dict = cast("dict[str, Any]", container)
        items: Any = container_dict.get(item_key, [])
        if not isinstance(items, list):
            return None
        return cast("list[Any]", items)

    @staticmethod
    def _select_id(
        candidate: Any,
        *,
        key: str,
    ) -> str:
        """Accept a raw ID string or a list/get dict (with the matching key)."""
        if isinstance(candidate, str):
            return candidate
        if isinstance(candidate, dict):
            mapping = cast("dict[str, Any]", candidate)
            for prefer in (key, "id"):
                value: Any = mapping.get(prefer)
                if isinstance(value, str) and value:
                    return value
        if isinstance(candidate, (list, tuple)):
            items = cast("list[Any] | tuple[Any, ...]", candidate)
            for item in items:
                resolved = TableauToolSet._select_id(item, key=key)
                if resolved:
                    return resolved
        raise ValueError(f"could not resolve {key} from input")

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_server_info(self) -> dict[str, Any]:
        """Return Tableau Server version info.

        Use to validate the connection and discover supported API version.
        """
        result: dict[str, Any] = self._client.get(f"/api/{self._api_version}/serverinfo").json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_sites(
        self,
        *,
        page_size: int = 25,
        page_number: int = 1,
    ) -> dict[str, Any]:
        """List sites the authenticated user can access.

        Returns the raw Tableau pagination payload.
        """
        result: dict[str, Any] = self._client.get(
            f"/api/{self._api_version}/sites",
            params={"pageSize": page_size, "pageNumber": page_number},
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_projects(
        self,
        *,
        page_size: int = 25,
        page_number: int = 1,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List projects in the active site.

        Returns compact summaries with ``project_ref``, name, description,
        and ``content_permissions``. Raw Tableau project IDs are omitted
        unless ``include_ids=True``.
        """
        payload: dict[str, Any] = self._client.get(
            self._site_path("/projects"),
            params={"pageSize": page_size, "pageNumber": page_number},
        ).json()
        records = self._extract_records(payload, container_key="projects", item_key="project")
        if records is None:
            return payload
        summaries = [
            self._project_summary(
                cast("dict[str, Any]", project), index=index, include_ids=include_ids
            )
            for index, project in enumerate(records, start=1)
            if isinstance(project, dict)
        ]
        return {
            "projects": summaries,
            "pagination": payload.get("pagination"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_workbooks(
        self,
        *,
        page_size: int = 25,
        page_number: int = 1,
        filter: str | None = None,
        sort: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List workbooks in the active site.

        Best first tool for workbook discovery. Returns compact summaries
        with ``workbook_ref``, name, description, owner name, project
        name, and ``updated_at``. Raw Tableau workbook IDs are omitted
        unless ``include_ids=True``; set it only when a follow-up tool
        like :meth:`get_workbook`, :meth:`refresh_workbook`, or
        :meth:`delete_workbook` needs the raw ID. Pagination from
        ``page_number`` is preserved.
        """
        params: dict[str, Any] = {
            "pageSize": page_size,
            "pageNumber": page_number,
        }
        if filter is not None:
            params["filter"] = filter
        if sort is not None:
            params["sort"] = sort
        payload: dict[str, Any] = self._client.get(
            self._site_path("/workbooks"), params=params
        ).json()
        records = self._extract_records(payload, container_key="workbooks", item_key="workbook")
        if records is None:
            return payload
        summaries = [
            self._workbook_summary(
                cast("dict[str, Any]", workbook), index=index, include_ids=include_ids
            )
            for index, workbook in enumerate(records, start=1)
            if isinstance(workbook, dict)
        ]
        return {
            "workbooks": summaries,
            "pagination": payload.get("pagination"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_workbook(self, workbook_id: str) -> dict[str, Any]:
        """Return one workbook by ID.

        ``workbook_id`` is the raw Tableau workbook UUID returned by
        ``list_workbooks(include_ids=True)``. The UUID is an internal
        handle and should not appear in final answers.
        """
        if not workbook_id:
            raise ValueError("workbook_id is required")
        result: dict[str, Any] = self._client.get(
            self._site_path(f"/workbooks/{workbook_id}")
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_views_for_workbook(
        self,
        workbook_id: str,
        *,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List views inside a workbook.

        Returns compact summaries with ``view_ref``, name, ``content_url``,
        and ``view_url_name``. Raw view IDs are omitted unless
        ``include_ids=True``; set it only when a follow-up
        :meth:`query_view_data` call needs the view ID.
        """
        if not workbook_id:
            raise ValueError("workbook_id is required")
        payload: dict[str, Any] = self._client.get(
            self._site_path(f"/workbooks/{workbook_id}/views")
        ).json()
        records = self._extract_records(payload, container_key="views", item_key="view")
        if records is None:
            return payload
        summaries = [
            self._view_summary(cast("dict[str, Any]", view), index=index, include_ids=include_ids)
            for index, view in enumerate(records, start=1)
            if isinstance(view, dict)
        ]
        return {"views": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def query_view_data(
        self,
        view_id: str,
        *,
        format: str = "csv",
        max_age: int | None = None,
    ) -> dict[str, Any]:
        """Query a view's data (CSV / Excel / PDF / Image).

        ``view_id`` is the raw Tableau view UUID. ``max_age`` lets Tableau
        return cached results. Returns ``{"status", "format", "body"}``.
        """
        if not view_id:
            raise ValueError("view_id is required")
        if format not in {"csv", "data", "excel", "image", "pdf"}:
            raise ValueError("invalid format")
        # Tableau's view-export path suffixes differ from the friendly format
        # names: CSV data is served at ``/data`` and Excel as ``/crosstab/excel``.
        suffix = {"csv": "data", "data": "data", "excel": "crosstab/excel"}.get(format, format)
        params: dict[str, Any] = {}
        if max_age is not None:
            params["maxAge"] = max_age
        response = self._client.get(
            self._site_path(f"/views/{view_id}/{suffix}"),
            params=params or None,
        )
        return {
            "status": response.status,
            "format": format,
            "body": response.text(),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_datasources(
        self,
        *,
        page_size: int = 25,
        page_number: int = 1,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List published datasources in the active site.

        Returns compact summaries with ``datasource_ref``, name, type,
        owner name, project name, and ``updated_at``. Raw datasource IDs
        are omitted unless ``include_ids=True``.
        """
        payload: dict[str, Any] = self._client.get(
            self._site_path("/datasources"),
            params={"pageSize": page_size, "pageNumber": page_number},
        ).json()
        records = self._extract_records(payload, container_key="datasources", item_key="datasource")
        if records is None:
            return payload
        summaries = [
            self._datasource_summary(
                cast("dict[str, Any]", datasource), index=index, include_ids=include_ids
            )
            for index, datasource in enumerate(records, start=1)
            if isinstance(datasource, dict)
        ]
        return {
            "datasources": summaries,
            "pagination": payload.get("pagination"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def refresh_datasource(self, datasource_id: str) -> dict[str, Any]:
        """Trigger an extract refresh on a datasource.

        Returns the new background job resource. Poll :meth:`get_job`
        to track completion.
        """
        if not datasource_id:
            raise ValueError("datasource_id is required")
        result: dict[str, Any] = self._client.post(
            self._site_path(f"/datasources/{datasource_id}/refresh"),
            json={},
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def refresh_workbook(self, workbook_id: str) -> dict[str, Any]:
        """Trigger an extract refresh on a workbook.

        Returns the new background job resource. Poll :meth:`get_job` to
        track completion.
        """
        if not workbook_id:
            raise ValueError("workbook_id is required")
        result: dict[str, Any] = self._client.post(
            self._site_path(f"/workbooks/{workbook_id}/refresh"),
            json={},
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_job(self, job_id: str) -> dict[str, Any]:
        """Return one background job (e.g. a refresh).

        Use this after :meth:`refresh_workbook` or :meth:`refresh_datasource`
        to track progress.
        """
        if not job_id:
            raise ValueError("job_id is required")
        result: dict[str, Any] = self._client.get(self._site_path(f"/jobs/{job_id}")).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_workbook(self, workbook_id: Any) -> dict[str, Any]:
        """Delete a workbook (irreversible).

        Destructive — confirm with the user before calling. Accepts the
        raw workbook UUID, or the dict returned by ``list_workbooks
        (include_ids=True)`` / ``get_workbook`` (the ``workbook_id``/``id``
        key is read).
        """
        resolved = self._select_id(workbook_id, key="workbook_id")
        if not resolved:
            raise ValueError("workbook_id is required")
        response = self._client.delete(self._site_path(f"/workbooks/{resolved}"))
        return {
            "workbook_id": resolved,
            "deleted": True,
            "status": response.status,
        }
