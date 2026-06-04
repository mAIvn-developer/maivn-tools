"""Expensify Integration Server connector.

The Expensify Integration Server uses ``application/x-www-form-urlencoded``
POSTs with a ``requestJobDescription`` JSON parameter and partner
credentials in the body. This toolset wraps that convention.
"""
# pyright: strict

from __future__ import annotations

import json as _json
from typing import Any, cast

from maivn import toolify, toolset

from ...auth.base import NoAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="expensify")
class ExpensifyToolSet:
    """A connector for the Expensify Integration Server.

    Plug into an Agent with ``agent.add_toolset(ExpensifyToolSet(
    partner_user_id=..., partner_user_secret=...))`` and the agent can
    answer questions about expense policies and run report exports.
    """

    metadata = ProviderMetadata(
        name="expensify",
        display_name="Expensify",
        version="0.1.0",
        description="Reports, expenses, policies, and exports via the Integration Server.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://integrations.expensify.com/Integration-Server/doc/",
        homepage_url="https://www.expensify.com/",
        tags=("expense", "finance"),
    )

    def __init__(
        self,
        *,
        partner_user_id: str,
        partner_user_secret: str,
        base_url: str = "https://integrations.expensify.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not partner_user_id or not partner_user_secret:
            raise ValueError("partner_user_id and partner_user_secret are required")
        self.connection = connection
        self._partner_id = partner_user_id
        self._partner_secret = partner_user_secret
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=NoAuth(),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _submit(
        self,
        job: dict[str, Any],
        *,
        template: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "requestJobDescription": _json.dumps(
                {
                    "credentials": {
                        "partnerUserID": self._partner_id,
                        "partnerUserSecret": self._partner_secret,
                    },
                    **job,
                }
            )
        }
        if template is not None:
            # Freemarker template required by the file-export job; the
            # Integration Server accepts it as a sibling form field.
            params["template"] = template
        response = self._client.post(
            "/Integration-Server/ExpensifyIntegrations",
            params=params,
        )
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text()
        return {"status": response.status, "body": body}

    # MARK: file-export helpers

    def _download_file(self, file_name: str) -> dict[str, Any]:
        """Issue the second-step ``download`` job to fetch exported bytes."""
        return self._submit(
            {
                "type": "download",
                "inputSettings": {
                    "type": "file",
                    "fileName": file_name,
                    "fileSystem": "integrationServer",
                },
            }
        )

    @staticmethod
    def _extract_file_name(submit_result: dict[str, Any]) -> str | None:
        """Pull the generated random filename out of a ``file`` job response."""
        body: Any = submit_result.get("body")
        if isinstance(body, dict):
            mapping = cast(dict[str, Any], body)
            name: Any = mapping.get("filename") or mapping.get("fileName")
            if isinstance(name, str) and name:
                return name
        if isinstance(body, str):
            text = body.strip()
            if text and "\n" not in text and "{" not in text:
                return text
        return None

    # MARK: tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def export_report(
        self,
        *,
        report_id: str,
        file_extension: str = "csv",
        template_ftl: str,
    ) -> dict[str, Any]:
        """Export one or more Expensify reports in the requested format.

        ``report_id`` is a single report ID (comma-join multiple IDs for a
        combined export). ``file_extension`` is one of ``csv``, ``pdf``,
        ``xlsx``. ``template_ftl`` is the Freemarker template body required by
        the Integration Server ``file`` job.

        The Integration Server file export is a two-step flow: the ``file``
        job returns only a generated filename, then a ``download`` job
        retrieves the bytes. Returns the ``download`` job response (the actual
        export), or the ``file`` job response if no filename was returned.
        """
        if not report_id:
            raise ValueError("report_id must be a non-empty string")
        if file_extension not in {"csv", "pdf", "xlsx"}:
            raise ValueError("file_extension must be csv/pdf/xlsx")
        if not template_ftl:
            raise ValueError("template_ftl must be a non-empty Freemarker template")
        submit_result = self._submit(
            {
                "type": "file",
                "onReceive": {"immediateResponse": ["returnRandomFileName"]},
                "inputSettings": {
                    "type": "combinedReportData",
                    "filters": {"reportIDList": report_id},
                },
                "outputSettings": {"fileExtension": file_extension},
            },
            template=template_ftl,
        )
        file_name = self._extract_file_name(submit_result)
        if file_name is None:
            return submit_result
        return self._download_file(file_name)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def report_export(
        self,
        *,
        report_state: str,
        template_ftl: str,
        file_extension: str = "csv",
        approved_after: str | None = None,
        approved_before: str | None = None,
        policy_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a report export job filtered by lifecycle state.

        ``report_state`` is the lifecycle filter (e.g. ``"APPROVED"``,
        ``"REIMBURSED"``) and is set at the ``inputSettings`` root.
        ``template_ftl`` is the required Freemarker template body and
        ``file_extension`` is one of ``csv``/``pdf``/``xlsx``.

        Performs the two-step ``file``/``download`` flow and returns the
        ``download`` job response (the actual export), or the ``file`` job
        response if no filename was returned.
        """
        if not report_state:
            raise ValueError("report_state must be a non-empty string")
        if not template_ftl:
            raise ValueError("template_ftl must be a non-empty Freemarker template")
        if file_extension not in {"csv", "pdf", "xlsx"}:
            raise ValueError("file_extension must be csv/pdf/xlsx")
        report_filters: dict[str, Any] = {}
        if approved_after is not None:
            report_filters["approvedAfter"] = approved_after
        if approved_before is not None:
            report_filters["approvedBefore"] = approved_before
        if policy_id is not None:
            report_filters["policyIDList"] = [policy_id]
        input_settings: dict[str, Any] = {
            "type": "combinedReportData",
            "reportState": report_state,
        }
        if report_filters:
            input_settings["filters"] = report_filters
        submit_result = self._submit(
            {
                "type": "file",
                "onReceive": {"immediateResponse": ["returnRandomFileName"]},
                "inputSettings": input_settings,
                "outputSettings": {"fileExtension": file_extension},
            },
            template=template_ftl,
        )
        file_name = self._extract_file_name(submit_result)
        if file_name is None:
            return submit_result
        return self._download_file(file_name)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_policy_list(self) -> dict[str, Any]:
        """List Expensify policies. Returns the raw Integration Server response."""
        return self._submit({"type": "get", "inputSettings": {"type": "policyList"}})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_policy(
        self,
        policy_id: str,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return one Expensify policy's configuration by ID.

        ``fields`` selects which policy attributes to retrieve; the
        Integration Server requires this array and returns no detail without
        it. Defaults to the full set when omitted.
        """
        if not policy_id:
            raise ValueError("policy_id must be a non-empty string")
        requested_fields = fields or [
            "categories",
            "tags",
            "tax",
            "reportFields",
            "employees",
        ]
        return self._submit(
            {
                "type": "get",
                "inputSettings": {
                    "type": "policy",
                    "policyIDList": [policy_id],
                    "fields": requested_fields,
                },
            }
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def update_policy(
        self,
        *,
        policy_id: str,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        """Update Expensify policy configuration in place.

        ``policy_id`` identifies the target policy. ``settings`` holds the
        mutation payloads keyed by attribute (``categories``, ``tags``,
        ``reportFields``), each a ``{"action": ..., "data": ...}`` mapping;
        these are sent as top-level siblings of ``inputSettings`` per the
        Integration Server update contract. ``policyID`` is placed inside
        ``inputSettings`` (``type="policy"``).

        Replacing categories/tags overwrites configuration in place, so this
        is marked destructive. Returns the raw Integration Server response.
        """
        if not policy_id or not settings:
            raise ValueError("policy_id and settings must be non-empty")
        return self._submit(
            {
                "type": "update",
                "inputSettings": {"type": "policy", "policyID": policy_id},
                **settings,
            }
        )
