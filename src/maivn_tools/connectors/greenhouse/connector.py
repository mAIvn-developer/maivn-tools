"""Greenhouse Harvest API connector (ATS)."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_CANDIDATES_OUTPUT, LIST_JOBS_OUTPUT


@toolset(prefix="greenhouse")
class GreenhouseToolSet:
    """A connector for Greenhouse Harvest.

    Args:
        api_key: Harvest API key (sent as Basic auth username with an
            empty password).
        on_behalf_of: User ID for on-behalf-of write operations.
    """

    metadata = ProviderMetadata(
        name="greenhouse",
        display_name="Greenhouse",
        version="0.1.0",
        description="Jobs, candidates, applications, scorecards, and offers.",
        auth_modes=(AuthMode.BASIC,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developers.greenhouse.io/harvest.html",
        homepage_url="https://www.greenhouse.io/",
        tags=("hr", "ats", "recruiting"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        on_behalf_of: str | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._on_behalf_of = on_behalf_of
        self._client = HttpClient(
            base_url="https://harvest.greenhouse.io",
            auth=BasicAuth(api_key, ""),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _write_headers(self) -> dict[str, str]:
        if not self._on_behalf_of:
            raise ValueError("on_behalf_of must be set in the constructor for this call")
        return {"On-Behalf-Of": self._on_behalf_of}

    # MARK: - Internal helpers

    @staticmethod
    def _job_summary(
        job: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        offices: object = job.get("offices", [])
        office_names: list[str] = []
        if isinstance(offices, list):
            offices_list = cast("list[Any]", offices)
            office_names = [
                str(cast("dict[str, Any]", office).get("name", ""))
                for office in offices_list
                if isinstance(office, dict)
            ]
        summary: dict[str, Any] = {
            "job_ref": f"job_{index}",
            "name": job.get("name", ""),
            "status": job.get("status", ""),
            "office_names": office_names,
            "opened_at": job.get("opened_at", ""),
            "closed_at": job.get("closed_at", ""),
        }
        if include_ids:
            summary["job_id"] = job.get("id", "")
        return summary

    @staticmethod
    def _candidate_summary(
        candidate: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        emails: object = candidate.get("email_addresses", [])
        primary_email = ""
        if isinstance(emails, list) and emails:
            emails_list = cast("list[Any]", emails)
            first_email: dict[str, Any] = (
                cast("dict[str, Any]", emails_list[0]) if isinstance(emails_list[0], dict) else {}
            )
            primary_email = str(first_email.get("value", ""))
        summary: dict[str, Any] = {
            "candidate_ref": f"candidate_{index}",
            "name": (
                candidate.get("first_name", "") + " " + candidate.get("last_name", "")
            ).strip(),
            "email": primary_email,
            "title": candidate.get("title", "") or "",
            "company": candidate.get("company", "") or "",
            "application_date": candidate.get("application_date", "")
            or candidate.get("created_at", ""),
        }
        if include_ids:
            summary["candidate_id"] = candidate.get("id", "")
        return summary

    @staticmethod
    def _select_application_id(candidate: Any) -> int:
        if isinstance(candidate, bool):
            raise ValueError("application_id must be a positive integer")
        if isinstance(candidate, int):
            if candidate <= 0:
                raise ValueError("application_id must be a positive integer")
            return candidate
        if isinstance(candidate, str) and candidate:
            try:
                parsed = int(candidate)
            except ValueError as exc:
                raise ValueError(f"application_id must be numeric, got {candidate!r}") from exc
            if parsed <= 0:
                raise ValueError("application_id must be a positive integer")
            return parsed
        if isinstance(candidate, dict):
            candidate_dict = cast("dict[str, Any]", candidate)
            for key in ("application_id", "id"):
                value: object = candidate_dict.get(key)
                if value is not None:
                    return GreenhouseToolSet._select_application_id(value)
        if isinstance(candidate, list | tuple):
            candidate_seq = cast("list[Any] | tuple[Any, ...]", candidate)
            for item in candidate_seq:
                try:
                    return GreenhouseToolSet._select_application_id(item)
                except ValueError:
                    continue
        raise ValueError("application_id is required")

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_JOBS_OUTPUT)
    def list_jobs(
        self,
        *,
        status: str | None = None,
        per_page: int = 25,
        page: int = 1,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List jobs in Greenhouse.

        Best first tool for job discovery. Returns compact summaries with
        ``job_ref`` (``job_1``, ``job_2``, ...), name, status, office
        names, opened/closed dates. Raw Greenhouse job IDs are omitted
        unless ``include_ids=True`` — they are internal handles needed
        only by follow-up tools.
        """
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        if status is not None:
            params["status"] = status
        payload: object = self._client.get("/v1/jobs", params=params).json()
        if not isinstance(payload, list):
            return cast("dict[str, Any]", payload)
        payload_list = cast("list[Any]", payload)
        summaries = [
            self._job_summary(cast("dict[str, Any]", job), index=index, include_ids=include_ids)
            for index, job in enumerate(payload_list, start=1)
            if isinstance(job, dict)
        ]
        return {"jobs": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_job(self, job_id: int) -> dict[str, Any]:
        """Return one job by ID.

        ``job_id`` is the raw Greenhouse job ID returned by
        ``list_jobs(include_ids=True)``. The ID is an internal handle and
        should not appear in final answers.
        """
        if not job_id:
            raise ValueError("job_id is required")
        return self._client.get(f"/v1/jobs/{job_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_CANDIDATES_OUTPUT)
    def list_candidates(
        self,
        *,
        email: str | None = None,
        updated_after: str | None = None,
        job_id: int | None = None,
        per_page: int = 25,
        page: int = 1,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List candidates.

        Best first tool for candidate discovery. Returns compact summaries
        with ``candidate_ref`` (``candidate_1``, ``candidate_2``, ...),
        full name, primary email, current title, current company, and
        application date. Raw Greenhouse candidate IDs are omitted unless
        ``include_ids=True``.
        """
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        if email is not None:
            params["email"] = email
        if updated_after is not None:
            params["updated_after"] = updated_after
        if job_id is not None:
            params["job_id"] = job_id
        payload: object = self._client.get("/v1/candidates", params=params).json()
        if not isinstance(payload, list):
            return cast("dict[str, Any]", payload)
        payload_list = cast("list[Any]", payload)
        summaries = [
            self._candidate_summary(
                cast("dict[str, Any]", candidate), index=index, include_ids=include_ids
            )
            for index, candidate in enumerate(payload_list, start=1)
            if isinstance(candidate, dict)
        ]
        return {"candidates": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_candidate(self, candidate_id: int) -> dict[str, Any]:
        """Return one candidate by ID.

        ``candidate_id`` is the raw Greenhouse candidate ID. The ID is an
        internal handle and should not appear in final answers.
        """
        if not candidate_id:
            raise ValueError("candidate_id is required")
        return self._client.get(f"/v1/candidates/{candidate_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Create a candidate.

        ``candidate`` is the full Harvest candidate payload (at minimum
        ``first_name`` and ``last_name``). Requires ``on_behalf_of`` on
        the connector. Confirm with the user before calling.
        """
        if not candidate:
            raise ValueError("candidate must be non-empty")
        return self._client.post(
            "/v1/candidates",
            json=candidate,
            headers=self._write_headers(),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_applications(
        self,
        *,
        job_id: int | None = None,
        status: str | None = None,
        per_page: int = 25,
        page: int = 1,
    ) -> dict[str, Any]:
        """List applications.

        Optionally filter by ``job_id`` and ``status`` (``active``/
        ``hired``/``rejected``).
        """
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        if job_id is not None:
            params["job_id"] = job_id
        if status is not None:
            params["status"] = status
        return self._client.get("/v1/applications", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def advance_application(
        self,
        application_id: int,
        *,
        from_stage_id: int,
    ) -> dict[str, Any]:
        """Move an application to the next stage.

        ``application_id`` and ``from_stage_id`` are both Greenhouse IDs.
        Requires ``on_behalf_of``.
        """
        if not application_id or not from_stage_id:
            raise ValueError("application_id and from_stage_id are required")
        return self._client.post(
            f"/v1/applications/{application_id}/advance",
            json={"from_stage_id": from_stage_id},
            headers=self._write_headers(),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def reject_application(
        self,
        application_id: Any,
        *,
        rejection_reason_id: int,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Reject an application.

        Destructive — moves the candidate out of consideration. Accepts
        the raw integer ID, a string, or an application dict (the
        ``application_id``/``id`` key is read). Requires ``on_behalf_of``.
        Confirm with the user before calling.
        """
        resolved = self._select_application_id(application_id)
        if not rejection_reason_id:
            raise ValueError("rejection_reason_id is required")
        body: dict[str, Any] = {"rejection_reason_id": rejection_reason_id}
        if notes is not None:
            body["notes"] = notes
        return self._client.post(
            f"/v1/applications/{resolved}/reject",
            json=body,
            headers=self._write_headers(),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_scorecards(
        self,
        *,
        application_id: int | None = None,
        per_page: int = 25,
        page: int = 1,
    ) -> dict[str, Any]:
        """List interview scorecards.

        When ``application_id`` is provided, scorecards for that single
        application are returned (``GET /v1/applications/{id}/scorecards``).
        Otherwise all org scorecards are listed. The top-level scorecards
        endpoint does not support per-application/candidate filtering.
        """
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        if application_id is not None:
            path = f"/v1/applications/{application_id}/scorecards"
        else:
            path = "/v1/scorecards"
        return self._client.get(path, params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_offers(
        self,
        *,
        application_id: int | None = None,
        per_page: int = 25,
        page: int = 1,
    ) -> dict[str, Any]:
        """List offers.

        When ``application_id`` is provided, offers for that single
        application are returned (``GET /v1/applications/{id}/offers``).
        Otherwise all org offers are listed. The top-level offers endpoint
        does not support per-application filtering.
        """
        params: dict[str, Any] = {"per_page": per_page, "page": page}
        if application_id is not None:
            path = f"/v1/applications/{application_id}/offers"
        else:
            path = "/v1/offers"
        return self._client.get(path, params=params).json()
