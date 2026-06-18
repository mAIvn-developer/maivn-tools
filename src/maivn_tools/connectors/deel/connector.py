"""Deel REST API connector."""
# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_CONTRACTS_OUTPUT, LIST_PEOPLE_OUTPUT


@toolset(prefix="deel")
class DeelToolSet:
    """A connector for the Deel REST API.

    Args:
        api_token: Bearer token.
        base_url: API root (default ``"https://api.letsdeel.com"``).
    """

    metadata = ProviderMetadata(
        name="deel",
        display_name="Deel",
        version="0.1.0",
        description="People, contracts, invoices, time off, and payroll.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.deel.com/docs",
        homepage_url="https://www.deel.com/",
        tags=("hr", "people-ops", "global-payroll"),
    )

    def __init__(
        self,
        *,
        api_token: str,
        base_url: str = "https://api.letsdeel.com",
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
    def _person_summary(
        person: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        first = person.get("first_name", "")
        last = person.get("last_name", "")
        name = (person.get("full_name") or f"{first} {last}").strip()
        emails_raw: object = person.get("emails", [])
        emails: list[Any] = cast("list[Any]", emails_raw) if isinstance(emails_raw, list) else []
        primary_email = ""
        if emails:
            first_email: Any = emails[0]
            if isinstance(first_email, dict):
                first_email_dict = cast("dict[str, Any]", first_email)
                value = first_email_dict.get("value", "")
                primary_email = value if isinstance(value, str) else ""
            elif isinstance(first_email, str):
                primary_email = first_email
        summary: dict[str, Any] = {
            "employee_ref": f"employee_{index}",
            "name": name,
            "email": primary_email or person.get("email", "") or person.get("work_email", ""),
            "title": person.get("job_title", "") or person.get("title", ""),
            "department": person.get("department", "") or "",
            "hiring_status": person.get("hiring_status", ""),
            "hiring_type": person.get("hiring_type", ""),
            "start_date": person.get("start_date", "") or person.get("hire_date", ""),
        }
        if include_ids:
            summary["person_id"] = person.get("id", "")
        return summary

    @staticmethod
    def _contract_summary(
        contract: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        worker_raw: object = contract.get("worker")
        worker: dict[str, Any] = (
            cast("dict[str, Any]", worker_raw) if isinstance(worker_raw, dict) else {}
        )
        summary: dict[str, Any] = {
            "contract_ref": f"contract_{index}",
            "title": contract.get("title", "") or contract.get("job_title", ""),
            "type": contract.get("type", "") or contract.get("contract_type", ""),
            "status": contract.get("status", ""),
            "worker_name": worker.get("full_name", ""),
            "country": contract.get("country", "") or contract.get("country_code", ""),
            "start_date": contract.get("start_date", ""),
        }
        if include_ids:
            summary["contract_id"] = contract.get("id", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_PEOPLE_OUTPUT)
    def list_people(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        hiring_types: list[str] | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List people in the org.

        Best first tool for finding employees/contractors. Returns compact
        summaries with ``employee_ref`` (``employee_1``, ``employee_2``,
        ...), name, primary email, title, department, hiring status, and
        start date. Raw Deel person IDs are omitted unless
        ``include_ids=True`` — they are internal handles needed only by
        follow-up tools like :meth:`get_person`.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if hiring_types is not None:
            params["hiring_types"] = ",".join(hiring_types)
        raw: object = self._client.get("/rest/v2/people", params=params).json()
        payload: dict[str, Any] = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
        data: object = payload.get("data")
        if not isinstance(data, list):
            return cast("dict[str, Any]", raw)
        data_list = cast("list[Any]", data)
        summaries = [
            self._person_summary(
                cast("dict[str, Any]", person), index=index, include_ids=include_ids
            )
            for index, person in enumerate(data_list, start=1)
            if isinstance(person, dict)
        ]
        return {
            "employees": summaries,
            "page": payload.get("page"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_person(self, person_id: str) -> dict[str, Any]:
        """Return one person by ID.

        ``person_id`` is the raw Deel person ID returned by
        ``list_people(include_ids=True)``. The ID is an internal handle
        and should not appear in final answers.
        """
        if not person_id:
            raise ValueError("person_id is required")
        return self._client.get(f"/rest/v2/people/{person_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_CONTRACTS_OUTPUT)
    def list_contracts(
        self,
        *,
        types: list[str] | None = None,
        statuses: list[str] | None = None,
        limit: int = 25,
        offset: int = 0,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List contracts.

        Returns compact summaries with ``contract_ref`` (``contract_1``,
        ``contract_2``, ...), title, type, status, worker name, country,
        and start date. Raw Deel contract IDs are omitted unless
        ``include_ids=True``.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if types is not None:
            params["types"] = ",".join(types)
        if statuses is not None:
            params["statuses"] = ",".join(statuses)
        raw: object = self._client.get("/rest/v2/contracts", params=params).json()
        payload: dict[str, Any] = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
        data: object = payload.get("data")
        if not isinstance(data, list):
            return cast("dict[str, Any]", raw)
        data_list = cast("list[Any]", data)
        summaries = [
            self._contract_summary(
                cast("dict[str, Any]", contract), index=index, include_ids=include_ids
            )
            for index, contract in enumerate(data_list, start=1)
            if isinstance(contract, dict)
        ]
        return {
            "contracts": summaries,
            "page": payload.get("page"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_contract(self, contract_id: str) -> dict[str, Any]:
        """Return one contract by ID.

        ``contract_id`` is the raw Deel contract ID. The ID is an
        internal handle and should not appear in final answers.
        """
        if not contract_id:
            raise ValueError("contract_id is required")
        return self._client.get(f"/rest/v2/contracts/{contract_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_invoice_adjustment(
        self,
        contract_id: str,
        *,
        amount: float,
        date_submission: str,
        description: str,
        adjustment_type: str = "bonus",
    ) -> dict[str, Any]:
        """Add an invoice adjustment to a contract.

        Use to add a one-off bonus/deduction/expense. ``date_submission``
        is ``YYYY-MM-DD``. Confirm with the user before calling.
        """
        if not contract_id or not amount or not date_submission or not description:
            raise ValueError("contract_id, amount, date_submission, and description are required")
        return self._client.post(
            "/rest/v2/invoice-adjustments",
            json={
                "contract_id": contract_id,
                "amount": amount,
                "date_submission": date_submission,
                "description": description,
                "type": adjustment_type,
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_invoice_adjustments(
        self,
        *,
        contract_id: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List invoice adjustments.

        Optionally filter by ``contract_id``. Returns the raw Deel
        adjustment list payload.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if contract_id is not None:
            params["contract_id"] = contract_id
        return self._client.get("/rest/v2/invoice-adjustments", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_time_off(
        self,
        hris_profile_id: str,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List time-off requests for a worker.

        Deel exposes time-off as a profile-scoped resource:
        ``GET /rest/v2/time_offs/profile/{hris_profile_id}``. Pass the
        worker's ``hris_profile_id``. Returns the raw Deel time-off list
        payload.
        """
        if not hris_profile_id:
            raise ValueError("hris_profile_id is required")
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        return self._client.get(
            f"/rest/v2/time_offs/profile/{hris_profile_id}",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def review_time_off(
        self,
        time_off_id: str,
        *,
        approve: bool,
    ) -> dict[str, Any]:
        """Approve or reject a time-off request.

        Deel reviews time-off via the batch endpoint
        ``POST /rest/v2/time_offs/review`` (token scope ``time-off:write``).
        Set ``approve=True`` to approve (status ``APPROVED``) or
        ``approve=False`` to reject (status ``REJECTED``).
        """
        if not time_off_id:
            raise ValueError("time_off_id is required")
        status = "APPROVED" if approve else "REJECTED"
        return self._client.post(
            "/rest/v2/time_offs/review",
            json={"data": {"ids": [time_off_id], "status": status}},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_payroll_events(
        self,
        legal_entity_id: str,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List global-payroll events for a legal entity.

        Deel exposes global-payroll events as
        ``GET /rest/v2/gp/legal-entities/{legal_entity_id}/reports``.
        Pass the ``legal_entity_id`` (see :meth:`list_legal_entities`).
        Returns the raw Deel payroll-event list payload.
        """
        if not legal_entity_id:
            raise ValueError("legal_entity_id is required")
        return self._client.get(
            f"/rest/v2/gp/legal-entities/{legal_entity_id}/reports",
            params={"limit": limit, "offset": offset},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_legal_entities(self) -> dict[str, Any]:
        """List org legal entities.

        Returns the raw Deel legal-entity list.
        """
        return self._client.get("/rest/v2/legal-entities").json()
