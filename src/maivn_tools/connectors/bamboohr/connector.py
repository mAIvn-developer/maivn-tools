"""BambooHR REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_EMPLOYEES_OUTPUT


@toolset(prefix="bamboohr")
class BambooHRToolSet:
    """A connector for the BambooHR v1 API.

    Args:
        subdomain: Company subdomain.
        api_key: BambooHR API key. Sent via Basic auth (key as username,
            literal ``x`` as password).
    """

    metadata = ProviderMetadata(
        name="bamboohr",
        display_name="BambooHR",
        version="0.1.0",
        description="Employees, time off, custom reports, and webhooks.",
        auth_modes=(AuthMode.BASIC,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://documentation.bamboohr.com/reference",
        homepage_url="https://www.bamboohr.com/",
        tags=("hr", "people-ops"),
    )

    def __init__(
        self,
        *,
        subdomain: str,
        api_key: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not subdomain or not api_key:
            raise ValueError("subdomain and api_key are required")
        self.connection = connection
        self._client = HttpClient(
            base_url=f"https://api.bamboohr.com/api/gateway.php/{subdomain}",
            auth=BasicAuth(api_key, "x"),
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
        display_name = (
            employee.get("displayName")
            or employee.get("preferredName")
            or f"{first} {last}".strip()
        )
        summary: dict[str, Any] = {
            "employee_ref": f"employee_{index}",
            "name": display_name,
            "email": employee.get("workEmail", "") or employee.get("bestEmail", ""),
            "title": employee.get("jobTitle", ""),
            "department": employee.get("department", ""),
            "hire_date": employee.get("hireDate", ""),
            "status": employee.get("status", ""),
        }
        if include_ids:
            summary["employee_id"] = employee.get("id", "")
        return summary

    @staticmethod
    def _select_employee_id(candidate: Any) -> int:
        """Accept an int, str ID, or a list/get dict (with ``employee_id``/``id``)."""
        if isinstance(candidate, bool):
            raise ValueError("employee_id must be a positive integer")
        if isinstance(candidate, int):
            if candidate <= 0:
                raise ValueError("employee_id must be a positive integer")
            return candidate
        if isinstance(candidate, str) and candidate:
            try:
                parsed = int(candidate)
            except ValueError as exc:
                raise ValueError(f"employee_id must be numeric, got {candidate!r}") from exc
            if parsed <= 0:
                raise ValueError("employee_id must be a positive integer")
            return parsed
        if isinstance(candidate, dict):
            mapping = cast(dict[str, Any], candidate)
            for key in ("employee_id", "id"):
                value = mapping.get(key)
                if value is not None:
                    return BambooHRToolSet._select_employee_id(value)
        if isinstance(candidate, list | tuple):
            sequence = cast("list[Any] | tuple[Any, ...]", candidate)
            for item in sequence:
                try:
                    return BambooHRToolSet._select_employee_id(item)
                except ValueError:
                    continue
        raise ValueError("employee_id is required")

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_EMPLOYEES_OUTPUT)
    def list_employees(
        self,
        *,
        limit: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List all employees in the directory.

        Best first tool for finding employees. Returns compact summaries
        with ``employee_ref`` (``employee_1``, ``employee_2``, ...),
        display name, work email, title, department, hire date, and
        status. Raw BambooHR employee IDs are omitted unless
        ``include_ids=True`` — they are internal handles needed only by
        follow-up tools like :meth:`get_employee` or :meth:`update_employee`.
        """
        raw_payload: Any = self._client.get("/v1/employees/directory").json()
        payload = cast(dict[str, Any], raw_payload) if isinstance(raw_payload, dict) else None
        employees: Any = payload.get("employees") if payload is not None else None
        if not isinstance(employees, list):
            return cast(dict[str, Any], raw_payload)
        employee_list = cast(list[Any], employees)
        limited: list[Any] = (
            employee_list[:limit] if limit and len(employee_list) > limit else employee_list
        )
        summaries = [
            self._employee_summary(
                cast(dict[str, Any], employee), index=index, include_ids=include_ids
            )
            for index, employee in enumerate(limited, start=1)
            if isinstance(employee, dict)
        ]
        return {
            "employees": summaries,
            "totalAvailable": len(employee_list),
            "fields": payload.get("fields") if payload is not None else None,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_employee(
        self,
        employee_id: int,
        *,
        fields: list[str],
    ) -> dict[str, Any]:
        """Return one employee with the selected ``fields``.

        ``employee_id`` is the raw BambooHR employee ID returned by
        ``list_employees(include_ids=True)``. The ID is an internal handle
        and should not appear in final answers. ``fields`` is the list of
        field names (e.g. ``["firstName", "lastName", "jobTitle"]``).
        """
        if not employee_id or not fields:
            raise ValueError("employee_id and fields are required")
        return self._client.get(
            f"/v1/employees/{employee_id}",
            params={"fields": ",".join(fields)},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_employee(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Create a new employee.

        ``fields`` must include at least ``firstName`` and ``lastName``.
        Confirm with the user before calling.
        """
        if not fields:
            raise ValueError("fields must be non-empty")
        return self._client.post("/v1/employees", json=fields).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_employee(
        self,
        employee_id: Any,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Update one employee's fields.

        ``employee_id`` accepts the raw integer ID, a string, or the dict
        returned by ``list_employees(include_ids=True)`` / ``get_employee``
        (the ``employee_id``/``id`` key is read). ``fields`` is the patch
        dict.
        """
        resolved = self._select_employee_id(employee_id)
        if not fields:
            raise ValueError("fields must be non-empty")
        return self._client.post(f"/v1/employees/{resolved}", json=fields).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_who_is_out(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        """Return who's-out time-off entries.

        ``start``/``end`` are ``YYYY-MM-DD``. Returns the list of
        approved time-off entries overlapping the range.
        """
        params: dict[str, Any] = {}
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        return self._client.get("/v1/time_off/whos_out/", params=params or None).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_time_off_requests(
        self,
        *,
        action: str | None = None,
        employee_id: int | None = None,
        start: str | None = None,
        end: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """List time-off requests.

        Filter by ``status`` (``approved``/``denied``/``superceded``/
        ``requested``), ``employee_id``, and a date range.
        """
        params: dict[str, Any] = {}
        if action is not None:
            params["action"] = action
        if employee_id is not None:
            params["employeeId"] = employee_id
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        if status is not None:
            params["status"] = status
        return self._client.get("/v1/time_off/requests/", params=params or None).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_time_off_request(
        self,
        *,
        employee_id: int,
        time_off_type_id: int,
        start: str,
        end: str,
        amount: float,
    ) -> dict[str, Any]:
        """Create a time-off request.

        ``time_off_type_id`` comes from :meth:`list_meta_time_off_types`.
        ``start``/``end`` are ``YYYY-MM-DD``. Confirm with the user before
        calling.
        """
        if not employee_id or not time_off_type_id or not start or not end:
            raise ValueError("employee_id, time_off_type_id, start, and end are required")
        return self._client.put(
            f"/v1/employees/{employee_id}/time_off/request",
            json={
                "timeOffTypeId": time_off_type_id,
                "start": start,
                "end": end,
                "amount": amount,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_custom_report(
        self,
        report_id: int,
        *,
        format: str = "JSON",
    ) -> dict[str, Any]:
        """Run a saved company report by ID.

        Fetches a previously-saved company report (``GET /v1/reports/{id}``),
        not the ad-hoc report builder (``POST /v1/reports/custom``).
        ``format`` is one of ``CSV``/``JSON``/``PDF``/``XLS``/``XML``.
        ``JSON`` returns parsed rows; other formats return
        ``{"status", "body"}``.
        """
        if not report_id:
            raise ValueError("report_id is required")
        if format not in {"CSV", "JSON", "PDF", "XLS", "XML"}:
            raise ValueError("invalid format")
        response = self._client.get(f"/v1/reports/{report_id}", params={"format": format})
        if format == "JSON":
            return response.json()
        return {"status": response.status, "body": response.text()}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_meta_fields(self) -> dict[str, Any]:
        """List available employee fields (metadata).

        Useful for picking the right ``fields=`` list for
        :meth:`get_employee`.
        """
        return self._client.get("/v1/meta/fields/").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_meta_time_off_types(self) -> dict[str, Any]:
        """List time-off types defined in the tenant.

        Use to pick the ``time_off_type_id`` for
        :meth:`create_time_off_request`.
        """
        return self._client.get("/v1/meta/time_off/types/").json()
