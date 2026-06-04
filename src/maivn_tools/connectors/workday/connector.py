"""Workday REST API connector (Common + Staffing + Talent endpoints)."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: - Constants

# Workday publishes each REST service at its own version under
# /ccx/api/{service}/{version}/{tenant}. There is no single shared version:
# Recruiting is v4 (v1 does not exist), Staffing is at a higher current
# version, while Absence Management and Common are still on v1.
_SERVICE_VERSIONS: dict[str, str] = {
    "recruiting": "v4",
    "staffing": "v6",
    "common": "v1",
    "absenceManagement": "v1",
}
_DEFAULT_SERVICE_VERSION = "v1"


@toolset(prefix="workday")
class WorkdayToolSet:
    """A connector for Workday's REST APIs.

    Args:
        tenant_url: Tenant root URL, e.g.
            ``"https://wd2-impl-services1.workday.com/ccx"``.
        tenant: Tenant name.
        access_token: OAuth 2.0 access token issued by Workday Identity
            (the connector does not handle the token exchange).
    """

    metadata = ProviderMetadata(
        name="workday",
        display_name="Workday",
        version="0.1.0",
        description="Workers, jobs, time off, organizations, and recruiting.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://community.workday.com/api",
        homepage_url="https://www.workday.com/",
        tags=("hr", "people-ops"),
    )

    def __init__(
        self,
        *,
        tenant_url: str,
        tenant: str,
        access_token: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not tenant_url or not tenant or not access_token:
            raise ValueError("tenant_url, tenant, and access_token are required")
        self.connection = connection
        self._tenant = tenant
        self._client = HttpClient(
            base_url=tenant_url.rstrip("/"),
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

    def _path(self, service: str, suffix: str) -> str:
        version = _SERVICE_VERSIONS.get(service, _DEFAULT_SERVICE_VERSION)
        return f"/api/{service}/{version}/{self._tenant}{suffix}"

    # MARK: - Internal helpers

    @staticmethod
    def _worker_summary(
        worker: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        descriptor: Any = worker.get("descriptor") or worker.get("name") or ""
        raw_primary_job: Any = worker.get("primaryJob")
        primary_job: dict[str, Any] = (
            cast(dict[str, Any], raw_primary_job) if isinstance(raw_primary_job, dict) else {}
        )
        summary: dict[str, Any] = {
            "worker_ref": f"worker_{index}",
            "name": descriptor,
            "email": worker.get("primaryWorkEmail", "") or worker.get("workEmail", ""),
            "title": primary_job.get("descriptor", ""),
            "hire_date": worker.get("hireDate", "") or worker.get("originalHireDate", ""),
            "is_active": worker.get("active", True),
        }
        if include_ids:
            summary["worker_id"] = worker.get("id", "")
        return summary

    @staticmethod
    def _candidate_summary(
        candidate: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        descriptor = candidate.get("descriptor") or candidate.get("name") or ""
        summary: dict[str, Any] = {
            "candidate_ref": f"candidate_{index}",
            "name": descriptor,
            "email": candidate.get("email", ""),
            "status": candidate.get("status", "") or "",
            "application_date": candidate.get("applicationDate", ""),
        }
        if include_ids:
            summary["candidate_id"] = candidate.get("id", "")
        return summary

    @staticmethod
    def _job_posting_summary(
        posting: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        descriptor = posting.get("descriptor") or posting.get("title") or ""
        summary: dict[str, Any] = {
            "job_ref": f"job_{index}",
            "title": descriptor,
            "location": posting.get("location", "") or "",
            "posted_at": posting.get("postingDate", ""),
            "status": posting.get("status", ""),
        }
        if include_ids:
            summary["job_id"] = posting.get("id", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_workers(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        search: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List workers via the staffing service.

        Best first tool for finding employees. Returns compact summaries
        with ``worker_ref`` (``worker_1``, ``worker_2``, ...), name,
        email, title, hire date, and active state. Raw Workday worker IDs
        are omitted unless ``include_ids=True`` — they are internal
        handles. Pagination is via ``offset``/``limit``.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if search is not None:
            params["search"] = search
        payload: dict[str, Any] = self._client.get(
            self._path("staffing", "/workers"), params=params
        ).json()
        data: Any = payload.get("data")
        if not isinstance(data, list):
            return payload
        items: list[Any] = cast(list[Any], data)
        summaries = [
            self._worker_summary(cast(dict[str, Any], worker), index=index, include_ids=include_ids)
            for index, worker in enumerate(items, start=1)
            if isinstance(worker, dict)
        ]
        return {
            "workers": summaries,
            "total": payload.get("total"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_worker(self, worker_id: str) -> dict[str, Any]:
        """Return one worker by ID.

        ``worker_id`` is the raw Workday worker WID returned by
        ``list_workers(include_ids=True)``. The WID is an internal handle
        and should not appear in final answers.
        """
        if not worker_id:
            raise ValueError("worker_id is required")
        return self._client.get(self._path("staffing", f"/workers/{worker_id}")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_organizations(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List supervisory organizations.

        Returns the raw Workday organization list. Use to find the
        ``supervisoryOrganization`` IDs needed by other Workday
        operations.
        """
        return self._client.get(
            self._path("common", "/organizations"),
            params={"limit": limit, "offset": offset},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_job_changes(
        self,
        *,
        worker_id: str,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List job changes for one worker.

        ``worker_id`` is the raw Workday worker WID. Returns the worker's
        position history.
        """
        if not worker_id:
            raise ValueError("worker_id is required")
        return self._client.get(
            self._path("staffing", f"/workers/{worker_id}/jobChanges"),
            params={"limit": limit, "offset": offset},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_time_off_balances(self, worker_id: str) -> dict[str, Any]:
        """List a worker's time-off balances.

        Returns the available leave per balance type.
        """
        if not worker_id:
            raise ValueError("worker_id is required")
        return self._client.get(
            self._path(
                "absenceManagement",
                f"/workers/{worker_id}/timeOffBalances",
            )
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def submit_time_off(
        self,
        worker_id: str,
        *,
        entries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Submit a time-off request for a worker.

        ``entries`` is a list of day-level entries (each typically has
        ``date``, ``hours``, and ``timeOffType``). Confirm with the user
        before calling.
        """
        if not worker_id or not entries:
            raise ValueError("worker_id and entries are required")
        return self._client.post(
            self._path(
                "absenceManagement",
                f"/workers/{worker_id}/requestTimeOff",
            ),
            json={"entries": entries},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_positions(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List positions (open or filled) defined in Workday.

        Returns the raw position list.
        """
        return self._client.get(
            self._path("staffing", "/positions"),
            params={"limit": limit, "offset": offset},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_job_postings(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List external job postings.

        Returns compact summaries with ``job_ref``, title, location,
        posted date, and status. Raw Workday job IDs are omitted unless
        ``include_ids=True``.
        """
        payload: dict[str, Any] = self._client.get(
            self._path("recruiting", "/jobPostings"),
            params={"limit": limit, "offset": offset},
        ).json()
        data: Any = payload.get("data")
        if not isinstance(data, list):
            return payload
        items: list[Any] = cast(list[Any], data)
        summaries = [
            self._job_posting_summary(
                cast(dict[str, Any], posting), index=index, include_ids=include_ids
            )
            for index, posting in enumerate(items, start=1)
            if isinstance(posting, dict)
        ]
        return {
            "jobs": summaries,
            "total": payload.get("total"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_candidates(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List recruiting candidates.

        Returns compact summaries with ``candidate_ref``, name, email,
        status, and application date. Raw Workday candidate IDs are
        omitted unless ``include_ids=True``.
        """
        payload: dict[str, Any] = self._client.get(
            self._path("recruiting", "/candidates"),
            params={"limit": limit, "offset": offset},
        ).json()
        data: Any = payload.get("data")
        if not isinstance(data, list):
            return payload
        items: list[Any] = cast(list[Any], data)
        summaries = [
            self._candidate_summary(
                cast(dict[str, Any], candidate), index=index, include_ids=include_ids
            )
            for index, candidate in enumerate(items, start=1)
            if isinstance(candidate, dict)
        ]
        return {
            "candidates": summaries,
            "total": payload.get("total"),
        }
