"""1Password Connect REST API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="onepassword")
class OnePasswordToolSet:
    """A connector for the 1Password Connect REST API.

    Args:
        base_url: Connect server URL (e.g.
            ``"https://op-connect.example.com"``).
        access_token: Connect access token.
    """

    metadata = ProviderMetadata(
        name="onepassword",
        display_name="1Password Connect",
        version="0.1.0",
        description="Vaults and items via 1Password Connect.",
        auth_modes=(AuthMode.BEARER,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.1password.com/docs/connect/",
        homepage_url="https://1password.com/",
        tags=("security", "secrets", "passwords"),
    )

    def __init__(
        self,
        *,
        base_url: str,
        access_token: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not base_url or not access_token:
            raise ValueError("base_url and access_token are required")
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

    # MARK: - Summary helpers

    @staticmethod
    def _dict_list(payload: object) -> list[dict[str, Any]]:
        """Coerce a JSON payload into a list of dicts, dropping non-dicts."""
        if not isinstance(payload, list):
            return []
        items = cast("list[object]", payload)
        return [cast("dict[str, Any]", entry) for entry in items if isinstance(entry, dict)]

    @staticmethod
    def _vault_summary(
        vault: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "vault_ref": f"vault_{index}",
            "name": vault.get("name", ""),
            "description": vault.get("description", ""),
            "type": vault.get("type", ""),
            "item_count": vault.get("items", 0),
        }
        if include_ids:
            summary["vault_id"] = vault.get("id", "")
        return summary

    @staticmethod
    def _item_summary(
        item: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        # Strip any value-bearing fields if they leak in — list endpoints
        # only return metadata, but be defensive.
        summary: dict[str, Any] = {
            "item_ref": f"item_{index}",
            "title": item.get("title", ""),
            "category": item.get("category", ""),
            "tags": list(item.get("tags", []) or []),
            "updated_at": item.get("updatedAt", ""),
        }
        urls: object = item.get("urls")
        if isinstance(urls, list) and urls:
            first: object = cast("list[object]", urls)[0]
            if isinstance(first, dict):
                first_dict = cast("dict[str, Any]", first)
                summary["primary_url"] = first_dict.get("href", "")
        if include_ids:
            summary["item_id"] = item.get("id", "")
            vault_meta: object = item.get("vault")
            if isinstance(vault_meta, dict):
                vault_meta_dict = cast("dict[str, Any]", vault_meta)
                summary["vault_id"] = vault_meta_dict.get("id", "")
        return summary

    @staticmethod
    def _resolve_vault_id(vault_or_id: Any) -> str:
        if isinstance(vault_or_id, str) and vault_or_id:
            return vault_or_id
        if isinstance(vault_or_id, dict):
            vault_dict = cast("dict[str, Any]", vault_or_id)
            for key in ("vault_id", "id"):
                value: object = vault_dict.get(key)
                if isinstance(value, str) and value:
                    return value
        raise ValueError("expected a vault id string or a vault dict with 'id'")

    @staticmethod
    def _resolve_item_id(item_or_id: Any) -> str:
        if isinstance(item_or_id, str) and item_or_id:
            return item_or_id
        if isinstance(item_or_id, dict):
            item_dict = cast("dict[str, Any]", item_or_id)
            for key in ("item_id", "id"):
                value: object = item_dict.get(key)
                if isinstance(value, str) and value:
                    return value
        raise ValueError("expected an item id string or an item dict with 'id'")

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_vaults(
        self,
        *,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List vaults the Connect token can access.

        Returns ``{"vaults": [...]}`` with ``vault_ref``, ``name``,
        ``description``, ``type``, and ``item_count``. Raw ``vault_id``
        values are omitted by default — set ``include_ids=True`` when a
        follow-up tool needs them.
        """
        payload: object = self._client.get("/v1/vaults").json()
        raw_vaults = self._dict_list(payload)
        summaries = [
            self._vault_summary(vault, index=index, include_ids=include_ids)
            for index, vault in enumerate(raw_vaults, start=1)
        ]
        return {"vaults": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_vault(self, vault_id: str) -> dict[str, Any]:
        """Return one vault's full metadata by id.

        Returns the raw vault resource (``id``, ``name``, ``description``,
        ``attributeVersion``, ``contentVersion``, ``items``).
        """
        if not vault_id:
            raise ValueError("vault_id is required")
        return self._client.get(f"/v1/vaults/{vault_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_items(
        self,
        vault_id: Any,
        *,
        filter: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List items in a vault (metadata only — NEVER secret values).

        ``vault_id`` accepts a vault id string or a vault dict. Returns
        ``{"items": [...]}`` with ``item_ref``, ``title``, ``category``,
        ``tags``, ``updated_at``, and (when present) ``primary_url``. The
        actual secret fields (password, credit card number, etc.) are
        intentionally not part of this response — use get_item with
        ``include_ids=True`` ids when you specifically need a value.
        """
        resolved_id = self._resolve_vault_id(vault_id)
        params: dict[str, Any] = {}
        if filter is not None:
            params["filter"] = filter
        payload: object = self._client.get(
            f"/v1/vaults/{resolved_id}/items", params=params or None
        ).json()
        raw_items = self._dict_list(payload)
        summaries = [
            self._item_summary(item, index=index, include_ids=include_ids)
            for index, item in enumerate(raw_items, start=1)
        ]
        return {"items": summaries, "vault_id": resolved_id}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_item(self, *, vault_id: Any, item_id: Any) -> dict[str, Any]:
        """Return a single item with all fields (including secret values).

        Both ``vault_id`` and ``item_id`` accept dict or string. The full
        item payload includes password/notes/totp/etc. Treat the result
        as sensitive — do not echo into a final user-facing answer.
        """
        resolved_vault_id = self._resolve_vault_id(vault_id)
        resolved_item_id = self._resolve_item_id(item_id)
        return self._client.get(f"/v1/vaults/{resolved_vault_id}/items/{resolved_item_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_item(
        self,
        vault_id: Any,
        *,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        """Create an item in a vault.

        Returns the new item resource. Confirm with the user before
        storing new secrets.
        """
        resolved_vault_id = self._resolve_vault_id(vault_id)
        if not item:
            raise ValueError("item is required")
        return self._client.post(f"/v1/vaults/{resolved_vault_id}/items", json=item).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_item(
        self,
        *,
        vault_id: Any,
        item_id: Any,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        """Fully replace an item.

        Returns the updated item resource. Replace is total — any field
        you omit is removed. Use patch_item for targeted edits.
        """
        resolved_vault_id = self._resolve_vault_id(vault_id)
        resolved_item_id = self._resolve_item_id(item_id)
        if not item:
            raise ValueError("item is required")
        return self._client.put(
            f"/v1/vaults/{resolved_vault_id}/items/{resolved_item_id}", json=item
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def patch_item(
        self,
        *,
        vault_id: Any,
        item_id: Any,
        ops: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply JSON Patch operations to an item.

        Returns the updated item. Each op is ``{"op": "add|replace|remove",
        "path": "/...", "value": ...}``.
        """
        resolved_vault_id = self._resolve_vault_id(vault_id)
        resolved_item_id = self._resolve_item_id(item_id)
        if not ops:
            raise ValueError("ops is required")
        return self._client.patch(
            f"/v1/vaults/{resolved_vault_id}/items/{resolved_item_id}",
            json=ops,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_item(self, *, vault_id: Any, item_id: Any) -> dict[str, Any]:
        """Permanently delete an item.

        Destructive — the secret cannot be recovered. Confirm with the
        user. Returns ``{"item_id": ..., "deleted": True, "status": ...}``.
        """
        resolved_vault_id = self._resolve_vault_id(vault_id)
        resolved_item_id = self._resolve_item_id(item_id)
        response = self._client.delete(f"/v1/vaults/{resolved_vault_id}/items/{resolved_item_id}")
        return {"item_id": resolved_item_id, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_item_files(
        self,
        *,
        vault_id: Any,
        item_id: Any,
    ) -> dict[str, Any]:
        """List file attachments on an item.

        Returns the raw file list (each entry has ``id``, ``name``,
        ``size``, ``content_path``).
        """
        resolved_vault_id = self._resolve_vault_id(vault_id)
        resolved_item_id = self._resolve_item_id(item_id)
        return self._client.get(
            f"/v1/vaults/{resolved_vault_id}/items/{resolved_item_id}/files"
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_heartbeat(self) -> dict[str, Any]:
        """Check the 1Password Connect server is alive.

        Returns ``{"status": ..., "alive": bool}``. Useful as a quick
        connectivity check.
        """
        response = self._client.get("/heartbeat")
        return {"status": response.status, "alive": response.status < 400}
