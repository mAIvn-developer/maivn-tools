"""dbt Cloud Administrative + Metadata API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Summary helpers


def _coerce_int_id(candidate: Any, *keys: str) -> int:
    """Coerce a value to an integer ID from a raw int/str, dict, or list of dicts."""
    if isinstance(candidate, int):
        return candidate
    if isinstance(candidate, str):
        try:
            return int(candidate)
        except ValueError as exc:
            raise ValueError(f"could not coerce {candidate!r} to int") from exc
    if isinstance(candidate, dict):
        mapping = cast(dict[Any, Any], candidate)
        for key in keys:
            value: Any = mapping.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    continue
        for nested in mapping.values():
            nested_value: Any = nested
            if isinstance(nested_value, dict | list):
                try:
                    return _coerce_int_id(nested_value, *keys)
                except ValueError:
                    continue
    if isinstance(candidate, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in sequence:
            item_value: Any = item
            try:
                return _coerce_int_id(item_value, *keys)
            except ValueError:
                continue
    type_name = type(cast(object, candidate)).__name__
    raise ValueError(f"could not extract an int ID from {type_name}")


def _summarize_project(project: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "project_ref": f"project_{index}",
        "name": project.get("name", ""),
        "state": project.get("state", ""),
        "created_at": project.get("created_at", ""),
    }
    if include_ids:
        summary["project_id"] = project.get("id", "")
    return summary


def _summarize_environment(
    environment: dict[str, Any], *, index: int, include_ids: bool
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "environment_ref": f"environment_{index}",
        "name": environment.get("name", ""),
        "type": environment.get("type", ""),
        "dbt_version": environment.get("dbt_version", ""),
        "deployment_type": environment.get("deployment_type", ""),
    }
    if include_ids:
        summary["environment_id"] = environment.get("id", "")
        summary["project_id"] = environment.get("project_id", "")
    return summary


def _summarize_job(job: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "job_ref": f"job_{index}",
        "name": job.get("name", ""),
        "environment": job.get("environment_id") if include_ids else None,
        "schedule": cast(dict[str, Any], job.get("schedule")).get("cron", "")
        if isinstance(job.get("schedule"), dict)
        else "",
        "generate_docs": job.get("generate_docs"),
        "triggers": job.get("triggers"),
        "execute_steps": job.get("execute_steps") or [],
    }
    if not include_ids:
        summary.pop("environment", None)
    if include_ids:
        summary["job_id"] = job.get("id", "")
        summary["project_id"] = job.get("project_id", "")
        summary["environment_id"] = job.get("environment_id", "")
    return summary


# MARK: Constants

# Numeric dbt Cloud run status codes -> human strings.
_RUN_STATUS: dict[int, str] = {
    1: "queued",
    2: "starting",
    3: "running",
    10: "success",
    20: "error",
    30: "cancelled",
}


def _summarize_run(run: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    status_code = run.get("status")
    status = (
        _RUN_STATUS.get(status_code, status_code) if isinstance(status_code, int) else status_code
    )
    summary: dict[str, Any] = {
        "run_ref": f"run_{index}",
        "status": status,
        "status_message": run.get("status_message") or "",
        "started_at": run.get("started_at", ""),
        "finished_at": run.get("finished_at", ""),
        "duration": run.get("duration_humanized") or run.get("duration", ""),
        "trigger_cause": cast(dict[str, Any], run.get("trigger")).get("cause", "")
        if isinstance(run.get("trigger"), dict)
        else "",
    }
    if include_ids:
        summary["run_id"] = run.get("id", "")
        summary["job_id"] = run.get("job_id", "")
        summary["project_id"] = run.get("project_id", "")
    return summary


# MARK: ToolSet


@toolset(prefix="dbt_cloud")
class DbtCloudToolSet:
    """A connector for the dbt Cloud Administrative API v2.

    Note that v2 is dbt's *legacy* Administrative API version with limited
    endpoints; dbt recommends v3 for new integrations. The project, job, run,
    and artifact routes used here remain available on v2.

    Args:
        account_id: dbt Cloud account ID.
        api_token: Service-account token or personal access token.
        host: API host (default ``"cloud.getdbt.com"``). Note that
            ``cloud.getdbt.com`` is the *legacy* access URL and dbt
            documents that it will be removed in the future. Cell-based /
            multi-tenant accounts use account-prefixed regional URLs (e.g.
            ``{account_prefix}.us1.dbt.com`` for US, ``emea.dbt.com`` for
            EMEA, ``au.dbt.com`` for APAC) and MUST pass ``host=`` with the
            access URL shown under dbt Cloud Account settings.
    """

    metadata = ProviderMetadata(
        name="dbt_cloud",
        display_name="dbt Cloud",
        version="0.1.0",
        description="Projects, jobs, runs, environments, and artifacts.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.getdbt.com/dbt-cloud/api-v2",
        homepage_url="https://www.getdbt.com/",
        tags=("etl", "analytics-engineering"),
    )

    def __init__(
        self,
        *,
        account_id: int,
        api_token: str,
        host: str = "cloud.getdbt.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not account_id or not api_token:
            raise ValueError("account_id and api_token are required")
        self.connection = connection
        self._account_id = account_id
        self._client = HttpClient(
            base_url=f"https://{host}",
            auth=ApiKeyAuth(api_token, header="Authorization", prefix="Token"),
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
    def list_projects(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List projects in the dbt Cloud account.

        Best first tool for project discovery. Returns compact summaries
        with ``project_ref``, name, state, and creation timestamp. Raw
        project IDs are omitted by default — set ``include_ids=True`` only
        when a follow-up tool (e.g. :meth:`list_jobs`) needs the raw
        ``project_id``. Pass ``raw=True`` for the unfiltered API response.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        payload: dict[str, Any] = self._client.get(
            f"/api/v2/accounts/{self._account_id}/projects/",
            params={"limit": limit, "offset": offset},
        ).json()
        if raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, project in enumerate(items, start=1):
            if isinstance(project, dict):
                project_dict = cast(dict[str, Any], project)
                summaries.append(
                    _summarize_project(project_dict, index=index, include_ids=include_ids)
                )
        return {"projects": summaries, "extra": payload.get("extra")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_project(self, project_id: Any) -> dict[str, Any]:
        """Return one project by ID.

        Returns the raw dbt Cloud project resource. ``project_id`` may be a
        raw integer ID or a project dict from :meth:`list_projects`
        (``include_ids=True``).
        """
        resolved_id = _coerce_int_id(project_id, "project_id", "id")
        if not resolved_id:
            raise ValueError("project_id is required")
        project: dict[str, Any] = self._client.get(
            f"/api/v2/accounts/{self._account_id}/projects/{resolved_id}/"
        ).json()
        return project

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_environments(
        self,
        *,
        project_id: int | None = None,
        limit: int = 25,
        offset: int = 0,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List environments (optionally narrowed by project).

        Returns compact summaries with ``environment_ref``, name, type
        (development/deployment), dbt version, and deployment type. Raw
        environment IDs are omitted by default — set ``include_ids=True``
        when a follow-up tool needs the raw ``environment_id``. Pass
        ``raw=True`` for the unfiltered API response.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if project_id is not None:
            params["project_id"] = project_id
        payload: dict[str, Any] = self._client.get(
            f"/api/v2/accounts/{self._account_id}/environments/",
            params=params,
        ).json()
        if raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, environment in enumerate(items, start=1):
            if isinstance(environment, dict):
                environment_dict = cast(dict[str, Any], environment)
                summaries.append(
                    _summarize_environment(environment_dict, index=index, include_ids=include_ids)
                )
        return {"environments": summaries, "extra": payload.get("extra")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_jobs(
        self,
        *,
        project_id: int | None = None,
        limit: int = 25,
        offset: int = 0,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List jobs (optionally filtered by project).

        Returns compact summaries with ``job_ref``, name, schedule (cron),
        whether docs are generated, triggers, and the steps that execute.
        Raw job IDs are omitted by default — set ``include_ids=True`` when
        a follow-up tool like :meth:`trigger_job_run` needs the raw
        ``job_id``. Pass ``raw=True`` for the unfiltered API response.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if project_id is not None:
            params["project_id"] = project_id
        payload: dict[str, Any] = self._client.get(
            f"/api/v2/accounts/{self._account_id}/jobs/", params=params
        ).json()
        if raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, job in enumerate(items, start=1):
            if isinstance(job, dict):
                job_dict = cast(dict[str, Any], job)
                summaries.append(_summarize_job(job_dict, index=index, include_ids=include_ids))
        return {"jobs": summaries, "extra": payload.get("extra")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_job(self, job_id: Any) -> dict[str, Any]:
        """Return one job's full configuration.

        Returns the raw dbt Cloud job resource. ``job_id`` may be a raw
        integer ID or a job dict from :meth:`list_jobs`
        (``include_ids=True``).
        """
        resolved_id = _coerce_int_id(job_id, "job_id", "id")
        if not resolved_id:
            raise ValueError("job_id is required")
        job: dict[str, Any] = self._client.get(
            f"/api/v2/accounts/{self._account_id}/jobs/{resolved_id}/"
        ).json()
        return job

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def trigger_job_run(
        self,
        job_id: Any,
        *,
        cause: str,
        git_branch: str | None = None,
        git_sha: str | None = None,
        schema_override: str | None = None,
        steps_override: list[str] | None = None,
    ) -> dict[str, Any]:
        """Trigger a job run.

        Returns the new run resource (with ``id``, ``status``, ``href``).
        ``job_id`` may be a raw integer or a job dict from
        :meth:`list_jobs` (``include_ids=True``). ``cause`` is required and
        is shown in the dbt Cloud UI run history.
        """
        resolved_id = _coerce_int_id(job_id, "job_id", "id")
        if not resolved_id or not cause:
            raise ValueError("job_id and cause are required")
        body: dict[str, Any] = {"cause": cause}
        if git_branch is not None:
            body["git_branch"] = git_branch
        if git_sha is not None:
            body["git_sha"] = git_sha
        if schema_override is not None:
            body["schema_override"] = schema_override
        if steps_override is not None:
            body["steps_override"] = steps_override
        run: dict[str, Any] = self._client.post(
            f"/api/v2/accounts/{self._account_id}/jobs/{resolved_id}/run/",
            json=body,
        ).json()
        return run

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_runs(
        self,
        *,
        job_definition_id: int | None = None,
        status: int | None = None,
        order_by: str = "-id",
        limit: int = 25,
        offset: int = 0,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List job runs (optionally filtered by job or status).

        Returns compact summaries with ``run_ref``, human-readable status
        (``queued``, ``starting``, ``running``, ``success``, ``error``,
        ``cancelled``), start/end timestamps, duration, and trigger cause.
        Raw run IDs are omitted by default — set ``include_ids=True`` when
        a follow-up tool like :meth:`cancel_run` or :meth:`list_run_artifacts`
        needs the raw ``run_id``. Pass ``raw=True`` for the unfiltered API
        response.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        params: dict[str, Any] = {
            "order_by": order_by,
            "limit": limit,
            "offset": offset,
        }
        if job_definition_id is not None:
            params["job_definition_id"] = job_definition_id
        if status is not None:
            params["status"] = status
        payload: dict[str, Any] = self._client.get(
            f"/api/v2/accounts/{self._account_id}/runs/", params=params
        ).json()
        if raw:
            return payload
        items: list[Any] = payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, run in enumerate(items, start=1):
            if isinstance(run, dict):
                run_dict = cast(dict[str, Any], run)
                summaries.append(_summarize_run(run_dict, index=index, include_ids=include_ids))
        return {"runs": summaries, "extra": payload.get("extra")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_run(
        self,
        run_id: Any,
        *,
        include_related: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return one run's full details.

        Returns the raw dbt Cloud run resource. ``run_id`` may be a raw
        integer ID or a run dict from :meth:`list_runs`
        (``include_ids=True``). ``include_related`` may carry e.g.
        ``["job"]`` to embed associated resources.
        """
        resolved_id = _coerce_int_id(run_id, "run_id", "id")
        if not resolved_id:
            raise ValueError("run_id is required")
        params: dict[str, Any] = {}
        if include_related is not None:
            params["include_related"] = ",".join(include_related)
        run: dict[str, Any] = self._client.get(
            f"/api/v2/accounts/{self._account_id}/runs/{resolved_id}/",
            params=params or None,
        ).json()
        return run

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def cancel_run(self, run_id: Any) -> dict[str, Any]:
        """Cancel a running job run. Destructive (the in-flight run is aborted).

        Returns the cancelled run resource. ``run_id`` may be a raw integer
        ID or a run dict from :meth:`list_runs` (``include_ids=True``).
        Confirm with the user before calling — any partial materializations
        may remain in the warehouse.
        """
        resolved_id = _coerce_int_id(run_id, "run_id", "id")
        if not resolved_id:
            raise ValueError("run_id is required")
        run: dict[str, Any] = self._client.post(
            f"/api/v2/accounts/{self._account_id}/runs/{resolved_id}/cancel/"
        ).json()
        return run

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_run_artifacts(self, run_id: Any) -> dict[str, Any]:
        """List artifacts (e.g. ``manifest.json``) produced by a run.

        Returns ``{"data": [<path>, ...]}``. Use :meth:`get_run_artifact` to
        fetch one. ``run_id`` accepts the same formats as :meth:`get_run`.
        """
        resolved_id = _coerce_int_id(run_id, "run_id", "id")
        if not resolved_id:
            raise ValueError("run_id is required")
        artifacts: dict[str, Any] = self._client.get(
            f"/api/v2/accounts/{self._account_id}/runs/{resolved_id}/artifacts/"
        ).json()
        return artifacts

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_run_artifact(self, *, run_id: Any, path: str) -> dict[str, Any]:
        """Fetch one artifact's content.

        Returns the parsed JSON content if available, else
        ``{"status": ..., "content": <raw text>}``. ``run_id`` accepts a
        raw integer or run dict; ``path`` is the artifact path from
        :meth:`list_run_artifacts`.
        """
        resolved_id = _coerce_int_id(run_id, "run_id", "id")
        if not resolved_id or not path:
            raise ValueError("run_id and path are required")
        response = self._client.get(
            f"/api/v2/accounts/{self._account_id}/runs/{resolved_id}/artifacts/{path}"
        )
        try:
            content: dict[str, Any] = response.json()
            return content
        except ValueError:
            return {"status": response.status, "content": response.text()}
