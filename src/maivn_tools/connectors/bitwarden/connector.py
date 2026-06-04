"""Bitwarden Secrets Manager connector (via the Bitwarden SDK-server)."""
# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: - Constants

# Path prefix the SDK-server mounts every secret route under.
_API_PREFIX = "/rest/api/1"

# Headers the SDK-server's Warden middleware reads to build the per-request
# authenticated Bitwarden client. The access token is supplied here (NOT as a
# raw bearer token to api.bitwarden.com): the SDK-server performs the OAuth2
# client_credentials exchange against identity.bitwarden.com and the
# client-side decryption, then returns plaintext over its local REST API.
_HEADER_ACCESS_TOKEN = "Warden-Access-Token"
_HEADER_API_URL = "Warden-Api-Url"
_HEADER_IDENTITY_URL = "Warden-Identity-Url"
_HEADER_STATE_PATH = "Warden-State-Path"


@toolset(prefix="bitwarden")
class BitwardenToolSet:
    """A connector for Bitwarden Secrets Manager via the Bitwarden SDK-server.

    Bitwarden Secrets Manager is end-to-end encrypted and exposes no
    first-party plaintext REST surface. The supported programmatic path is
    the Bitwarden SDK-server (``external-secrets/bitwarden-sdk-server``, the
    REST wrapper around the Bitwarden Rust SDK used by the External Secrets
    Operator). The SDK-server accepts the machine-account access token,
    performs the OAuth2 ``client_credentials`` exchange at
    ``identity.bitwarden.com`` AND the client-side decryption, and serves
    plaintext secrets over a local REST API.

    This connector therefore requires a running SDK-server reachable at
    ``base_url``. It does NOT talk to ``api.bitwarden.com`` directly.

    The SDK-server exposes SECRET operations only (it wraps the SDK's
    ``Secrets()`` interface); it does NOT expose project routes. Projects are
    referenced only via the ``project_ids`` field on secrets.

    Args:
        access_token: Machine-account access token. Sent to the SDK-server in
            the ``Warden-Access-Token`` header.
        organization_id: Organization ID associated with the access token.
            Sent in the request body of list/create/update calls.
        base_url: SDK-server root (default ``"http://localhost:9998"``).
        api_url: Optional override for the Bitwarden API URL the SDK-server
            should use (``Warden-Api-Url`` header). Defaults to the
            SDK-server's own default when omitted.
        identity_url: Optional override for the Bitwarden identity URL the
            SDK-server should use (``Warden-Identity-Url`` header).
        state_path: Optional SDK-server state-file path
            (``Warden-State-Path`` header).
    """

    metadata = ProviderMetadata(
        name="bitwarden",
        display_name="Bitwarden Secrets Manager",
        version="0.2.0",
        description=(
            "Secrets in Bitwarden Secrets Manager via the Bitwarden SDK-server "
            "(local REST wrapper around the Bitwarden Rust SDK). Requires a "
            "running SDK-server; does not talk to api.bitwarden.com directly."
        ),
        auth_modes=(AuthMode.SERVICE_ACCOUNT,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://github.com/external-secrets/bitwarden-sdk-server",
        homepage_url="https://bitwarden.com/",
        tags=("security", "secrets", "sdk-server"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        organization_id: str,
        base_url: str = "http://localhost:9998",
        api_url: str | None = None,
        identity_url: str | None = None,
        state_path: str | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token or not organization_id:
            raise ValueError("access_token and organization_id are required")
        self.connection = connection
        self._org_id = organization_id
        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            _HEADER_ACCESS_TOKEN: access_token,
        }
        if api_url:
            headers[_HEADER_API_URL] = api_url
        if identity_url:
            headers[_HEADER_IDENTITY_URL] = identity_url
        if state_path:
            headers[_HEADER_STATE_PATH] = state_path
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            transport=transport,
            default_headers=headers,
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Summary helpers

    @staticmethod
    def _secret_summary(
        secret: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        # CRITICAL: never include "value" in the summary. The SDK-server's
        # list route (SecretIdentifiersResponse) returns id/key/organizationId/
        # projectIds only -- no value, note, or timestamps.
        summary: dict[str, Any] = {
            "secret_ref": f"secret_{index}",
            "key": secret.get("key", ""),
        }
        if include_ids:
            summary["secret_id"] = secret.get("id", "")
        return summary

    @staticmethod
    def _resolve_secret_ids(secrets: Any) -> list[str]:
        if isinstance(secrets, str) and secrets:
            return [secrets]
        if isinstance(secrets, dict):
            secret_dict = cast(dict[str, Any], secrets)
            for key in ("secret_id", "id"):
                value: Any = secret_dict.get(key)
                if isinstance(value, str) and value:
                    return [value]
        if isinstance(secrets, list):
            entries = cast(list[Any], secrets)
            ids: list[str] = []
            for entry in entries:
                if isinstance(entry, str) and entry:
                    ids.append(entry)
                elif isinstance(entry, dict):
                    entry_dict = cast(dict[str, Any], entry)
                    for key in ("secret_id", "id"):
                        entry_value: Any = entry_dict.get(key)
                        if isinstance(entry_value, str) and entry_value:
                            ids.append(entry_value)
                            break
            if ids:
                return ids
        raise ValueError("expected secret id string(s) or secret dict(s) with 'id'")

    @staticmethod
    def _data_list(payload: Any) -> list[dict[str, Any]]:
        """Return the ``data`` list from an SDK-server list-style response."""
        if isinstance(payload, dict):
            data_field: Any = cast(dict[str, Any], payload).get("data", [])
            if isinstance(data_field, list):
                items = cast(list[Any], data_field)
                return [cast(dict[str, Any], s) for s in items if isinstance(s, dict)]
        return []

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_secrets(
        self,
        *,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List secrets accessible to the access token (metadata only).

        Calls ``GET /rest/api/1/secrets`` on the SDK-server with the
        organization id in the request body. Returns ``{"secrets": [...]}``
        with ``secret_ref`` and ``key``. NEVER returns the secret ``value``
        (the SDK-server's list route omits it entirely). Set
        ``include_ids=True`` when a follow-up tool needs raw ids. Use
        get_secret to read a specific secret's value.
        """
        payload: Any = self._client.get(
            f"{_API_PREFIX}/secrets",
            json={"organizationId": self._org_id},
        ).json()
        raw_secrets = self._data_list(payload)
        summaries = [
            self._secret_summary(secret, index=index, include_ids=include_ids)
            for index, secret in enumerate(raw_secrets, start=1)
        ]
        return {"secrets": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_secret(self, secret_id: Any) -> dict[str, Any]:
        """Return a single secret including the decrypted value.

        Calls ``GET /rest/api/1/secret`` with ``{"id": <secret_id>}``.
        ``secret_id`` accepts dict or string. Returns the decrypted secret
        resource (``id``, ``key``, ``value``, ``note``, ``organizationId``,
        ``projectId``, timestamps). Treat the result as sensitive -- do not
        echo into a final user-facing answer.
        """
        resolved = self._resolve_secret_ids(secret_id)
        return self._client.get(
            f"{_API_PREFIX}/secret",
            json={"id": resolved[0]},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_secrets_by_ids(self, secret_ids: Any) -> dict[str, Any]:
        """Return multiple decrypted secrets by id in one call.

        Calls ``GET /rest/api/1/secrets-by-ids`` with ``{"ids": [...]}``.
        ``secret_ids`` accepts id string(s) or secret dict(s). Returns
        ``{"data": [<secret>, ...]}`` where each entry is a decrypted secret
        resource. Treat the result as sensitive.
        """
        ids = self._resolve_secret_ids(secret_ids)
        return self._client.get(
            f"{_API_PREFIX}/secrets-by-ids",
            json={"ids": ids},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_secret(
        self,
        *,
        key: str,
        value: str,
        note: str | None = None,
        project_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a secret in the organization.

        Calls ``POST /rest/api/1/secret``. Returns the new (decrypted) secret
        resource. Confirm with the user before creating secrets that grant
        access to live systems.
        """
        if not key or not value:
            raise ValueError("key and value are required")
        body: dict[str, Any] = {
            "key": key,
            "value": value,
            "note": note if note is not None else "",
            "organizationId": self._org_id,
        }
        if project_ids is not None:
            body["projectIds"] = project_ids
        return self._client.post(f"{_API_PREFIX}/secret", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_secret(
        self,
        secret_id: Any,
        *,
        key: str | None = None,
        value: str | None = None,
        note: str | None = None,
        project_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update a secret. ``secret_id`` accepts dict or string.

        Calls ``PUT /rest/api/1/secret``. The SDK-server requires the full
        key/value/note on update, so any field left as ``None`` is sent as an
        empty string. Returns the updated (decrypted) secret resource.
        Confirm with the user before rotating production values.
        """
        resolved = self._resolve_secret_ids(secret_id)
        if key is None and value is None and note is None and project_ids is None:
            raise ValueError("at least one update field is required")
        body: dict[str, Any] = {
            "id": resolved[0],
            "key": key if key is not None else "",
            "value": value if value is not None else "",
            "note": note if note is not None else "",
            "organizationId": self._org_id,
        }
        if project_ids is not None:
            body["projectIds"] = project_ids
        return self._client.put(f"{_API_PREFIX}/secret", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_secrets(self, secret_ids: Any) -> dict[str, Any]:
        """Delete one or more secrets.

        Calls ``DELETE /rest/api/1/secret`` with ``{"ids": [...]}``.
        ``secret_ids`` accepts a list of ids, a list of secret dicts, or a
        single id/dict. Destructive -- confirm with the user.
        """
        ids = self._resolve_secret_ids(secret_ids)
        return self._client.delete(f"{_API_PREFIX}/secret", json={"ids": ids}).json()
