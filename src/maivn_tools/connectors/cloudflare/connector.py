"""Cloudflare v4 REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

_SUMMARY_MAX = 25


# MARK: Helpers


def _coerce_id(candidate: Any, *, field: str) -> str:
    """Accept a string ID, a resource dict, or a list of such."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError(f"{field} is required")
        return candidate
    if isinstance(candidate, dict):
        candidate_dict = cast("dict[str, Any]", candidate)
        for key in (field, "id"):
            value: Any = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
    if isinstance(candidate, list) and candidate:
        candidate_list = cast("list[Any]", candidate)
        return _coerce_id(candidate_list[0], field=field)
    raise ValueError(f"{field} must be a non-empty string (or a resource dict)")


# MARK: ToolSet


@toolset(prefix="cloudflare")
class CloudflareToolSet:
    """A connector for the Cloudflare v4 REST API.

    Args:
        api_token: API token (recommended over global API key).
        base_url: API root (default ``https://api.cloudflare.com/client/v4``).
    """

    metadata = ProviderMetadata(
        name="cloudflare",
        display_name="Cloudflare",
        version="0.1.0",
        description="Zones, DNS records, cache, WAF, workers, and R2.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developers.cloudflare.com/api/",
        homepage_url="https://www.cloudflare.com/",
        tags=("cloud", "cdn", "dns"),
    )

    def __init__(
        self,
        *,
        api_token: str,
        base_url: str = "https://api.cloudflare.com/client/v4",
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

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def verify_token(self) -> dict[str, Any]:
        """Verify the API token.

        Returns ``{"status": "active", "expires_on": ..., "id": ...}``
        wrapped in the standard Cloudflare envelope. Use to sanity-check
        credentials.
        """
        return self._client.get("/user/tokens/verify").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_zones(
        self,
        *,
        name: str | None = None,
        status: str | None = None,
        page: int = 1,
        per_page: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List zones.

        Best first tool for zone discovery. Returns compact summaries:
        ``zone_ref``, ``name`` (the domain — user-facing), ``status``
        (``active``/``pending``/etc.), ``plan`` name. Raw zone IDs are
        omitted by default; set ``include_ids=True`` when a follow-up
        call (``list_dns_records``, ``purge_cache``) needs the zone ID.
        """
        if per_page < 1 or per_page > 50:
            raise ValueError("per_page must be between 1 and 50")
        if include_metadata:
            per_page = min(per_page, _SUMMARY_MAX)
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if name is not None:
            params["name"] = name
        if status is not None:
            params["status"] = status
        payload: dict[str, Any] = self._client.get("/zones", params=params).json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("result") or []
        summaries: list[dict[str, Any]] = []
        for index, zone in enumerate(items, start=1):
            if not isinstance(zone, dict):
                continue
            zone_data = cast("dict[str, Any]", zone)
            raw_plan: Any = zone_data.get("plan") or {}
            plan = cast("dict[str, Any]", raw_plan) if isinstance(raw_plan, dict) else {}
            summary: dict[str, Any] = {
                "zone_ref": f"zone_{index}",
                "name": zone_data.get("name", ""),
                "status": zone_data.get("status", ""),
                "plan": plan.get("name", ""),
            }
            if include_ids:
                summary["zone_id"] = zone_data.get("id", "")
            summaries.append(summary)
        return {"zones": summaries, "result_info": payload.get("result_info", {})}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_zone(self, zone_id: Any) -> dict[str, Any]:
        """Return one zone's settings.

        ``zone_id`` accepts a string ID or a zone dict from
        ``list_zones(include_ids=True)``.
        """
        zid = _coerce_id(zone_id, field="zone_id")
        return self._client.get(f"/zones/{zid}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_dns_records(
        self,
        zone_id: Any,
        *,
        type: str | None = None,
        name: str | None = None,
        content: str | None = None,
        page: int = 1,
        per_page: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List DNS records in a zone.

        Returns compact summaries: ``record_ref``, ``type`` (``A``,
        ``CNAME``, etc.), ``name``, ``content``, ``ttl``, ``proxied``.
        Raw record IDs omitted by default; set ``include_ids=True`` when
        a follow-up tool (``update_dns_record``, ``delete_dns_record``)
        needs them.

        ``zone_id`` accepts a string ID or a zone dict.
        """
        zid = _coerce_id(zone_id, field="zone_id")
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        if include_metadata:
            per_page = min(per_page, _SUMMARY_MAX)
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if type is not None:
            params["type"] = type
        if name is not None:
            params["name"] = name
        if content is not None:
            params["content"] = content
        payload: dict[str, Any] = self._client.get(
            f"/zones/{zid}/dns_records", params=params
        ).json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("result") or []
        summaries: list[dict[str, Any]] = []
        for index, record in enumerate(items, start=1):
            if not isinstance(record, dict):
                continue
            record_data = cast("dict[str, Any]", record)
            summary: dict[str, Any] = {
                "record_ref": f"record_{index}",
                "type": record_data.get("type", ""),
                "name": record_data.get("name", ""),
                "content": record_data.get("content", ""),
                "ttl": record_data.get("ttl", 0),
                "proxied": record_data.get("proxied", False),
            }
            if include_ids:
                summary["record_id"] = record_data.get("id", "")
            summaries.append(summary)
        return {"records": summaries, "result_info": payload.get("result_info", {})}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_dns_record(
        self,
        zone_id: Any,
        *,
        type: str,
        name: str,
        content: str,
        ttl: int = 1,
        proxied: bool = False,
        priority: int | None = None,
    ) -> dict[str, Any]:
        """Create a DNS record.

        Returns the new record. ``ttl=1`` means "automatic". ``proxied``
        controls the orange-cloud. ``priority`` is required for MX
        records.

        ``zone_id`` accepts a string ID or a zone dict.
        """
        zid = _coerce_id(zone_id, field="zone_id")
        if not type or not name or not content:
            raise ValueError("type, name, and content are required")
        body: dict[str, Any] = {
            "type": type,
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": proxied,
        }
        if priority is not None:
            body["priority"] = priority
        return self._client.post(f"/zones/{zid}/dns_records", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_dns_record(
        self,
        *,
        zone_id: Any,
        record_id: Any,
        type: str | None = None,
        name: str | None = None,
        content: str | None = None,
        ttl: int | None = None,
        proxied: bool | None = None,
    ) -> dict[str, Any]:
        """Patch a DNS record.

        Both ``zone_id`` and ``record_id`` accept either a string ID or
        a resource dict from the corresponding list call.
        """
        zid = _coerce_id(zone_id, field="zone_id")
        rid = _coerce_id(record_id, field="record_id")
        body: dict[str, Any] = {}
        if type is not None:
            body["type"] = type
        if name is not None:
            body["name"] = name
        if content is not None:
            body["content"] = content
        if ttl is not None:
            body["ttl"] = ttl
        if proxied is not None:
            body["proxied"] = proxied
        if not body:
            raise ValueError("at least one update field is required")
        return self._client.patch(f"/zones/{zid}/dns_records/{rid}", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_dns_record(
        self,
        *,
        zone_id: Any,
        record_id: Any,
    ) -> dict[str, Any]:
        """Delete a DNS record.

        Destructive — confirm with the user first. Both IDs accept a
        string or a resource dict from the corresponding list call.
        """
        zid = _coerce_id(zone_id, field="zone_id")
        rid = _coerce_id(record_id, field="record_id")
        return self._client.delete(f"/zones/{zid}/dns_records/{rid}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def purge_cache(
        self,
        zone_id: Any,
        *,
        purge_everything: bool = False,
        files: list[str] | None = None,
        tags: list[str] | None = None,
        hosts: list[str] | None = None,
    ) -> dict[str, Any]:
        """Purge cached resources (full or partial).

        Destructive — site visitors will see slower responses until the
        cache repopulates. Pass ``purge_everything=True`` only when
        scoped purges (``files``/``tags``/``hosts``) are not enough.
        """
        zid = _coerce_id(zone_id, field="zone_id")
        if not purge_everything and not files and not tags and not hosts:
            raise ValueError("Provide purge_everything=True, files, tags, or hosts")
        body: dict[str, Any] = {}
        if purge_everything:
            body["purge_everything"] = True
        if files is not None:
            body["files"] = files
        if tags is not None:
            body["tags"] = tags
        if hosts is not None:
            body["hosts"] = hosts
        return self._client.post(f"/zones/{zid}/purge_cache", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_workers(
        self,
        account_id: str,
        *,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Worker scripts on an account.

        Returns compact summaries: ``worker_ref``, ``name`` (script name
        — user-facing), ``created_on``, ``modified_on``, ``etag``. Set
        ``include_ids=True`` for the raw script ID.
        """
        if not account_id:
            raise ValueError("account_id is required")
        payload: dict[str, Any] = self._client.get(f"/accounts/{account_id}/workers/scripts").json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("result") or []
        summaries: list[dict[str, Any]] = []
        for index, worker in enumerate(items[:_SUMMARY_MAX], start=1):
            if not isinstance(worker, dict):
                continue
            worker_data = cast("dict[str, Any]", worker)
            summary: dict[str, Any] = {
                "worker_ref": f"worker_{index}",
                "name": worker_data.get("id", ""),
                "created_on": worker_data.get("created_on", ""),
                "modified_on": worker_data.get("modified_on", ""),
                "etag": worker_data.get("etag", ""),
            }
            if include_ids:
                summary["script_id"] = worker_data.get("id", "")
            summaries.append(summary)
        return {"workers": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_r2_buckets(
        self,
        account_id: str,
        *,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List R2 buckets.

        Returns compact summaries: ``bucket_ref``, ``name`` (bucket name
        — user-facing), ``creation_date``, ``location``. Bucket names are
        the primary identifier in R2; no separate ID is needed.
        """
        if not account_id:
            raise ValueError("account_id is required")
        payload: dict[str, Any] = self._client.get(f"/accounts/{account_id}/r2/buckets").json()
        if not include_metadata:
            return payload
        result: Any = payload.get("result") or {}
        raw_items: Any
        if isinstance(result, dict):
            raw_items = cast("dict[str, Any]", result).get("buckets")
        elif isinstance(result, list):
            raw_items = cast("list[Any]", result)
        else:
            raw_items = []
        items: list[Any] = raw_items or []
        summaries: list[dict[str, Any]] = []
        for index, bucket in enumerate(items[:_SUMMARY_MAX], start=1):
            if not isinstance(bucket, dict):
                continue
            bucket_data = cast("dict[str, Any]", bucket)
            summaries.append(
                {
                    "bucket_ref": f"bucket_{index}",
                    "name": bucket_data.get("name", ""),
                    "creation_date": bucket_data.get("creation_date", ""),
                    "location": bucket_data.get("location", ""),
                }
            )
        return {"buckets": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_r2_bucket(
        self,
        *,
        account_id: str,
        name: str,
        location_hint: str | None = None,
    ) -> dict[str, Any]:
        """Create an R2 bucket.

        Returns the new bucket. ``name`` must follow R2 naming rules
        (lowercase, alphanumeric + dashes). ``location_hint`` (e.g.
        ``"WEUR"``) is advisory only.
        """
        if not account_id or not name:
            raise ValueError("account_id and name are required")
        body: dict[str, Any] = {"name": name}
        if location_hint is not None:
            body["locationHint"] = location_hint
        return self._client.post(f"/accounts/{account_id}/r2/buckets", json=body).json()
