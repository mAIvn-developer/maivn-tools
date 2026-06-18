"""Lever API connector (ATS)."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import (
    LIST_OPPORTUNITIES_OUTPUT,
    LIST_POSTINGS_OUTPUT,
    LIST_USERS_OUTPUT,
)


@toolset(prefix="lever")
class LeverToolSet:
    """A connector for the Lever v1 REST API.

    Args:
        api_key: Lever API key (sent as Basic auth username with an
            empty password).
        sandbox: When True, target ``sandbox.lever.co`` instead of
            production.
    """

    metadata = ProviderMetadata(
        name="lever",
        display_name="Lever",
        version="0.1.0",
        description="Opportunities (candidates), postings, stages, and feedback.",
        auth_modes=(AuthMode.BASIC,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://hire.lever.co/developer/documentation",
        homepage_url="https://www.lever.co/",
        tags=("hr", "ats", "recruiting"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        sandbox: bool = False,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        host = "api.sandbox.lever.co" if sandbox else "api.lever.co"
        self._client = HttpClient(
            base_url=f"https://{host}",
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

    # MARK: - Internal helpers

    @staticmethod
    def _opportunity_summary(
        opportunity: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        emails = opportunity.get("emails", [])
        primary_email = ""
        if isinstance(emails, list) and emails:
            primary_email = emails[0] if isinstance(emails[0], str) else ""
        stage: Any = opportunity.get("stage", "")
        if isinstance(stage, dict):
            stage = cast(dict[str, Any], stage).get("text", "") or ""
        summary: dict[str, Any] = {
            "candidate_ref": f"candidate_{index}",
            "name": opportunity.get("name", "") or "",
            "email": primary_email,
            "headline": opportunity.get("headline", "") or "",
            "stage": stage,
            "archived": opportunity.get("archived") is not None,
            "created_at": opportunity.get("createdAt", ""),
        }
        if include_ids:
            summary["opportunity_id"] = opportunity.get("id", "")
        return summary

    @staticmethod
    def _posting_summary(
        posting: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        categories_raw: Any = posting.get("categories", {})
        categories: dict[str, Any] = (
            cast(dict[str, Any], categories_raw) if isinstance(categories_raw, dict) else {}
        )
        summary: dict[str, Any] = {
            "job_ref": f"job_{index}",
            "title": posting.get("text", "") or "",
            "state": posting.get("state", ""),
            "team": categories.get("team", ""),
            "department": categories.get("department", ""),
            "location": categories.get("location", ""),
            "commitment": categories.get("commitment", ""),
            "created_at": posting.get("createdAt", ""),
        }
        if include_ids:
            summary["posting_id"] = posting.get("id", "")
        return summary

    @staticmethod
    def _user_summary(
        user: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "user_ref": f"user_{index}",
            "name": user.get("name", "") or "",
            "email": user.get("email", ""),
            "access_role": user.get("accessRole", ""),
            "deactivated_at": user.get("deactivatedAt", ""),
        }
        if include_ids:
            summary["user_id"] = user.get("id", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_OPPORTUNITIES_OUTPUT)
    def list_opportunities(
        self,
        *,
        contact_id: str | None = None,
        email: str | None = None,
        posting_id: str | None = None,
        stage_id: str | None = None,
        archived: bool | None = None,
        limit: int = 25,
        offset: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List opportunities (candidates in Lever's data model).

        Best first tool for candidate discovery. Returns compact summaries
        with ``candidate_ref`` (``candidate_1``, ``candidate_2``, ...),
        name, primary email, headline, stage text, archived flag, and
        created date. Raw Lever opportunity IDs are omitted unless
        ``include_ids=True``; set it only when a follow-up tool
        (:meth:`get_opportunity`, :meth:`update_opportunity_stage`,
        :meth:`archive_opportunity`) needs the raw ID. Pagination is via
        ``offset``.
        """
        params: dict[str, Any] = {"limit": limit}
        if contact_id is not None:
            params["contact_id"] = contact_id
        if email is not None:
            params["email"] = email
        if posting_id is not None:
            params["posting_id"] = posting_id
        if stage_id is not None:
            params["stage_id"] = stage_id
        if archived is not None:
            params["archived"] = str(archived).lower()
        if offset is not None:
            params["offset"] = offset
        raw: object = self._client.get("/v1/opportunities", params=params).json()
        if not isinstance(raw, dict):
            return cast(dict[str, Any], raw)
        payload: dict[str, Any] = cast(dict[str, Any], raw)
        data: object = payload.get("data")
        if not isinstance(data, list):
            return payload
        items: list[Any] = cast(list[Any], data)
        summaries = [
            self._opportunity_summary(
                cast(dict[str, Any], item), index=index, include_ids=include_ids
            )
            for index, item in enumerate(items, start=1)
            if isinstance(item, dict)
        ]
        return {
            "candidates": summaries,
            "next": payload.get("next"),
            "hasNext": payload.get("hasNext", False),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_opportunity(self, opportunity_id: str) -> dict[str, Any]:
        """Return one opportunity by ID.

        ``opportunity_id`` is the raw Lever opportunity ID returned by
        ``list_opportunities(include_ids=True)``. The ID is an internal
        handle and should not appear in final answers.
        """
        if not opportunity_id:
            raise ValueError("opportunity_id is required")
        return self._client.get(f"/v1/opportunities/{opportunity_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_opportunity(
        self,
        *,
        perform_as: str,
        opportunity: dict[str, Any],
    ) -> dict[str, Any]:
        """Create an opportunity acting on behalf of ``perform_as``.

        ``perform_as`` is a Lever user ID; ``opportunity`` is the full
        Lever opportunity payload (at minimum a ``name``).
        """
        if not perform_as or not opportunity:
            raise ValueError("perform_as and opportunity are required")
        return self._client.post(
            "/v1/opportunities",
            params={"perform_as": perform_as},
            json=opportunity,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_opportunity_stage(
        self,
        opportunity_id: str,
        *,
        perform_as: str,
        stage_id: str,
    ) -> dict[str, Any]:
        """Move an opportunity to a new pipeline stage.

        ``opportunity_id`` and ``stage_id`` are raw Lever IDs.
        """
        if not opportunity_id or not perform_as or not stage_id:
            raise ValueError("opportunity_id, perform_as, and stage_id are required")
        return self._client.put(
            f"/v1/opportunities/{opportunity_id}/stage",
            params={"perform_as": perform_as},
            json={"stage": stage_id},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_POSTINGS_OUTPUT)
    def list_postings(
        self,
        *,
        state: str | None = None,
        location: str | None = None,
        limit: int = 25,
        offset: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List job postings.

        Returns compact summaries with ``job_ref`` (``job_1``, ``job_2``,
        ...), title, state, team, department, location, commitment, and
        created date. Raw Lever posting IDs are omitted unless
        ``include_ids=True``.
        """
        params: dict[str, Any] = {"limit": limit}
        if state is not None:
            params["state"] = state
        if location is not None:
            params["location"] = location
        if offset is not None:
            params["offset"] = offset
        raw: object = self._client.get("/v1/postings", params=params).json()
        if not isinstance(raw, dict):
            return cast(dict[str, Any], raw)
        payload: dict[str, Any] = cast(dict[str, Any], raw)
        data: object = payload.get("data")
        if not isinstance(data, list):
            return payload
        items: list[Any] = cast(list[Any], data)
        summaries = [
            self._posting_summary(
                cast(dict[str, Any], posting), index=index, include_ids=include_ids
            )
            for index, posting in enumerate(items, start=1)
            if isinstance(posting, dict)
        ]
        return {
            "jobs": summaries,
            "next": payload.get("next"),
            "hasNext": payload.get("hasNext", False),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_posting(self, posting_id: str) -> dict[str, Any]:
        """Return one posting by ID.

        ``posting_id`` is the raw Lever posting ID. The ID is an internal
        handle and should not appear in final answers.
        """
        if not posting_id:
            raise ValueError("posting_id is required")
        return self._client.get(f"/v1/postings/{posting_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_stages(self) -> dict[str, Any]:
        """List pipeline stages.

        Returns the raw Lever stage list. Use ``id`` to drive
        :meth:`update_opportunity_stage`.
        """
        return self._client.get("/v1/stages").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_USERS_OUTPUT)
    def list_users(
        self,
        *,
        access_role: str | None = None,
        limit: int = 25,
        offset: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Lever users (interviewers, recruiters, etc.).

        Returns compact summaries with ``user_ref`` (``user_1``,
        ``user_2``, ...), name, email, access role, and deactivation
        timestamp. Raw Lever user IDs are omitted unless
        ``include_ids=True``.
        """
        params: dict[str, Any] = {"limit": limit}
        if access_role is not None:
            params["access_role"] = access_role
        if offset is not None:
            params["offset"] = offset
        raw: object = self._client.get("/v1/users", params=params).json()
        if not isinstance(raw, dict):
            return cast(dict[str, Any], raw)
        payload: dict[str, Any] = cast(dict[str, Any], raw)
        data: object = payload.get("data")
        if not isinstance(data, list):
            return payload
        items: list[Any] = cast(list[Any], data)
        summaries = [
            self._user_summary(cast(dict[str, Any], user), index=index, include_ids=include_ids)
            for index, user in enumerate(items, start=1)
            if isinstance(user, dict)
        ]
        return {
            "users": summaries,
            "next": payload.get("next"),
            "hasNext": payload.get("hasNext", False),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_feedback(
        self,
        opportunity_id: str,
        *,
        limit: int = 25,
        offset: str | None = None,
    ) -> dict[str, Any]:
        """List feedback (interview scorecards) for an opportunity.

        ``opportunity_id`` is the raw Lever opportunity ID. Returns the
        feedback list payload.
        """
        if not opportunity_id:
            raise ValueError("opportunity_id is required")
        params: dict[str, Any] = {"limit": limit}
        if offset is not None:
            params["offset"] = offset
        return self._client.get(
            f"/v1/opportunities/{opportunity_id}/feedback", params=params
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def archive_opportunity(
        self,
        opportunity_id: str,
        *,
        perform_as: str,
        archive_reason_id: str,
    ) -> dict[str, Any]:
        """Archive an opportunity (removes them from active pipeline).

        Destructive — confirm with the user before calling. All three
        arguments are raw Lever IDs.
        """
        if not opportunity_id or not perform_as or not archive_reason_id:
            raise ValueError("opportunity_id, perform_as, and archive_reason_id are required")
        return self._client.put(
            f"/v1/opportunities/{opportunity_id}/archived",
            params={"perform_as": perform_as},
            json={"reason": archive_reason_id},
        ).json()
