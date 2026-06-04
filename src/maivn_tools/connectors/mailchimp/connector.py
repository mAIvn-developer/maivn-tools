"""Mailchimp Marketing API 3.0 connector."""

# pyright: strict
from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="mailchimp")
class MailchimpToolSet:
    """A connector for Mailchimp Marketing API 3.0."""

    metadata = ProviderMetadata(
        name="mailchimp",
        display_name="Mailchimp",
        version="0.1.0",
        description="Audiences, campaigns, templates, segments, and reports.",
        auth_modes=(AuthMode.BASIC, AuthMode.OAUTH2_AUTH_CODE),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://mailchimp.com/developer/marketing/api/",
        homepage_url="https://mailchimp.com/",
        tags=("email", "marketing"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        data_center: str | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        dc = data_center
        if dc is None and "-" in api_key:
            dc = api_key.rsplit("-", 1)[-1]
        if not dc:
            raise ValueError("data_center could not be inferred from api_key")
        self.connection = connection
        self._client = HttpClient(
            base_url=f"https://{dc}.api.mailchimp.com",
            auth=BasicAuth("anystring", api_key),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @staticmethod
    def _list_summary(
        lst: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        stats: object = lst.get("stats") or {}
        stats_dict: dict[str, Any] = (
            cast("dict[str, Any]", stats) if isinstance(stats, dict) else {}
        )
        summary: dict[str, Any] = {
            "list_ref": f"list_{index}",
            "name": lst.get("name", ""),
            "member_count": stats_dict.get("member_count", 0),
            "unsubscribe_count": stats_dict.get("unsubscribe_count", 0),
            "date_created": lst.get("date_created", ""),
        }
        if include_ids:
            summary["list_id"] = lst.get("id", "")
        return summary

    @staticmethod
    def _member_summary(
        member: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        merge_fields: object = member.get("merge_fields") or {}
        mf_dict: dict[str, Any] = (
            cast("dict[str, Any]", merge_fields) if isinstance(merge_fields, dict) else {}
        )
        first: Any = mf_dict.get("FNAME") or ""
        last: Any = mf_dict.get("LNAME") or ""
        summary: dict[str, Any] = {
            "subscriber_ref": f"subscriber_{index}",
            "name": f"{first} {last}".strip() or member.get("email_address", ""),
            "email": member.get("email_address", ""),
            "status": member.get("status", ""),
            "timestamp_signup": member.get("timestamp_signup", ""),
            "last_changed": member.get("last_changed", ""),
        }
        if include_ids:
            summary["subscriber_id"] = member.get("id", "")
            summary["unique_email_id"] = member.get("unique_email_id", "")
        return summary

    @staticmethod
    def _campaign_summary(
        campaign: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        settings: object = campaign.get("settings") or {}
        settings_dict: dict[str, Any] = (
            cast("dict[str, Any]", settings) if isinstance(settings, dict) else {}
        )
        summary: dict[str, Any] = {
            "campaign_ref": f"campaign_{index}",
            "title": settings_dict.get("title", ""),
            "subject_line": settings_dict.get("subject_line", ""),
            "type": campaign.get("type", ""),
            "status": campaign.get("status", ""),
            "send_time": campaign.get("send_time", ""),
            "emails_sent": campaign.get("emails_sent", 0),
        }
        if include_ids:
            summary["campaign_id"] = campaign.get("id", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def ping(self) -> dict[str, Any]:
        """Check that the account responds.

        Use to validate the API key at startup.
        """
        return self._client.get("/3.0/ping").json()

    # MARK: - Lists / Audiences

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_lists(
        self,
        *,
        count: int = 10,
        offset: int = 0,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List audiences (lists) with compact summaries.

        Returns compact summaries with ``list_ref`` plus name,
        member_count, unsubscribe_count. Raw list IDs are omitted by
        default — set ``include_ids=True`` when ``get_list`` /
        ``list_members`` needs them.
        """
        if count < 1 or count > 1000:
            raise ValueError("count must be between 1 and 1000")
        payload: dict[str, Any] = self._client.get(
            "/3.0/lists",
            params={"count": count, "offset": offset},
        ).json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("lists") or []
        summaries = [
            self._list_summary(cast("dict[str, Any]", lst), index=i, include_ids=include_ids)
            for i, lst in enumerate(items, start=1)
            if isinstance(lst, dict)
        ]
        return {
            "lists": summaries,
            "count": len(summaries),
            "total_items": payload.get("total_items"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_list(self, list_id: str) -> dict[str, Any]:
        """Return one audience with full stats.

        Use after ``list_lists(include_ids=True)``.
        """
        if not list_id:
            raise ValueError("list_id must be a non-empty string")
        return self._client.get(f"/3.0/lists/{list_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_members(
        self,
        list_id: str,
        *,
        status: str | None = None,
        count: int = 10,
        offset: int = 0,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List audience members with compact summaries.

        Returns compact summaries with ``subscriber_ref`` plus name,
        email (user-facing), status. ``status`` filters: ``subscribed``,
        ``unsubscribed``, ``cleaned``, ``pending``, ``transactional``.
        """
        if not list_id:
            raise ValueError("list_id must be a non-empty string")
        if count < 1 or count > 1000:
            raise ValueError("count must be between 1 and 1000")
        params: dict[str, Any] = {"count": count, "offset": offset}
        if status is not None:
            params["status"] = status
        payload: dict[str, Any] = self._client.get(
            f"/3.0/lists/{list_id}/members",
            params=params,
        ).json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("members") or []
        summaries = [
            self._member_summary(cast("dict[str, Any]", m), index=i, include_ids=include_ids)
            for i, m in enumerate(items, start=1)
            if isinstance(m, dict)
        ]
        return {
            "subscribers": summaries,
            "count": len(summaries),
            "total_items": payload.get("total_items"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upsert_member(
        self,
        list_id: str,
        *,
        email: str,
        status: str = "subscribed",
        merge_fields: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add or update a member by email (uses ``PUT`` with MD5 subscriber hash).

        Email is the user-facing identifier. ``status`` is ``subscribed``,
        ``unsubscribed``, ``cleaned``, ``pending``, ``transactional``.
        Returns the member resource.
        """
        if not list_id or not email:
            raise ValueError("list_id and email must be non-empty")
        from hashlib import md5

        sub_hash = md5(email.lower().encode("utf-8")).hexdigest()
        body: dict[str, Any] = {"email_address": email, "status_if_new": status}
        if merge_fields is not None:
            body["merge_fields"] = merge_fields
        if tags is not None:
            body["tags"] = tags
        return self._client.put(
            f"/3.0/lists/{list_id}/members/{sub_hash}",
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def archive_member(self, list_id: str, *, email: str) -> dict[str, Any]:
        """Archive (unsubscribe) a member. Destructive — confirm with the user first.

        Unsubscribes the member; their record is preserved but they
        receive no future mailings.
        """
        if not list_id or not email:
            raise ValueError("list_id and email must be non-empty")
        from hashlib import md5

        sub_hash = md5(email.lower().encode("utf-8")).hexdigest()
        response = self._client.delete(f"/3.0/lists/{list_id}/members/{sub_hash}")
        return {"list_id": list_id, "email": email, "archived": True, "status": response.status}

    # MARK: - Campaigns

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_campaigns(
        self,
        *,
        status: str | None = None,
        count: int = 10,
        offset: int = 0,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List campaigns with compact summaries.

        Returns compact summaries with ``campaign_ref`` plus title,
        subject_line, type, status. ``status`` filters: ``save``,
        ``paused``, ``schedule``, ``sending``, ``sent``. Raw campaign IDs
        are omitted by default.
        """
        if count < 1 or count > 1000:
            raise ValueError("count must be between 1 and 1000")
        params: dict[str, Any] = {"count": count, "offset": offset}
        if status is not None:
            params["status"] = status
        payload: dict[str, Any] = self._client.get("/3.0/campaigns", params=params).json()
        if include_raw:
            return payload
        items: list[Any] = payload.get("campaigns") or []
        summaries = [
            self._campaign_summary(cast("dict[str, Any]", c), index=i, include_ids=include_ids)
            for i, c in enumerate(items, start=1)
            if isinstance(c, dict)
        ]
        return {
            "campaigns": summaries,
            "count": len(summaries),
            "total_items": payload.get("total_items"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_campaign(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a campaign with the standard Mailchimp ``settings`` payload.

        Returns the new campaign resource. Use ``send_campaign`` or
        ``schedule_campaign`` to send.
        """
        if not payload:
            raise ValueError("payload must be non-empty")
        return self._client.post("/3.0/campaigns", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def send_campaign(self, campaign_id: str) -> dict[str, Any]:
        """Send a campaign immediately. Irreversible once sent.

        Marked destructive — every subscriber on the audience will
        receive the email. Always confirm with the user first.
        """
        if not campaign_id:
            raise ValueError("campaign_id must be a non-empty string")
        response = self._client.post(f"/3.0/campaigns/{campaign_id}/actions/send")
        return {"id": campaign_id, "sent": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def schedule_campaign(
        self,
        campaign_id: str,
        *,
        schedule_time: str,
    ) -> dict[str, Any]:
        """Schedule a campaign for a future send.

        ``schedule_time`` is an ISO 8601 timestamp. The send is still
        irreversible at that time — confirm with the user first.
        """
        if not campaign_id or not schedule_time:
            raise ValueError("campaign_id and schedule_time must be non-empty")
        response = self._client.post(
            f"/3.0/campaigns/{campaign_id}/actions/schedule",
            json={"schedule_time": schedule_time},
        )
        return {"id": campaign_id, "scheduled": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_campaign(self, campaign_id: str) -> dict[str, Any]:
        """Permanently delete a campaign. Destructive — confirm with the user first."""
        if not campaign_id:
            raise ValueError("campaign_id must be a non-empty string")
        self._client.delete(f"/3.0/campaigns/{campaign_id}")
        return {"id": campaign_id, "deleted": True}

    # MARK: - Templates & reports

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_templates(self, *, count: int = 10, offset: int = 0) -> dict[str, Any]:
        """List templates.

        Returns the raw provider payload.
        """
        return self._client.get(
            "/3.0/templates",
            params={"count": count, "offset": offset},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_reports(self, *, count: int = 10, offset: int = 0) -> dict[str, Any]:
        """List campaign reports.

        Returns the raw provider payload with open / click / bounce stats
        per campaign.
        """
        return self._client.get(
            "/3.0/reports",
            params={"count": count, "offset": offset},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_report(self, campaign_id: str) -> dict[str, Any]:
        """Return one campaign report.

        Use after ``list_campaigns(include_ids=True)``.
        """
        if not campaign_id:
            raise ValueError("campaign_id must be a non-empty string")
        return self._client.get(f"/3.0/reports/{campaign_id}").json()
