"""Zendesk Support REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.basic import BasicAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="zendesk")
class ZendeskToolSet:
    """A connector for Zendesk Support.

    Args:
        subdomain: Zendesk subdomain, e.g. ``acme`` for ``acme.zendesk.com``.
        email: Zendesk agent email (used with ``"/token"`` suffix for basic
            auth).
        api_token: API token. Never logged.
        transport: Optional :class:`HttpTransport` override.
        base_url: Override for self-hosted or sandbox subdomains.
    """

    metadata = ProviderMetadata(
        name="zendesk",
        display_name="Zendesk",
        version="0.1.0",
        description="Search, read, and update Zendesk tickets and users.",
        auth_modes=(AuthMode.BASIC,),
        scopes={
            "tickets:read": "Read tickets and ticket comments.",
            "tickets:write": "Create, update, and add comments to tickets.",
            "users:read": "Read user records.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developer.zendesk.com/api-reference/",
        homepage_url="https://www.zendesk.com",
        tags=("ticketing", "support"),
    )

    def __init__(
        self,
        *,
        subdomain: str = "",
        email: str,
        api_token: str,
        transport: HttpTransport | None = None,
        base_url: str | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if base_url is None and not subdomain:
            raise ValueError("Either subdomain or base_url is required")
        if not email:
            raise ValueError("email is required")
        if not api_token:
            raise ValueError("api_token is required")
        resolved_base = base_url or f"https://{subdomain}.zendesk.com"
        self.connection = connection
        self._client = HttpClient(
            base_url=resolved_base.rstrip("/"),
            auth=BasicAuth(f"{email}/token", api_token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_tickets(
        self,
        query: str,
        *,
        sort_by: str | None = "updated_at",
        sort_order: str = "desc",
        page: int = 1,
        per_page: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """Search tickets and users via Zendesk's search syntax.

        Best first tool for ticket triage. By default returns compact
        summaries with a stable ``ticket_ref`` (``ticket_1``, ``ticket_2``,
        ...) plus subject, status, priority, requester, and updated
        timestamp. Raw Zendesk numeric ``id`` values are internal handles
        and are omitted by default; set ``include_ids=True`` only when a
        follow-up tool (:meth:`get_ticket`, :meth:`update_ticket`,
        :meth:`add_comment`, :meth:`delete_ticket`) needs the raw id.

        Set ``include_metadata=False`` to receive the raw Zendesk payload
        including ``next_page``/``previous_page`` pagination cursors and
        any non-ticket results.

        Uses Zendesk offset pagination (``page``/``per_page``), which is
        capped at roughly 100 pages / 10k results; deeper result sets are
        silently truncated by the API. Narrow the ``query`` (or use
        ``next_page`` from the raw payload) to page through large result
        sets.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params: dict[str, Any] = {
            "query": query,
            "page": page,
            "per_page": per_page,
            "sort_order": sort_order,
        }
        if sort_by is not None:
            params["sort_by"] = sort_by
        payload = self._client.get("/api/v2/search.json", params=params).json()
        if not include_metadata:
            return payload
        return self._summarize_tickets(payload, source_key="results", include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_ticket(self, ticket_id: Any) -> dict[str, Any]:
        """Return one ticket by ID.

        ``ticket_id`` accepts the raw integer ID, a numeric string, a dict
        returned by :meth:`search_tickets`/:meth:`list_tickets`, or a list
        of such dicts.
        """
        resolved = self._extract_ticket_id(ticket_id)
        return self._client.get(f"/api/v2/tickets/{resolved}.json").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_ticket(
        self,
        subject: str,
        description: str,
        *,
        requester_email: str | None = None,
        priority: str | None = None,
        tags: list[str] | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a ticket.

        Returns the Zendesk ticket resource. ``description`` becomes the
        first ticket comment.
        """
        if not subject:
            raise ValueError("subject must be a non-empty string")
        if not description:
            raise ValueError("description must be a non-empty string")
        ticket: dict[str, Any] = {
            "subject": subject,
            "comment": {"body": description},
        }
        if requester_email is not None:
            ticket["requester"] = {"email": requester_email}
        if priority is not None:
            ticket["priority"] = priority
        if tags is not None:
            ticket["tags"] = list(tags)
        if extra_fields is not None:
            ticket.update(extra_fields)
        return self._client.post("/api/v2/tickets.json", json={"ticket": ticket}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_ticket(self, ticket_id: Any, patch: dict[str, Any]) -> dict[str, Any]:
        """Patch ticket fields (status, priority, assignee, etc.).

        ``ticket_id`` accepts the raw integer ID, a dict returned by
        :meth:`search_tickets`/:meth:`list_tickets`, or a list of such
        dicts.
        """
        resolved = self._extract_ticket_id(ticket_id)
        if not patch:
            raise ValueError("patch must be a non-empty dict")
        return self._client.put(
            f"/api/v2/tickets/{resolved}.json",
            json={"ticket": patch},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_comment(
        self,
        ticket_id: Any,
        body: str,
        *,
        public: bool = True,
    ) -> dict[str, Any]:
        """Append a public or internal comment to a ticket.

        ``ticket_id`` accepts the raw integer ID or a dict/list from
        :meth:`search_tickets`/:meth:`list_tickets`.
        """
        resolved = self._extract_ticket_id(ticket_id)
        if not body:
            raise ValueError("body must be a non-empty string")
        payload = {"ticket": {"comment": {"body": body, "public": public}}}
        return self._client.put(f"/api/v2/tickets/{resolved}.json", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self, user_id: int) -> dict[str, Any]:
        """Return one user record by ID."""
        return self._client.get(f"/api/v2/users/{int(user_id)}.json").json()

    # MARK: - Tickets (list, comments, attachments)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_tickets(
        self,
        *,
        sort_by: str = "id",
        sort_order: str = "asc",
        page: int = 1,
        per_page: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List tickets (paged).

        By default returns compact summaries with a stable ``ticket_ref``
        (``ticket_1``, ``ticket_2``, ...) plus subject, status, priority,
        requester, and updated timestamp. Raw Zendesk numeric IDs are
        omitted; set ``include_ids=True`` only when a follow-up tool needs
        them. Set ``include_metadata=False`` to receive the raw Zendesk
        ``{"tickets": [...], "next_page": ..., "previous_page": ...,
        "count": ...}`` payload.

        Uses Zendesk offset pagination (``page``/``per_page``), which is
        capped at roughly 100 pages / 10k results; deeper result sets are
        silently truncated by the API. Follow ``next_page`` from the raw
        payload to page through large result sets.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        payload = self._client.get(
            "/api/v2/tickets.json",
            params={
                "sort_by": sort_by,
                "sort_order": sort_order,
                "page": page,
                "per_page": per_page,
            },
        ).json()
        if not include_metadata:
            return payload
        return self._summarize_tickets(payload, source_key="tickets", include_ids=include_ids)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_ticket_comments(
        self,
        ticket_id: Any,
        *,
        per_page: int = 100,
        page: int = 1,
    ) -> dict[str, Any]:
        """List comments on a ticket.

        ``ticket_id`` accepts the raw integer ID or a dict/list from the
        ticket search/list tools.
        """
        resolved = self._extract_ticket_id(ticket_id)
        return self._client.get(
            f"/api/v2/tickets/{resolved}/comments.json",
            params={"per_page": per_page, "page": page},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_ticket(self, ticket_id: Any) -> dict[str, Any]:
        """Soft-delete a ticket (recoverable from the deleted tickets list).

        Destructive: confirm with the user first. ``ticket_id`` accepts the
        raw integer ID or a dict/list from the ticket search/list tools.
        """
        resolved = self._extract_ticket_id(ticket_id)
        self._client.delete(f"/api/v2/tickets/{resolved}.json")
        return {"id": resolved, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def merge_tickets(
        self,
        target_ticket_id: Any,
        source_ticket_ids: list[Any],
        *,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """Merge ``source_ticket_ids`` into ``target_ticket_id``.

        Each ID may be a raw integer or a dict from the ticket search/list
        tools.
        """
        resolved_target = self._extract_ticket_id(target_ticket_id)
        if not source_ticket_ids:
            raise ValueError("source_ticket_ids must contain at least one id")
        resolved_sources = [self._extract_ticket_id(item) for item in source_ticket_ids]
        payload: dict[str, Any] = {"ids": resolved_sources}
        if comment is not None:
            payload["target_comment"] = comment
            payload["source_comment"] = comment
        return self._client.post(
            f"/api/v2/tickets/{resolved_target}/merge.json",
            json=payload,
        ).json()

    # MARK: - Users

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_users(
        self,
        *,
        role: str | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        """List users (optionally narrowed by ``role``)."""
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if role is not None:
            params["role"] = role
        return self._client.get("/api/v2/users.json", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_users(
        self,
        query: str,
        *,
        page: int = 1,
        per_page: int = 25,
    ) -> dict[str, Any]:
        """Search users by name, email, or role using the search endpoint."""
        if not query:
            raise ValueError("query must be a non-empty string")
        return self.search_tickets(
            query=f"type:user {query}",
            page=page,
            per_page=per_page,
            sort_by=None,
            sort_order="desc",
            include_metadata=False,
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_user(
        self,
        *,
        name: str,
        email: str,
        role: str = "end-user",
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a user."""
        if not name or not email:
            raise ValueError("name and email must be non-empty")
        user: dict[str, Any] = {"name": name, "email": email, "role": role}
        if extra_fields is not None:
            user.update(extra_fields)
        return self._client.post("/api/v2/users.json", json={"user": user}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_user(self, user_id: int, patch: dict[str, Any]) -> dict[str, Any]:
        """Patch user fields."""
        if not patch:
            raise ValueError("patch must be a non-empty dict")
        return self._client.put(
            f"/api/v2/users/{int(user_id)}.json",
            json={"user": patch},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_user(self, user_id: int) -> dict[str, Any]:
        """Delete a user.

        Destructive: confirm with the user first.
        """
        self._client.delete(f"/api/v2/users/{int(user_id)}.json")
        return {"id": int(user_id), "deleted": True}

    # MARK: - Organizations & groups

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_organizations(
        self,
        *,
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        """List organizations."""
        return self._client.get(
            "/api/v2/organizations.json",
            params={"page": page, "per_page": per_page},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_organization(self, organization_id: int) -> dict[str, Any]:
        """Return one organization by ID."""
        return self._client.get(f"/api/v2/organizations/{int(organization_id)}.json").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_organization(
        self,
        *,
        name: str,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an organization."""
        if not name:
            raise ValueError("name must be a non-empty string")
        org: dict[str, Any] = {"name": name}
        if extra_fields is not None:
            org.update(extra_fields)
        return self._client.post("/api/v2/organizations.json", json={"organization": org}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_groups(
        self,
        *,
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        """List agent groups."""
        return self._client.get(
            "/api/v2/groups.json",
            params={"page": page, "per_page": per_page},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_group(self, group_id: int) -> dict[str, Any]:
        """Return one group by ID."""
        return self._client.get(f"/api/v2/groups/{int(group_id)}.json").json()

    # MARK: - Macros & views

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_macros(
        self,
        *,
        active: bool | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        """List macros, optionally narrowed by ``active`` state."""
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if active is not None:
            params["active"] = str(active).lower()
        return self._client.get("/api/v2/macros.json", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def show_macro_application(
        self,
        ticket_id: int,
        macro_id: int,
    ) -> dict[str, Any]:
        """Preview the changes a macro would apply to a ticket (no write)."""
        return self._client.get(
            f"/api/v2/tickets/{int(ticket_id)}/macros/{int(macro_id)}/apply.json"
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_views(
        self,
        *,
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        """List ticket views."""
        return self._client.get(
            "/api/v2/views.json",
            params={"page": page, "per_page": per_page},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def execute_view(
        self,
        view_id: int,
        *,
        page: int = 1,
        per_page: int = 25,
    ) -> dict[str, Any]:
        """Return the tickets that match a saved view."""
        return self._client.get(
            f"/api/v2/views/{int(view_id)}/execute.json",
            params={"page": page, "per_page": per_page},
        ).json()

    # MARK: - Tags & metadata

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_ticket_fields(self) -> dict[str, Any]:
        """List all ticket field definitions."""
        return self._client.get("/api/v2/ticket_fields.json").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_user_fields(self) -> dict[str, Any]:
        """List custom user-field definitions."""
        return self._client.get("/api/v2/user_fields.json").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_tags_to_ticket(self, ticket_id: int, tags: list[str]) -> dict[str, Any]:
        """Append tags to a ticket."""
        if not tags:
            raise ValueError("tags must contain at least one value")
        return self._client.put(
            f"/api/v2/tickets/{int(ticket_id)}/tags.json",
            json={"tags": list(tags)},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def remove_tags_from_ticket(self, ticket_id: int, tags: list[str]) -> dict[str, Any]:
        """Remove tags from a ticket."""
        if not tags:
            raise ValueError("tags must contain at least one value")
        return self._client.delete(
            f"/api/v2/tickets/{int(ticket_id)}/tags.json",
            json={"tags": list(tags)},
        ).json()

    # MARK: - Internal

    @staticmethod
    def _summarize_tickets(
        payload: dict[str, Any],
        *,
        source_key: str,
        include_ids: bool,
    ) -> dict[str, Any]:
        items: list[Any] = payload.get(source_key, []) or []
        summaries: list[dict[str, Any]] = []
        index = 0
        for raw in items:
            if not isinstance(raw, dict):
                continue
            raw_dict = cast(dict[str, Any], raw)
            # Filter to ticket-shaped objects when reading a heterogeneous
            # search response (search endpoint may include users etc.).
            if source_key == "results":
                result_type: Any = raw_dict.get("result_type") or raw_dict.get("type")
                if result_type not in (None, "ticket"):
                    continue
            index += 1
            summary: dict[str, Any] = {
                "ticket_ref": f"ticket_{index}",
                "subject": raw_dict.get("subject", ""),
                "status": raw_dict.get("status", ""),
                "priority": raw_dict.get("priority", ""),
                "requester_id": raw_dict.get("requester_id", ""),
                "updated_at": raw_dict.get("updated_at", ""),
                "tags": raw_dict.get("tags", []) or [],
            }
            if include_ids:
                summary["ticket_id"] = raw_dict.get("id", "")
            summaries.append(summary)
        result: dict[str, Any] = {"tickets": summaries}
        for cursor_key in ("next_page", "previous_page", "count"):
            if cursor_key in payload:
                result[cursor_key] = payload[cursor_key]
        return result

    @staticmethod
    def _extract_ticket_id(candidate: Any) -> int:
        """Pull a Zendesk ticket ID from an arbitrary value.

        Accepts a raw integer, a numeric string, a dict returned by
        :meth:`search_tickets`/:meth:`list_tickets`, or a list containing
        such dicts.
        """
        if isinstance(candidate, bool):
            raise ValueError(f"ticket id must be an integer, got bool: {candidate!r}")
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, str):
            try:
                return int(candidate)
            except ValueError as exc:
                raise ValueError(f"ticket id must be numeric, got: {candidate!r}") from exc
        if isinstance(candidate, dict):
            candidate_dict = cast(dict[str, Any], candidate)
            for key in ("ticket_id", "id"):
                value: Any = candidate_dict.get(key)
                if value is not None:
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        continue
        if isinstance(candidate, list | tuple):
            candidate_seq = cast("list[Any] | tuple[Any, ...]", candidate)
            for item in candidate_seq:
                try:
                    return ZendeskToolSet._extract_ticket_id(item)
                except ValueError:
                    continue
        raise ValueError(f"could not extract Zendesk ticket id from: {candidate!r}")
