"""HashiCorp Vault HTTP API connector (KV v2 + transit)."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport


@toolset(prefix="vault")
class VaultToolSet:
    """A connector for HashiCorp Vault.

    Args:
        base_url: Vault address (e.g. ``"https://vault.example:8200"``).
        token: Vault token.
        namespace: Optional enterprise namespace.
    """

    metadata = ProviderMetadata(
        name="vault",
        display_name="HashiCorp Vault",
        version="0.1.0",
        description="KV v2 secrets, leases, transit encrypt/decrypt, and token ops.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.hashicorp.com/vault/api-docs",
        homepage_url="https://www.vaultproject.io/",
        tags=("security", "secrets"),
    )

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        namespace: str | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not base_url or not token:
            raise ValueError("base_url and token are required")
        self.connection = connection
        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if namespace is not None:
            headers["X-Vault-Namespace"] = namespace
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(token, header="X-Vault-Token"),
            transport=transport,
            default_headers=headers,
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_health(self) -> dict[str, Any]:
        """Return Vault seal / standby / sealed status.

        Useful as a first call to confirm Vault is reachable and unsealed
        before issuing data-plane requests.
        """
        return self._client.get("/v1/sys/health").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_mounts(self) -> dict[str, Any]:
        """List mounted secrets engines.

        Returns the raw mounts payload — each key is a mount path (e.g.
        ``"secret/"``) and the value carries the engine ``type``,
        ``description``, and options. The mount path is what you pass as
        ``mount`` to kv_* tools (strip the trailing slash).
        """
        return self._client.get("/v1/sys/mounts").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def kv_get(
        self,
        *,
        mount: str,
        path: str,
        version: int | None = None,
    ) -> dict[str, Any]:
        """Read a KV v2 secret (returns the secret value).

        Returns Vault's raw KV v2 payload — ``data.data`` is the secret
        material itself. Treat this as sensitive: do not echo into a
        final user-facing answer.
        """
        if not mount or not path:
            raise ValueError("mount and path are required")
        params: dict[str, Any] = {}
        if version is not None:
            params["version"] = version
        return self._client.get(f"/v1/{mount}/data/{path}", params=params or None).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def kv_put(
        self,
        *,
        mount: str,
        path: str,
        data: dict[str, Any],
        cas: int | None = None,
    ) -> dict[str, Any]:
        """Write (or upsert) a KV v2 secret.

        Returns Vault's response metadata. Use ``cas`` (check-and-set) to
        protect against lost-update races. Confirm with the user before
        overwriting an existing secret.
        """
        if not mount or not path or not data:
            raise ValueError("mount, path, and data are required")
        body: dict[str, Any] = {"data": data}
        if cas is not None:
            body["options"] = {"cas": cas}
        return self._client.post(f"/v1/{mount}/data/{path}", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def kv_patch(
        self,
        *,
        mount: str,
        path: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch (merge) fields into an existing KV v2 secret.

        Returns Vault's response metadata. Unlike kv_put this preserves
        unspecified fields.
        """
        if not mount or not path or not data:
            raise ValueError("mount, path, and data are required")
        return self._client.patch(
            f"/v1/{mount}/data/{path}",
            json={"data": data},
            headers={"Content-Type": "application/merge-patch+json"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def kv_delete(
        self,
        *,
        mount: str,
        path: str,
        versions: list[int] | None = None,
    ) -> dict[str, Any]:
        """Soft-delete versions of a KV v2 secret (reversible via undelete).

        Destructive — the secret stops responding to kv_get until
        undeleted. Confirm with the user. Returns Vault's response.
        """
        if not mount or not path:
            raise ValueError("mount and path are required")
        if versions is None:
            response = self._client.delete(f"/v1/{mount}/data/{path}")
            return {"status": response.status, "deleted": True}
        return self._client.post(f"/v1/{mount}/delete/{path}", json={"versions": versions}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def kv_destroy(
        self,
        *,
        mount: str,
        path: str,
        versions: list[int],
    ) -> dict[str, Any]:
        """Permanently destroy specific KV v2 versions (irreversible).

        Destructive and unrecoverable. Confirm with the user before
        calling. Returns Vault's response.
        """
        if not mount or not path or not versions:
            raise ValueError("mount, path, and versions are required")
        return self._client.post(f"/v1/{mount}/destroy/{path}", json={"versions": versions}).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def kv_list(
        self,
        *,
        mount: str,
        path: str,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List child keys (secret names) under a KV v2 path.

        Best first tool for discovering secrets. Returns
        ``{"secrets": [{"secret_ref": ..., "key": ...}, ...]}``. NEVER
        returns secret values — only the names of child keys. Set
        ``include_ids=True`` to also include the full ``path`` for each
        key (useful for follow-up kv_get calls).
        """
        if not mount or not path:
            raise ValueError("mount and path are required")
        payload: object = self._client.get(
            f"/v1/{mount}/metadata/{path}", params={"list": "true"}
        ).json()
        keys: list[str] = []
        if isinstance(payload, dict):
            data: object = cast("dict[str, Any]", payload).get("data")
            if isinstance(data, dict):
                raw_keys: object = cast("dict[str, Any]", data).get("keys")
                if isinstance(raw_keys, list):
                    raw_keys_list = cast("list[Any]", raw_keys)
                    keys = [k for k in raw_keys_list if isinstance(k, str)]
        base_path = path.rstrip("/")
        summaries: list[dict[str, Any]] = []
        for index, key in enumerate(keys, start=1):
            entry: dict[str, Any] = {
                "secret_ref": f"secret_{index}",
                "key": key,
                "is_directory": key.endswith("/"),
            }
            if include_ids:
                entry["path"] = f"{base_path}/{key}".lstrip("/") if base_path else key
            summaries.append(entry)
        return {"secrets": summaries, "mount": mount, "path": path}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def lookup_token_self(self) -> dict[str, Any]:
        """Return metadata for the current Vault token.

        Returns ``data`` with token policies, TTL, accessor, and renewable
        flag. Useful for verifying the token has the expected scope before
        issuing privileged calls.
        """
        return self._client.get("/v1/auth/token/lookup-self").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def renew_token_self(self, *, increment: str | None = None) -> dict[str, Any]:
        """Renew the current Vault token.

        ``increment`` is a duration string (``"24h"``, ``"30m"``). Returns
        the renewed lease info.
        """
        body: dict[str, Any] = {}
        if increment is not None:
            body["increment"] = increment
        return self._client.post("/v1/auth/token/renew-self", json=body or None).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def transit_encrypt(
        self,
        *,
        mount: str,
        key_name: str,
        plaintext: str,
        context: str | None = None,
    ) -> dict[str, Any]:
        """Encrypt a base64 plaintext via Vault's transit engine.

        ``plaintext`` MUST be base64-encoded (Vault transit requires that).
        Returns ``{"data": {"ciphertext": "vault:v1:..."}}``.
        """
        if not mount or not key_name or not plaintext:
            raise ValueError("mount, key_name, and plaintext are required")
        body: dict[str, Any] = {"plaintext": plaintext}
        if context is not None:
            body["context"] = context
        return self._client.post(f"/v1/{mount}/encrypt/{key_name}", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def transit_decrypt(
        self,
        *,
        mount: str,
        key_name: str,
        ciphertext: str,
        context: str | None = None,
    ) -> dict[str, Any]:
        """Decrypt a transit ciphertext.

        Returns ``{"data": {"plaintext": "<base64>"}}``. Decode the
        plaintext with ``base64.b64decode`` to get the original bytes.
        Treat the result as sensitive.
        """
        if not mount or not key_name or not ciphertext:
            raise ValueError("mount, key_name, and ciphertext are required")
        body: dict[str, Any] = {"ciphertext": ciphertext}
        if context is not None:
            body["context"] = context
        return self._client.post(f"/v1/{mount}/decrypt/{key_name}", json=body).json()
