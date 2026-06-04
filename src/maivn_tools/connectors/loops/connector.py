"""Loops API v1 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="loops")
class LoopsToolSet:
    """A connector for the Loops API v1."""

    metadata = ProviderMetadata(
        name="loops",
        display_name="Loops",
        version="0.1.0",
        description="Transactional email, contacts, lists, and events.",
        auth_modes=(AuthMode.BEARER, AuthMode.API_KEY),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://loops.so/docs/api-reference",
        homepage_url="https://loops.so/",
        tags=("email", "transactional", "marketing"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://app.loops.so/api/v1",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(api_key),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @staticmethod
    def _list_summary(
        mlist: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "list_ref": f"list_{index}",
            "name": mlist.get("name", ""),
            "description": mlist.get("description", ""),
            "is_public": mlist.get("isPublic"),
        }
        if include_ids:
            summary["list_id"] = mlist.get("id", "")
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def api_key_info(self) -> dict[str, Any]:
        """Return info about the API key.

        Returns ``{"teamName": ..., "type": ...}`` — use to validate the
        key at startup.
        """
        return self._client.get("/api-key").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE), destructive=True)
    def send_transactional(
        self,
        *,
        transactional_id: str,
        email: str,
        data_variables: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send a transactional email by ``transactional_id``. Irreversible once sent.

        Marked destructive because emails cannot be unsent. Always confirm
        with the user first.
        """
        if not transactional_id or not email:
            raise ValueError("transactional_id and email must be non-empty")
        body: dict[str, Any] = {
            "transactionalId": transactional_id,
            "email": email,
        }
        if data_variables is not None:
            body["dataVariables"] = data_variables
        if attachments is not None:
            body["attachments"] = attachments
        return self._client.post("/transactional", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def find_contact(
        self,
        *,
        email: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Look up a contact by email or user ID.

        Exactly one of ``email`` or ``user_id`` may be supplied — the Loops
        ``/contacts/find`` endpoint allows only a single query parameter per
        request. Returns the contact resource (or an empty list if not found).
        """
        if not email and not user_id:
            raise ValueError("provide email or user_id")
        if email and user_id:
            raise ValueError("provide only one of email or user_id")
        params: dict[str, Any] = {}
        if email is not None:
            params["email"] = email
        if user_id is not None:
            params["userId"] = user_id
        return self._client.get("/contacts/find", params=params).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_contact(
        self,
        *,
        email: str,
        first_name: str | None = None,
        last_name: str | None = None,
        user_group: str | None = None,
        user_id: str | None = None,
        attributes: dict[str, Any] | None = None,
        mailing_lists: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        """Create a contact.

        Returns ``{"success": True, "id": ...}``.
        """
        if not email:
            raise ValueError("email must be a non-empty string")
        body: dict[str, Any] = {"email": email}
        if first_name is not None:
            body["firstName"] = first_name
        if last_name is not None:
            body["lastName"] = last_name
        if user_group is not None:
            body["userGroup"] = user_group
        if user_id is not None:
            body["userId"] = user_id
        if attributes is not None:
            body.update(attributes)
        if mailing_lists is not None:
            body["mailingLists"] = mailing_lists
        return self._client.post("/contacts/create", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_contact(self, *, email: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Update a contact's attributes.

        Returns ``{"success": True, "id": ...}``.
        """
        if not email or not fields:
            raise ValueError("email and fields must be non-empty")
        return self._client.put(
            "/contacts/update",
            json={"email": email, **fields},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_contact(
        self,
        *,
        email: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Permanently delete a contact by email or user ID. Destructive — confirm first.

        Unsubscribes the contact from future emails.
        """
        if not email and not user_id:
            raise ValueError("provide email or user_id")
        body: dict[str, Any] = {}
        if email is not None:
            body["email"] = email
        if user_id is not None:
            body["userId"] = user_id
        return self._client.post("/contacts/delete", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_mailing_lists(
        self,
        *,
        include_ids: bool = False,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        """List mailing lists with compact summaries.

        Returns compact summaries with ``list_ref`` plus name,
        description, is_public. Raw list IDs are omitted by default.
        """
        payload: Any = self._client.get("/lists").json()
        if include_raw:
            return payload
        lists = cast(
            "list[Any]",
            payload if isinstance(payload, list) else (payload.get("lists") or []),
        )
        summaries: list[dict[str, Any]] = [
            self._list_summary(cast("dict[str, Any]", lst), index=i, include_ids=include_ids)
            for i, lst in enumerate(lists, start=1)
            if isinstance(lst, dict)
        ]
        return {"lists": summaries, "count": len(summaries)}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def send_event(
        self,
        *,
        email: str | None = None,
        user_id: str | None = None,
        event_name: str,
        event_properties: dict[str, Any] | None = None,
        mailing_lists: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        """Send a tracking event for a contact.

        Events drive Loops workflows.
        """
        if not event_name:
            raise ValueError("event_name must be a non-empty string")
        if not email and not user_id:
            raise ValueError("provide email or user_id")
        body: dict[str, Any] = {"eventName": event_name}
        if email is not None:
            body["email"] = email
        if user_id is not None:
            body["userId"] = user_id
        if event_properties is not None:
            body["eventProperties"] = event_properties
        if mailing_lists is not None:
            body["mailingLists"] = mailing_lists
        return self._client.post("/events/send", json=body).json()
