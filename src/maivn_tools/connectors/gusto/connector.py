"""Gusto Embedded Payroll REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

_API_VERSION = "2026-02-01"


@toolset(prefix="gusto")
class GustoToolSet:
    """A connector for Gusto's v1 REST API.

    Args:
        access_token: OAuth 2.0 access token.
        base_url: API root (default ``"https://api.gusto.com"``;
            demo: ``"https://api.gusto-demo.com"``).
    """

    metadata = ProviderMetadata(
        name="gusto",
        display_name="Gusto",
        version="0.1.0",
        description="Companies, employees, payrolls, pay schedules, and time off.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.gusto.com/embedded-payroll/reference",
        homepage_url="https://gusto.com/",
        tags=("hr", "payroll"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        base_url: str = "https://api.gusto.com",
        api_version: str = _API_VERSION,
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
                "X-Gusto-API-Version": api_version,
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Internal helpers

    @staticmethod
    def _employee_summary(
        employee: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        first = employee.get("first_name", "")
        last = employee.get("last_name", "")
        jobs: object = employee.get("jobs", [])
        primary_title: object = ""
        if isinstance(jobs, list) and jobs:
            jobs_list = cast("list[object]", jobs)
            first_raw = jobs_list[0]
            first_job: dict[str, Any] = (
                cast("dict[str, Any]", first_raw) if isinstance(first_raw, dict) else {}
            )
            primary_title = (first_job or {}).get("title", "")
        summary: dict[str, Any] = {
            "employee_ref": f"employee_{index}",
            "name": (employee.get("preferred_first_name") or f"{first} {last}").strip(),
            "email": employee.get("email", ""),
            "title": primary_title,
            "department": employee.get("department", "") or "",
            "hire_date": employee.get("current_employment_status_date", ""),
            "is_terminated": employee.get("terminated", False),
        }
        if include_ids:
            summary["employee_id"] = employee.get("uuid", "") or employee.get("id", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_companies(self) -> dict[str, Any]:
        """List companies the token can access.

        Gusto has no company-list endpoint; accessible companies are
        discovered from ``GET /v1/me``, which returns the current user
        with role buckets (``payroll_admin``, ``admin``, ``signatory``,
        ...), each carrying a ``companies`` array. Returns
        ``{"companies": [...]}`` where each entry has a ``uuid``. Use that
        ``uuid`` as ``company_uuid`` in other Gusto tools.
        """
        me: Any = self._client.get("/v1/me").json()
        roles: object = cast("dict[str, Any]", me).get("roles", {}) if isinstance(me, dict) else {}
        companies: list[dict[str, Any]] = []
        seen: set[str] = set()
        if isinstance(roles, dict):
            roles_dict = cast("dict[str, Any]", roles)
            for role in roles_dict.values():
                role_companies: object = (
                    cast("dict[str, Any]", role).get("companies", [])
                    if isinstance(role, dict)
                    else []
                )
                if not isinstance(role_companies, list):
                    continue
                companies_list = cast("list[object]", role_companies)
                for company in companies_list:
                    if not isinstance(company, dict):
                        continue
                    company_dict = cast("dict[str, Any]", company)
                    uuid: str = company_dict.get("uuid", "")
                    if uuid and uuid in seen:
                        continue
                    if uuid:
                        seen.add(uuid)
                    companies.append(company_dict)
        return {"companies": companies}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_company(self, company_uuid: str) -> dict[str, Any]:
        """Return one company by UUID.

        ``company_uuid`` is the raw Gusto company UUID.
        """
        if not company_uuid:
            raise ValueError("company_uuid is required")
        return self._client.get(f"/v1/companies/{company_uuid}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_employees(
        self,
        company_uuid: str,
        *,
        terminated: bool = False,
        page: int = 1,
        per: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List employees at a company.

        Best first tool for employee discovery. Returns compact summaries
        with ``employee_ref`` (``employee_1``, ``employee_2``, ...),
        name, email, primary job title, department, hire date, and
        termination state. Raw Gusto employee UUIDs are omitted unless
        ``include_ids=True``. ``per`` controls per-page size; pagination
        is via ``page``.
        """
        if not company_uuid:
            raise ValueError("company_uuid is required")
        payload: Any = self._client.get(
            f"/v1/companies/{company_uuid}/employees",
            params={
                "terminated": str(terminated).lower(),
                "page": page,
                "per": per,
            },
        ).json()
        if not isinstance(payload, list):
            return cast("dict[str, Any]", payload)
        payload_list = cast("list[object]", payload)
        summaries = [
            self._employee_summary(
                cast("dict[str, Any]", employee), index=index, include_ids=include_ids
            )
            for index, employee in enumerate(payload_list, start=1)
            if isinstance(employee, dict)
        ]
        return {"employees": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_employee(self, employee_uuid: str) -> dict[str, Any]:
        """Return one employee by UUID.

        ``employee_uuid`` is the raw Gusto employee UUID returned by
        ``list_employees(include_ids=True)``. The UUID is an internal
        handle and should not appear in final answers.
        """
        if not employee_uuid:
            raise ValueError("employee_uuid is required")
        return self._client.get(f"/v1/employees/{employee_uuid}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_employee(
        self,
        company_uuid: str,
        *,
        first_name: str,
        last_name: str,
        email: str,
    ) -> dict[str, Any]:
        """Create a new employee on a company.

        All four args are required. Confirm with the user before calling.
        """
        if not company_uuid or not first_name or not last_name or not email:
            raise ValueError("company_uuid, first_name, last_name, and email are required")
        return self._client.post(
            f"/v1/companies/{company_uuid}/employees",
            json={
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_payrolls(
        self,
        company_uuid: str,
        *,
        processing_statuses: list[str] | None = None,
        page: int = 1,
        per: int = 25,
    ) -> dict[str, Any]:
        """List payrolls for a company.

        Optionally filter by ``processing_statuses`` (e.g. ``["paid"]``).
        """
        if not company_uuid:
            raise ValueError("company_uuid is required")
        params: dict[str, Any] = {"page": page, "per": per}
        if processing_statuses is not None:
            params["processing_statuses"] = ",".join(processing_statuses)
        return self._client.get(f"/v1/companies/{company_uuid}/payrolls", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_payroll(
        self,
        *,
        company_uuid: str,
        payroll_uuid: str,
    ) -> dict[str, Any]:
        """Return one payroll by UUID.

        Both UUIDs are raw Gusto handles. Returns the full payroll
        resource with line items.
        """
        if not company_uuid or not payroll_uuid:
            raise ValueError("company_uuid and payroll_uuid are required")
        return self._client.get(f"/v1/companies/{company_uuid}/payrolls/{payroll_uuid}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_pay_schedules(self, company_uuid: str) -> dict[str, Any]:
        """List pay schedules for a company.

        Returns the raw Gusto pay-schedule list.
        """
        if not company_uuid:
            raise ValueError("company_uuid is required")
        return self._client.get(f"/v1/companies/{company_uuid}/pay_schedules").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_time_off_requests(
        self,
        company_uuid: str,
        *,
        status: str | None = None,
        page: int = 1,
        per: int = 25,
    ) -> dict[str, Any]:
        """List time-off requests for a company.

        Optionally filter by ``status`` (``pending``/``approved``/
        ``denied``).
        """
        if not company_uuid:
            raise ValueError("company_uuid is required")
        params: dict[str, Any] = {"page": page, "per": per}
        if status is not None:
            params["status"] = status
        return self._client.get(
            f"/v1/companies/{company_uuid}/time_off_requests",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_jobs(self, employee_uuid: str) -> dict[str, Any]:
        """List jobs for one employee.

        Returns the raw Gusto job list for that employee.
        """
        if not employee_uuid:
            raise ValueError("employee_uuid is required")
        return self._client.get(f"/v1/employees/{employee_uuid}/jobs").json()
