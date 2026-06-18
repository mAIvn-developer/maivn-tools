"""Google BigQuery REST API v2 connector."""

# pyright: strict

from __future__ import annotations

import re
from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from ..google_workspace._shared import TokenSource, make_bearer_auth
from .output_schemas import LIST_DATASETS_OUTPUT, LIST_TABLES_OUTPUT

# MARK: - Constants

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|merge)\b",
    re.IGNORECASE,
)

# Smaller defaults keep agent context windows tidy. Callers can override.
_DEFAULT_LIST_LIMIT = 25
_DEFAULT_SAMPLE_LIMIT = 5
_DEFAULT_QUERY_LIMIT = 100


# MARK: - Helpers


def _validate_read_only_sql(sql: object) -> None:
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql must be a non-empty string")
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        raise ValueError("Compound statements are not allowed")
    first_word = stripped.split(None, 1)[0].lower()
    if first_word not in {"select", "with", "explain"}:
        raise ValueError("Only SELECT, WITH, and EXPLAIN statements are allowed")
    if _FORBIDDEN_KEYWORDS.search(stripped):
        raise ValueError("Query contains a forbidden mutation keyword")


_VALID_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def _validate_id(value: str, kind: str) -> None:
    if not value:
        raise ValueError(f"{kind} must be a non-empty string")
    if not _VALID_ID.match(value):
        raise ValueError(f"{kind} must match ^[A-Za-z_][A-Za-z0-9_-]*$")


def _dataset_summary(item: dict[str, Any], *, index: int) -> dict[str, Any]:
    """Build a compact summary of a BigQuery dataset list entry."""
    raw_reference = item.get("datasetReference")
    reference: dict[str, Any] = (
        cast("dict[str, Any]", raw_reference) if isinstance(raw_reference, dict) else {}
    )
    return {
        "dataset_ref": f"dataset_{index}",
        "dataset_id": reference.get("datasetId", ""),
        "project_id": reference.get("projectId", ""),
        "location": item.get("location", ""),
        "friendly_name": item.get("friendlyName", ""),
        "labels": item.get("labels") or {},
    }


def _table_summary(item: dict[str, Any], *, index: int) -> dict[str, Any]:
    """Build a compact summary of a BigQuery table list entry."""
    raw_reference = item.get("tableReference")
    reference: dict[str, Any] = (
        cast("dict[str, Any]", raw_reference) if isinstance(raw_reference, dict) else {}
    )
    return {
        "table_ref": f"table_{index}",
        "table_id": reference.get("tableId", ""),
        "dataset_id": reference.get("datasetId", ""),
        "project_id": reference.get("projectId", ""),
        "type": item.get("type", ""),
        "friendly_name": item.get("friendlyName", ""),
        "labels": item.get("labels") or {},
    }


# MARK: - Class


@toolset(prefix="bigquery")
class BigQueryToolSet:
    """A connector for the BigQuery REST API v2.

    Args:
        token: OAuth bearer token, ``OAuth2Token``, or callable provider with
            the ``https://www.googleapis.com/auth/bigquery`` scope.
        project_id: Default Google Cloud project ID.
        base_url: API root.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="bigquery",
        display_name="Google BigQuery",
        version="0.1.0",
        description="Run read-only BigQuery jobs and inspect datasets/tables.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE, AuthMode.SERVICE_ACCOUNT),
        scopes={
            "https://www.googleapis.com/auth/bigquery": "Full BigQuery access.",
            "https://www.googleapis.com/auth/bigquery.readonly": "Read-only access.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://cloud.google.com/bigquery/docs/reference/rest",
        homepage_url="https://cloud.google.com/bigquery",
        tags=("database", "warehouse", "google-cloud"),
    )

    def __init__(
        self,
        *,
        token: TokenSource,
        project_id: str,
        base_url: str = "https://bigquery.googleapis.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        _validate_id(project_id, "project_id")
        self.connection = connection
        self._project_id = project_id
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=make_bearer_auth(token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Datasets

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_DATASETS_OUTPUT)
    def list_datasets(
        self,
        *,
        all_datasets: bool = False,
        max_results: int = _DEFAULT_LIST_LIMIT,
        page_token: str | None = None,
        filter: str | None = None,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List datasets in the project.

        Best first tool for warehouse exploration. By default returns
        ``{"datasets", "nextPageToken"}`` where each dataset is a compact
        summary with ``dataset_ref``, the user-facing ``dataset_id``, the
        parent ``project_id``, ``location``, ``friendly_name``, and
        ``labels``. Pass ``dataset_id`` to :meth:`list_tables` or
        :meth:`get_dataset`.

        Set ``include_metadata=False`` to receive the raw BigQuery
        response untouched. Pagination is preserved via
        ``nextPageToken``.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        params: dict[str, Any] = {"maxResults": max_results}
        if all_datasets:
            params["all"] = "true"
        if page_token is not None:
            params["pageToken"] = page_token
        if filter is not None:
            params["filter"] = filter
        payload: dict[str, Any] = self._client.get(
            f"/bigquery/v2/projects/{self._project_id}/datasets",
            params=params,
        ).json()
        if not include_metadata:
            return payload
        raw_datasets = payload.get("datasets")
        datasets: list[Any] = (
            cast("list[Any]", raw_datasets) if isinstance(raw_datasets, list) else []
        )
        summaries = [
            _dataset_summary(cast("dict[str, Any]", item), index=index)
            for index, item in enumerate(datasets, start=1)
            if isinstance(item, dict)
        ]
        result: dict[str, Any] = {"datasets": summaries}
        next_page_token = payload.get("nextPageToken")
        if next_page_token:
            result["nextPageToken"] = next_page_token
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        """Return one dataset by ID.

        Returns the raw BigQuery dataset resource (``datasetReference``,
        ``access``, ``defaultTableExpirationMs``, ``labels``, ...). Use
        after :meth:`list_datasets` when you need the full metadata.
        """
        _validate_id(dataset_id, "dataset_id")
        return self._client.get(
            f"/bigquery/v2/projects/{self._project_id}/datasets/{dataset_id}",
        ).json()

    # MARK: - Tables

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_TABLES_OUTPUT)
    def list_tables(
        self,
        dataset_id: str,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
        page_token: str | None = None,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List tables in a dataset.

        Run after :meth:`list_datasets`. By default returns ``{"tables",
        "nextPageToken"}`` where each entry has ``table_ref``, the
        user-facing ``table_id``, parent ``dataset_id`` / ``project_id``,
        ``type`` (``"TABLE"``, ``"VIEW"``, ``"MATERIALIZED_VIEW"``,
        ``"EXTERNAL"``), ``friendly_name``, and ``labels``. Pass
        ``table_id`` to :meth:`get_table` or :meth:`get_table_data`.

        Set ``include_metadata=False`` to receive the raw BigQuery
        response.
        """
        _validate_id(dataset_id, "dataset_id")
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        params: dict[str, Any] = {"maxResults": max_results}
        if page_token is not None:
            params["pageToken"] = page_token
        payload: dict[str, Any] = self._client.get(
            f"/bigquery/v2/projects/{self._project_id}/datasets/{dataset_id}/tables",
            params=params,
        ).json()
        if not include_metadata:
            return payload
        raw_tables = payload.get("tables")
        tables: list[Any] = cast("list[Any]", raw_tables) if isinstance(raw_tables, list) else []
        summaries = [
            _table_summary(cast("dict[str, Any]", item), index=index)
            for index, item in enumerate(tables, start=1)
            if isinstance(item, dict)
        ]
        result: dict[str, Any] = {"tables": summaries}
        next_page_token = payload.get("nextPageToken")
        if next_page_token:
            result["nextPageToken"] = next_page_token
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_table(self, dataset_id: str, table_id: str) -> dict[str, Any]:
        """Return one table (schema, row count, size, etc.).

        Run after :meth:`list_tables` to understand a table before
        writing a query. Returns the raw BigQuery table resource —
        ``schema.fields`` carries the column definitions, ``numRows`` /
        ``numBytes`` describe size, ``type`` indicates table vs view.
        """
        _validate_id(dataset_id, "dataset_id")
        _validate_id(table_id, "table_id")
        return self._client.get(
            f"/bigquery/v2/projects/{self._project_id}/datasets/{dataset_id}/tables/{table_id}",
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_table_data(
        self,
        dataset_id: str,
        table_id: str,
        *,
        max_results: int = _DEFAULT_SAMPLE_LIMIT,
        start_index: str | None = None,
        page_token: str | None = None,
        selected_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return rows of a table (preview, no SQL required).

        Defaults to 5 rows so a quick sample stays cheap. Returns the
        raw BigQuery ``tabledata.list`` response — rows live under
        ``rows[*].f[*].v`` paired with the table's ``schema.fields``
        column names. For larger reads, use :meth:`run_query` with a
        ``SELECT ... LIMIT`` instead.
        """
        _validate_id(dataset_id, "dataset_id")
        _validate_id(table_id, "table_id")
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        params: dict[str, Any] = {"maxResults": max_results}
        if start_index is not None:
            params["startIndex"] = start_index
        if page_token is not None:
            params["pageToken"] = page_token
        if selected_fields is not None:
            params["selectedFields"] = ",".join(selected_fields)
        return self._client.get(
            f"/bigquery/v2/projects/{self._project_id}"
            f"/datasets/{dataset_id}/tables/{table_id}/data",
            params=params,
        ).json()

    # MARK: - Jobs

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def run_query(
        self,
        sql: str,
        *,
        location: str | None = None,
        max_results: int = _DEFAULT_QUERY_LIMIT,
        timeout_ms: int = 60000,
        use_legacy_sql: bool = False,
        dry_run: bool = False,
        parameters: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run a synchronous read-only query.

        Use this once :meth:`get_table` has clarified the schema. Returns
        the raw BigQuery ``queries`` response — rows live under
        ``rows[*].f[*].v`` paired with ``schema.fields`` column names.
        ``jobReference.jobId`` is the handle you would pass to
        :meth:`get_query_results` for paging or :meth:`cancel_job`.

        Args:
            sql: ``SELECT``/``WITH``/``EXPLAIN`` statement. Compound
                statements and mutation keywords are rejected.
            location: BigQuery region (e.g. ``"US"``, ``"EU"``). Required
                for non-US datasets.
            max_results: Page size cap. Defaults to 100 to keep agent
                context windows tidy; raise for analytical reads.
            timeout_ms: Synchronous wait. After this BigQuery returns
                ``jobComplete=false`` and the caller must poll with
                :meth:`get_query_results`.
            use_legacy_sql: Set to ``True`` only for the legacy SQL
                dialect.
            dry_run: When ``True``, BigQuery validates the query and
                returns cost estimates without executing it.
            parameters: Optional list of BigQuery
                ``queryParameters`` entries for parameterized SQL.
        """
        _validate_read_only_sql(sql)
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        body: dict[str, Any] = {
            "query": sql,
            "useLegacySql": use_legacy_sql,
            "timeoutMs": timeout_ms,
            "maxResults": max_results,
        }
        if location is not None:
            body["location"] = location
        if dry_run:
            body["dryRun"] = True
        if parameters is not None:
            body["queryParameters"] = parameters
        return self._client.post(
            f"/bigquery/v2/projects/{self._project_id}/queries",
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_query_results(
        self,
        job_id: str,
        *,
        location: str | None = None,
        page_token: str | None = None,
        max_results: int = _DEFAULT_QUERY_LIMIT,
        timeout_ms: int = 0,
    ) -> dict[str, Any]:
        """Fetch results for a previously submitted query job.

        Pass the ``job_id`` from a prior :meth:`run_query` response (it
        is under ``jobReference.jobId``). Use ``page_token`` to walk
        large result sets.
        """
        if not job_id:
            raise ValueError("job_id must be a non-empty string")
        params: dict[str, Any] = {
            "maxResults": max_results,
            "timeoutMs": timeout_ms,
        }
        if location is not None:
            params["location"] = location
        if page_token is not None:
            params["pageToken"] = page_token
        return self._client.get(
            f"/bigquery/v2/projects/{self._project_id}/queries/{job_id}",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_job(
        self,
        job_id: str,
        *,
        location: str | None = None,
    ) -> dict[str, Any]:
        """Return job status and metadata.

        Returns the raw BigQuery job resource — ``status.state``,
        ``statistics``, and ``configuration`` are typically what you
        need.
        """
        if not job_id:
            raise ValueError("job_id must be a non-empty string")
        params: dict[str, Any] = {}
        if location is not None:
            params["location"] = location
        return self._client.get(
            f"/bigquery/v2/projects/{self._project_id}/jobs/{job_id}",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_jobs(
        self,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
        all_users: bool = False,
        projection: str | None = None,
        state_filter: list[str] | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List recent jobs.

        Returns the raw BigQuery job-list response (``jobs``,
        ``nextPageToken``). Each job carries ``jobReference``,
        ``status``, and ``statistics``. ``state_filter`` accepts
        ``"running"``, ``"pending"``, ``"done"``.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        params: dict[str, Any] = {"maxResults": max_results}
        if all_users:
            params["allUsers"] = "true"
        if projection is not None:
            params["projection"] = projection
        if state_filter is not None:
            params["stateFilter"] = ",".join(state_filter)
        if page_token is not None:
            params["pageToken"] = page_token
        return self._client.get(
            f"/bigquery/v2/projects/{self._project_id}/jobs",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def cancel_job(self, job_id: str, *, location: str | None = None) -> dict[str, Any]:
        """Cancel a running job.

        Destructive: aborts the in-flight job. Confirm with the user
        before calling — partial output (e.g. INSERT into a destination
        table from a long load) may be left behind.
        """
        if not job_id:
            raise ValueError("job_id must be a non-empty string")
        params: dict[str, Any] = {}
        if location is not None:
            params["location"] = location
        return self._client.post(
            f"/bigquery/v2/projects/{self._project_id}/jobs/{job_id}/cancel",
            params=params or None,
        ).json()

    # MARK: - Routines & models (read-only inspection)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_routines(
        self,
        dataset_id: str,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List routines (functions / procedures) in a dataset.

        Returns the raw BigQuery response: ``{"routines": [...],
        "nextPageToken": ...}``. Each routine carries
        ``routineReference``, ``routineType`` (``"SCALAR_FUNCTION"`` /
        ``"PROCEDURE"`` / etc.), and ``language``.
        """
        _validate_id(dataset_id, "dataset_id")
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        params: dict[str, Any] = {"maxResults": max_results}
        if page_token is not None:
            params["pageToken"] = page_token
        return self._client.get(
            f"/bigquery/v2/projects/{self._project_id}/datasets/{dataset_id}/routines",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_models(
        self,
        dataset_id: str,
        *,
        max_results: int = _DEFAULT_LIST_LIMIT,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List BigQuery ML models in a dataset.

        Returns the raw BigQuery response: ``{"models": [...],
        "nextPageToken": ...}``. Each model carries ``modelReference``
        and ``modelType``.
        """
        _validate_id(dataset_id, "dataset_id")
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        params: dict[str, Any] = {"maxResults": max_results}
        if page_token is not None:
            params["pageToken"] = page_token
        return self._client.get(
            f"/bigquery/v2/projects/{self._project_id}/datasets/{dataset_id}/models",
            params=params,
        ).json()
