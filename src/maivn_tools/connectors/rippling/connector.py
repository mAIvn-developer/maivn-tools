"""Rippling Platform API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_EMPLOYEES_OUTPUT


@toolset(prefix="rippling")
class RipplingToolSet:
    """A connector for the Rippling Platform API.

    Args:
        access_token: OAuth access token.
        base_url: API root (default ``"https://api.rippling.com"``).
    """

    metadata = ProviderMetadata(
        name="rippling",
        display_name="Rippling",
        version="0.1.0",
        description="Employees, departments, work locations, leave, and groups.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.rippling.com/docs",
        homepage_url="https://www.rippling.com/",
        tags=("hr", "people-ops"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        base_url: str = "https://api.rippling.com",
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

    # MARK: - Internal helpers

    @staticmethod
    def _employee_summary(
        employee: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        first = employee.get("firstName", "")
        last = employee.get("lastName", "")
        name = (
            employee.get("preferredFirstName")
            or f"{first} {last}".strip()
            or employee.get("displayName", "")
        )
        raw_department: object = employee.get("department")
        department: dict[str, Any] = (
            cast("dict[str, Any]", raw_department) if isinstance(raw_department, dict) else {}
        )
        summary: dict[str, Any] = {
            "employee_ref": f"employee_{index}",
            "name": name,
            "email": employee.get("workEmail", "") or employee.get("personalEmail", ""),
            "title": employee.get("title", "") or employee.get("jobTitle", ""),
            "department": department.get("name", ""),
            "hire_date": employee.get("startDate", "") or employee.get("hireDate", ""),
            "status": employee.get("status", "") or employee.get("employmentStatus", ""),
        }
        if include_ids:
            summary["employee_id"] = employee.get("id", "") or employee.get("roleId", "")
        return summary

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_current_company(self) -> dict[str, Any]:
        """Return the company associated with the token.

        Use once at startup to confirm the token works.
        """
        return self._client.get("/platform/api/companies/current").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_EMPLOYEES_OUTPUT)
    def list_employees(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        status: str | None = None,
        employment_type: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List employees in the company.

        Best first tool for employee discovery. Returns compact summaries
        with ``employee_ref`` (``employee_1``, ``employee_2``, ...), name,
        work email, title, department, hire date, and status. Raw
        Rippling employee IDs are omitted unless ``include_ids=True`` —
        they are internal handles needed only by follow-up tools like
        :meth:`get_employee`.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status
        if employment_type is not None:
            params["employmentType"] = employment_type
        payload: object = self._client.get("/platform/api/employees", params=params).json()
        employees: list[Any] | None = (
            cast("list[Any]", payload) if isinstance(payload, list) else None
        )
        if employees is None and isinstance(payload, dict):
            payload_dict = cast("dict[str, Any]", payload)
            for key in ("employees", "data", "results"):
                value: object = payload_dict.get(key)
                if isinstance(value, list):
                    employees = cast("list[Any]", value)
                    break
        if employees is None and isinstance(payload, dict):
            return cast("dict[str, Any]", payload)
        if employees is None:
            return {"items": payload}
        summaries: list[dict[str, Any]] = [
            self._employee_summary(
                cast("dict[str, Any]", employee), index=index, include_ids=include_ids
            )
            for index, employee in enumerate(employees, start=1)
            if isinstance(employee, dict)
        ]
        return {
            "employees": summaries,
            "totalAvailable": len(employees),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_employee(self, employee_id: str) -> dict[str, Any]:
        """Return one employee by ID.

        ``employee_id`` is the raw Rippling employee ID returned by
        ``list_employees(include_ids=True)``. The ID is an internal handle
        and should not appear in final answers.
        """
        if not employee_id:
            raise ValueError("employee_id is required")
        return self._client.get(f"/platform/api/employees/{employee_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_departments(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List departments configured in the company.

        Returns the raw Rippling department list.
        """
        return self._client.get(
            "/platform/api/departments",
            params={"limit": limit, "offset": offset},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_work_locations(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List configured work locations.

        Returns the raw Rippling work-location list.
        """
        return self._client.get(
            "/platform/api/work_locations",
            params={"limit": limit, "offset": offset},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_groups(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List custom groups.

        Returns the raw Rippling group list.
        """
        return self._client.get(
            "/platform/api/groups",
            params={"limit": limit, "offset": offset},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_leave_requests(
        self,
        *,
        employee_id: str | None = None,
        status: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List leave requests.

        Optionally filter by ``employee_id`` and/or ``status``
        (``PENDING``/``APPROVED``/``REJECTED``).
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if employee_id is not None:
            params["role"] = employee_id
        if status is not None:
            params["status"] = status
        return self._client.get("/platform/api/leave_requests", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_compensations(self, employee_id: str) -> dict[str, Any]:
        """Return compensation for one employee.

        The native Rippling Platform API does not expose a standalone
        compensations collection — compensation is returned as fields on
        the employee object (subject to entitlement-based redaction). This
        reads the employee via ``GET /platform/api/employees/{id}``.
        ``employee_id`` is the raw Rippling employee ID returned by
        ``list_employees(include_ids=True)``.
        """
        if not employee_id:
            raise ValueError("employee_id is required")
        return self._client.get(f"/platform/api/employees/{employee_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_teams(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List teams in the company.

        Returns the raw Rippling team list.
        """
        return self._client.get(
            "/platform/api/teams",
            params={"limit": limit, "offset": offset},
        ).json()
