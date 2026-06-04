"""Tests for identity / security connectors.

Auth0, Okta, Vault, 1Password Connect, Bitwarden Secrets Manager,
Doppler, Infisical, Snyk, Twilio, JumpCloud, OneLogin, Duo.
"""

# pyright: strict

from __future__ import annotations

import pytest
from maivn._internal.utils.toolset import get_toolify_options

from maivn_tools.connectors.auth0 import Auth0ToolSet
from maivn_tools.connectors.bitwarden import BitwardenToolSet
from maivn_tools.connectors.doppler import DopplerToolSet
from maivn_tools.connectors.duo import DuoToolSet
from maivn_tools.connectors.infisical import InfisicalToolSet
from maivn_tools.connectors.jumpcloud import JumpCloudToolSet
from maivn_tools.connectors.okta import OktaToolSet
from maivn_tools.connectors.onelogin import OneLoginToolSet
from maivn_tools.connectors.onepassword import OnePasswordToolSet
from maivn_tools.connectors.snyk import SnykToolSet
from maivn_tools.connectors.twilio import TwilioToolSet
from maivn_tools.connectors.vault import VaultToolSet
from maivn_tools.testing import MockTransport, json_response

# MARK: - Auth0


def _auth0() -> tuple[Auth0ToolSet, MockTransport]:
    transport = MockTransport()
    return (
        Auth0ToolSet(
            domain="tenant.us.auth0.com",
            access_token="t",
            transport=transport,
        ),
        transport,
    )


def test_auth0_requires_args() -> None:
    with pytest.raises(ValueError):
        Auth0ToolSet(domain="", access_token="t")
    with pytest.raises(ValueError):
        Auth0ToolSet(domain="d", access_token="")


def test_auth0_endpoints() -> None:
    connector, transport = _auth0()
    for _ in range(10):
        transport.enqueue(json_response({"id": "u"}))
    connector.list_users(
        q="email:*@example.com",
        page=0,
        per_page=50,
        include_totals=True,
        sort="created_at:1",
    )
    connector.get_user("auth0|abc")
    connector.create_user(
        connection="Username-Password-Authentication",
        email="a@b.com",
        username="alice",
        password="X1",
        user_metadata={"k": "v"},
        app_metadata={"k": "v"},
    )
    connector.update_user(
        "auth0|abc",
        blocked=True,
        email_verified=True,
        user_metadata={"k": "v"},
        app_metadata={"k": "v"},
    )
    connector.delete_user("auth0|abc")
    connector.list_roles()
    connector.assign_roles_to_user(user_id="u", role_ids=["r"])
    connector.list_connections(strategy="auth0")
    connector.list_clients()
    connector.list_organizations()
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert transport.requests[3].method == "PATCH"
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_user("")
    with pytest.raises(ValueError):
        connector.create_user(connection="")
    with pytest.raises(ValueError):
        connector.create_user(connection="c")
    with pytest.raises(ValueError):
        connector.update_user("")
    with pytest.raises(ValueError):
        connector.update_user("u")
    with pytest.raises(ValueError):
        connector.delete_user("")
    with pytest.raises(ValueError):
        connector.assign_roles_to_user(user_id="", role_ids=["r"])
    with pytest.raises(ValueError):
        connector.assign_roles_to_user(user_id="u", role_ids=[])


def test_auth0_logs() -> None:
    connector, transport = _auth0()
    transport.enqueue(json_response([]))
    connector.list_logs(q="type:s", page=0, per_page=50)


def test_auth0_list_users_returns_summary_without_ids() -> None:
    connector, transport = _auth0()
    transport.enqueue(
        json_response(
            {
                "users": [
                    {
                        "user_id": "auth0|abc",
                        "email": "a@b.com",
                        "name": "Alice",
                        "blocked": False,
                        "email_verified": True,
                        "last_login": "2026-05-01T00:00:00Z",
                        "logins_count": 7,
                    }
                ]
            }
        )
    )
    result = connector.list_users()
    assert result["users"] == [
        {
            "user_ref": "user_1",
            "email": "a@b.com",
            "name": "Alice",
            "blocked": False,
            "email_verified": True,
            "last_login": "2026-05-01T00:00:00Z",
            "logins_count": 7,
        }
    ]
    assert "user_id" not in result["users"][0]


def test_auth0_list_users_include_ids() -> None:
    connector, transport = _auth0()
    transport.enqueue(
        json_response(
            {
                "users": [
                    {
                        "user_id": "auth0|abc",
                        "email": "a@b.com",
                    }
                ]
            }
        )
    )
    result = connector.list_users(include_ids=True)
    assert result["users"][0]["user_id"] == "auth0|abc"


def test_auth0_list_roles_clients_orgs_connections_no_ids_by_default() -> None:
    connector, transport = _auth0()
    transport.enqueue(json_response([{"id": "rol_1", "name": "admin", "description": "x"}]))
    transport.enqueue(json_response([{"id": "con_1", "name": "DB", "strategy": "auth0"}]))
    transport.enqueue(json_response([{"client_id": "c1", "name": "App", "app_type": "spa"}]))
    transport.enqueue(json_response([{"id": "org_1", "name": "acme", "display_name": "Acme"}]))
    roles = connector.list_roles()
    connections = connector.list_connections()
    apps = connector.list_clients()
    orgs = connector.list_organizations()
    assert roles["roles"][0]["role_ref"] == "role_1"
    assert "role_id" not in roles["roles"][0]
    assert connections["connections"][0]["connection_ref"] == "connection_1"
    assert "connection_id" not in connections["connections"][0]
    assert apps["apps"][0]["app_ref"] == "app_1"
    assert "client_id" not in apps["apps"][0]
    assert orgs["organizations"][0]["org_ref"] == "org_1"
    assert "org_id" not in orgs["organizations"][0]


def test_auth0_update_user_accepts_user_dict() -> None:
    connector, transport = _auth0()
    transport.enqueue(json_response({"user_id": "auth0|abc"}))
    connector.update_user({"user_id": "auth0|abc"}, blocked=True)
    assert transport.requests[0].method == "PATCH"
    assert transport.requests[0].url.endswith("/api/v2/users/auth0%7Cabc")


def test_auth0_destructive_tagging() -> None:
    connector, _ = _auth0()
    opts = get_toolify_options(connector.delete_user)
    assert opts is not None and opts.destructive is True


# MARK: - Okta


def _okta() -> tuple[OktaToolSet, MockTransport]:
    transport = MockTransport()
    return (
        OktaToolSet(
            org_url="https://dev.okta.com",
            api_token="t",
            transport=transport,
        ),
        transport,
    )


def test_okta_requires_args() -> None:
    with pytest.raises(ValueError):
        OktaToolSet(org_url="", api_token="t")
    with pytest.raises(ValueError):
        OktaToolSet(org_url="x", api_token="")


def test_okta_users_and_groups() -> None:
    connector, transport = _okta()
    for _ in range(13):
        transport.enqueue(json_response({"id": "u"}))
    connector.list_users(
        q="alice",
        filter='status eq "ACTIVE"',
        search='profile.email eq "a@b"',
        limit=200,
        after="cur",
    )
    connector.get_user("00u1")
    connector.create_user(
        profile={"login": "a@b", "email": "a@b", "firstName": "A", "lastName": "B"},
        credentials={"password": {"value": "X"}},
        group_ids=["g1"],
        activate=True,
    )
    connector.update_user("00u1", profile={"firstName": "X"}, credentials={})
    connector.suspend_user("00u1")
    connector.unsuspend_user("00u1")
    connector.deactivate_user("00u1")
    connector.list_groups(q="x", filter='type eq "OKTA_GROUP"', limit=200, after="cur")
    connector.add_user_to_group(group_id="g1", user_id="u1")
    connector.remove_user_from_group(group_id="g1", user_id="u1")
    connector.list_applications(q="x", limit=200)
    connector.list_factors("u1")
    connector.list_system_logs(
        since="2026-01-01",
        until="2026-02-01",
        filter='eventType eq "x"',
        limit=100,
    )
    assert transport.requests[0].headers["Authorization"] == "SSWS t"
    assert transport.requests[8].method == "PUT"
    assert transport.requests[9].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_user("")
    with pytest.raises(ValueError):
        connector.create_user(profile={})
    with pytest.raises(ValueError):
        connector.update_user("")
    with pytest.raises(ValueError):
        connector.update_user("u")
    with pytest.raises(ValueError):
        connector.suspend_user("")
    with pytest.raises(ValueError):
        connector.unsuspend_user("")
    with pytest.raises(ValueError):
        connector.deactivate_user("")
    with pytest.raises(ValueError):
        connector.add_user_to_group(group_id="", user_id="u")
    with pytest.raises(ValueError):
        connector.remove_user_from_group(group_id="g", user_id="")
    with pytest.raises(ValueError):
        connector.list_factors("")


def test_okta_list_users_returns_summary_without_ids() -> None:
    connector, transport = _okta()
    transport.enqueue(
        json_response(
            [
                {
                    "id": "00u123",
                    "status": "ACTIVE",
                    "lastLogin": "2026-05-01T00:00:00Z",
                    "profile": {
                        "login": "alice@example.com",
                        "email": "alice@example.com",
                        "firstName": "Alice",
                        "lastName": "Smith",
                    },
                }
            ]
        )
    )
    result = connector.list_users()
    assert result["users"] == [
        {
            "user_ref": "user_1",
            "email": "alice@example.com",
            "name": "Alice Smith",
            "login": "alice@example.com",
            "status": "ACTIVE",
            "last_login": "2026-05-01T00:00:00Z",
        }
    ]
    assert "user_id" not in result["users"][0]


def test_okta_list_users_include_ids() -> None:
    connector, transport = _okta()
    transport.enqueue(json_response([{"id": "00u123", "profile": {"login": "alice@x"}}]))
    result = connector.list_users(include_ids=True)
    assert result["users"][0]["user_id"] == "00u123"


def test_okta_list_groups_and_apps_summaries() -> None:
    connector, transport = _okta()
    transport.enqueue(
        json_response([{"id": "g1", "type": "OKTA_GROUP", "profile": {"name": "Admins"}}])
    )
    transport.enqueue(
        json_response([{"id": "a1", "name": "app", "label": "App", "status": "ACTIVE"}])
    )
    groups = connector.list_groups()
    apps = connector.list_applications()
    assert groups["groups"][0]["group_ref"] == "group_1"
    assert groups["groups"][0]["name"] == "Admins"
    assert "group_id" not in groups["groups"][0]
    assert apps["apps"][0]["app_ref"] == "app_1"
    assert "app_id" not in apps["apps"][0]


def test_okta_update_user_accepts_dict() -> None:
    connector, transport = _okta()
    transport.enqueue(json_response({"id": "00u1"}))
    connector.update_user({"id": "00u1"}, profile={"firstName": "Alex"})
    assert transport.requests[0].url.endswith("/api/v1/users/00u1")


def test_okta_destructive_tagging() -> None:
    connector, _ = _okta()
    for method in (
        connector.suspend_user,
        connector.deactivate_user,
        connector.remove_user_from_group,
    ):
        opts = get_toolify_options(method)
        assert opts is not None and opts.destructive is True


# MARK: - Vault


def _vault() -> tuple[VaultToolSet, MockTransport]:
    transport = MockTransport()
    return (
        VaultToolSet(
            base_url="https://vault.example:8200",
            token="t",
            namespace="ns",
            transport=transport,
        ),
        transport,
    )


def test_vault_requires_args() -> None:
    with pytest.raises(ValueError):
        VaultToolSet(base_url="", token="t")
    with pytest.raises(ValueError):
        VaultToolSet(base_url="x", token="")


def test_vault_endpoints() -> None:
    connector, transport = _vault()
    for _ in range(12):
        transport.enqueue(json_response({"data": {}}))
    connector.get_health()
    connector.list_mounts()
    connector.kv_get(mount="secret", path="app/x", version=2)
    connector.kv_put(mount="secret", path="app/x", data={"k": "v"}, cas=0)
    connector.kv_patch(mount="secret", path="app/x", data={"k": "v2"})
    connector.kv_delete(mount="secret", path="app/x")
    connector.kv_delete(mount="secret", path="app/x", versions=[1, 2])
    connector.kv_destroy(mount="secret", path="app/x", versions=[1])
    connector.kv_list(mount="secret", path="app")
    connector.lookup_token_self()
    connector.renew_token_self(increment="24h")
    connector.transit_encrypt(mount="transit", key_name="k", plaintext="cGxhaW4=", context="Y3R4")
    assert transport.requests[0].headers["X-Vault-Token"] == "t"
    assert transport.requests[0].headers["X-Vault-Namespace"] == "ns"
    assert transport.requests[5].method == "DELETE"
    with pytest.raises(ValueError):
        connector.kv_get(mount="", path="p")
    with pytest.raises(ValueError):
        connector.kv_put(mount="m", path="p", data={})
    with pytest.raises(ValueError):
        connector.kv_patch(mount="", path="p", data={"k": 1})
    with pytest.raises(ValueError):
        connector.kv_delete(mount="", path="p")
    with pytest.raises(ValueError):
        connector.kv_destroy(mount="m", path="p", versions=[])
    with pytest.raises(ValueError):
        connector.kv_list(mount="", path="p")
    with pytest.raises(ValueError):
        connector.transit_encrypt(mount="", key_name="k", plaintext="x")
    with pytest.raises(ValueError):
        connector.transit_encrypt(mount="m", key_name="", plaintext="x")


def test_vault_transit_decrypt() -> None:
    connector, transport = _vault()
    transport.enqueue(json_response({"data": {"plaintext": "cGxhaW4="}}))
    connector.transit_decrypt(mount="transit", key_name="k", ciphertext="vault:v1:x")
    with pytest.raises(ValueError):
        connector.transit_decrypt(mount="", key_name="k", ciphertext="x")


def test_vault_kv_list_returns_metadata_only() -> None:
    """kv_list MUST NEVER return secret values — only key names."""
    connector, transport = _vault()
    transport.enqueue(json_response({"data": {"keys": ["api_key", "db_password", "subdir/"]}}))
    result = connector.kv_list(mount="secret", path="app")
    assert result["secrets"] == [
        {"secret_ref": "secret_1", "key": "api_key", "is_directory": False},
        {"secret_ref": "secret_2", "key": "db_password", "is_directory": False},
        {"secret_ref": "secret_3", "key": "subdir/", "is_directory": True},
    ]
    # No value-bearing keys leaked.
    for entry in result["secrets"]:
        for forbidden in ("value", "data", "plaintext", "secret", "password"):
            assert forbidden not in entry


def test_vault_kv_list_include_ids_adds_path() -> None:
    connector, transport = _vault()
    transport.enqueue(json_response({"data": {"keys": ["k1"]}}))
    result = connector.kv_list(mount="secret", path="app", include_ids=True)
    assert result["secrets"][0]["path"] == "app/k1"


def test_vault_destructive_tagging() -> None:
    connector, _ = _vault()
    for method in (connector.kv_delete, connector.kv_destroy):
        opts = get_toolify_options(method)
        assert opts is not None and opts.destructive is True


# MARK: - 1Password


def _onepassword() -> tuple[OnePasswordToolSet, MockTransport]:
    transport = MockTransport()
    return (
        OnePasswordToolSet(
            base_url="https://op.example",
            access_token="t",
            transport=transport,
        ),
        transport,
    )


def test_onepassword_requires_args() -> None:
    with pytest.raises(ValueError):
        OnePasswordToolSet(base_url="", access_token="t")
    with pytest.raises(ValueError):
        OnePasswordToolSet(base_url="u", access_token="")


def test_onepassword_endpoints() -> None:
    connector, transport = _onepassword()
    for _ in range(10):
        transport.enqueue(json_response({"id": "v"}))
    connector.list_vaults()
    connector.get_vault("v1")
    connector.list_items("v1", filter='title co "x"')
    connector.get_item(vault_id="v1", item_id="i1")
    connector.create_item("v1", item={"category": "LOGIN", "title": "t", "fields": []})
    connector.update_item(
        vault_id="v1",
        item_id="i1",
        item={"category": "LOGIN", "title": "t2", "fields": []},
    )
    connector.patch_item(
        vault_id="v1",
        item_id="i1",
        ops=[{"op": "replace", "path": "/title", "value": "x"}],
    )
    connector.delete_item(vault_id="v1", item_id="i1")
    connector.get_item_files(vault_id="v1", item_id="i1")
    connector.get_heartbeat()
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert transport.requests[5].method == "PUT"
    assert transport.requests[6].method == "PATCH"
    assert transport.requests[7].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_vault("")
    with pytest.raises(ValueError):
        connector.list_items("")
    with pytest.raises(ValueError):
        connector.get_item(vault_id="", item_id="i")
    with pytest.raises(ValueError):
        connector.create_item("", item={"x": 1})
    with pytest.raises(ValueError):
        connector.create_item("v", item={})
    with pytest.raises(ValueError):
        connector.update_item(vault_id="", item_id="i", item={"x": 1})
    with pytest.raises(ValueError):
        connector.patch_item(vault_id="v", item_id="i", ops=[])
    with pytest.raises(ValueError):
        connector.delete_item(vault_id="", item_id="i")
    with pytest.raises(ValueError):
        connector.get_item_files(vault_id="v", item_id="")


def test_onepassword_list_vaults_summary() -> None:
    connector, transport = _onepassword()
    transport.enqueue(
        json_response(
            [{"id": "vault_1", "name": "Engineering", "type": "USER_CREATED", "items": 23}]
        )
    )
    result = connector.list_vaults()
    assert result["vaults"][0] == {
        "vault_ref": "vault_1",
        "name": "Engineering",
        "description": "",
        "type": "USER_CREATED",
        "item_count": 23,
    }
    assert "vault_id" not in result["vaults"][0]


def test_onepassword_list_items_strips_secret_values() -> None:
    """list_items MUST NEVER return password/credit card/notesPlain values."""
    connector, transport = _onepassword()
    transport.enqueue(
        json_response(
            [
                {
                    "id": "item_1",
                    "title": "AWS prod",
                    "category": "LOGIN",
                    "tags": ["prod"],
                    "updatedAt": "2026-05-01T00:00:00Z",
                    "urls": [{"primary": True, "href": "https://aws.amazon.com"}],
                    "fields": [
                        {"label": "password", "value": "TOP-SECRET"},
                        {"label": "username", "value": "alice"},
                    ],
                }
            ]
        )
    )
    result = connector.list_items("v1")
    summary = result["items"][0]
    assert summary["item_ref"] == "item_1"
    assert summary["title"] == "AWS prod"
    assert summary["primary_url"] == "https://aws.amazon.com"
    # Verify no field values leaked.
    serialized = repr(result)
    assert "TOP-SECRET" not in serialized
    assert "fields" not in summary
    assert "value" not in summary


def test_onepassword_list_items_include_ids() -> None:
    connector, transport = _onepassword()
    transport.enqueue(json_response([{"id": "item_abc", "title": "x"}]))
    result = connector.list_items("v1", include_ids=True)
    assert result["items"][0]["item_id"] == "item_abc"


def test_onepassword_write_accepts_dict_input() -> None:
    connector, transport = _onepassword()
    transport.enqueue(json_response({"id": "x"}))
    connector.delete_item(vault_id={"id": "v1"}, item_id={"id": "i1"})
    assert transport.requests[0].url.endswith("/v1/vaults/v1/items/i1")


def test_onepassword_destructive_tagging() -> None:
    connector, _ = _onepassword()
    opts = get_toolify_options(connector.delete_item)
    assert opts is not None and opts.destructive is True


# MARK: - Bitwarden Secrets Manager


def _bitwarden() -> tuple[BitwardenToolSet, MockTransport]:
    transport = MockTransport()
    return (
        BitwardenToolSet(
            access_token="t",
            organization_id="org",
            transport=transport,
        ),
        transport,
    )


def test_bitwarden_requires_args() -> None:
    with pytest.raises(ValueError):
        BitwardenToolSet(access_token="", organization_id="o")
    with pytest.raises(ValueError):
        BitwardenToolSet(access_token="t", organization_id="")


def test_bitwarden_endpoints() -> None:
    connector, transport = _bitwarden()
    for _ in range(10):
        transport.enqueue(json_response({"id": "x"}))
    connector.list_secrets()
    connector.get_secret("s1")
    connector.get_secrets_by_ids(["s1", "s2"])
    connector.create_secret(
        key="API_KEY",
        value="v",
        note="n",
        project_ids=["p1"],
    )
    connector.update_secret(
        "s1",
        key="API_KEY2",
        value="v2",
        note="n2",
        project_ids=["p1"],
    )
    connector.delete_secrets(["s1"])
    with pytest.raises(ValueError):
        connector.get_secret("")
    with pytest.raises(ValueError):
        connector.get_secrets_by_ids([])
    with pytest.raises(ValueError):
        connector.create_secret(key="", value="v")
    with pytest.raises(ValueError):
        connector.create_secret(key="K", value="")
    with pytest.raises(ValueError):
        connector.update_secret("")
    with pytest.raises(ValueError):
        connector.update_secret("s")
    with pytest.raises(ValueError):
        connector.delete_secrets([])


def test_bitwarden_uses_sdk_server_contract() -> None:
    """The connector must drive the SDK-server: localhost:9998, the
    Warden-Access-Token header, the /rest/api/1 routes, and the org id in
    the request body (never a Bearer token to api.bitwarden.com)."""
    connector, transport = _bitwarden()
    for _ in range(5):
        transport.enqueue(json_response({"id": "x"}))
    connector.list_secrets()
    connector.get_secret("s1")
    connector.create_secret(key="K", value="v")
    connector.update_secret("s1", value="v2")
    connector.delete_secrets(["s1"])

    reqs = transport.requests
    # Every request targets the local SDK-server under /rest/api/1, never
    # api.bitwarden.com, and carries the access token in the Warden header.
    for req in reqs:
        assert req.url.startswith("http://localhost:9998/rest/api/1/")
        assert "api.bitwarden.com" not in req.url
        assert req.headers["Warden-Access-Token"] == "t"
        assert "Authorization" not in req.headers

    list_req, get_req, create_req, update_req, delete_req = reqs
    assert list_req.method == "GET"
    assert list_req.url.endswith("/rest/api/1/secrets")
    assert list_req.json_body == {"organizationId": "org"}

    assert get_req.method == "GET"
    assert get_req.url.endswith("/rest/api/1/secret")
    assert get_req.json_body == {"id": "s1"}

    assert create_req.method == "POST"
    assert create_req.url.endswith("/rest/api/1/secret")
    assert create_req.json_body == {
        "key": "K",
        "value": "v",
        "note": "",
        "organizationId": "org",
    }

    assert update_req.method == "PUT"
    assert update_req.url.endswith("/rest/api/1/secret")
    assert update_req.json_body == {
        "id": "s1",
        "key": "",
        "value": "v2",
        "note": "",
        "organizationId": "org",
    }

    assert delete_req.method == "DELETE"
    assert delete_req.url.endswith("/rest/api/1/secret")
    assert delete_req.json_body == {"ids": ["s1"]}


def test_bitwarden_list_secrets_never_returns_values() -> None:
    connector, transport = _bitwarden()
    # The SDK-server's list route (SecretIdentifiersResponse) returns only
    # id/key/organizationId/projectIds -- but defend against a value leaking
    # in regardless.
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "s1",
                        "key": "API_KEY",
                        "value": "SUPER-SECRET-DO-NOT-LEAK",
                        "organizationId": "org",
                        "projectIds": ["p1"],
                    }
                ]
            }
        )
    )
    result = connector.list_secrets()
    summary = result["secrets"][0]
    assert summary == {
        "secret_ref": "secret_1",
        "key": "API_KEY",
    }
    # Hard assertion: the secret value MUST NOT appear anywhere in the result.
    serialized = repr(result)
    assert "SUPER-SECRET" not in serialized
    assert "value" not in summary


def test_bitwarden_list_secrets_include_ids() -> None:
    connector, transport = _bitwarden()
    transport.enqueue(json_response({"data": [{"id": "s1", "key": "K"}]}))
    result = connector.list_secrets(include_ids=True)
    assert result["secrets"][0]["secret_id"] == "s1"


def test_bitwarden_get_secret_returns_decrypted_value() -> None:
    connector, transport = _bitwarden()
    transport.enqueue(
        json_response(
            {
                "id": "s1",
                "key": "API_KEY",
                "value": "decrypted-value",
                "note": "n",
                "organizationId": "org",
                "creationDate": "2026-04-01T00:00:00Z",
                "revisionDate": "2026-05-01T00:00:00Z",
            }
        )
    )
    result = connector.get_secret("s1")
    assert result["value"] == "decrypted-value"
    assert transport.requests[0].json_body == {"id": "s1"}


def test_bitwarden_delete_secrets_accepts_dict_list() -> None:
    connector, transport = _bitwarden()
    transport.enqueue(json_response({}))
    connector.delete_secrets([{"id": "s1"}, "s2"])
    body = transport.requests[0].json_body
    assert body == {"ids": ["s1", "s2"]}


def test_bitwarden_destructive_tagging() -> None:
    connector, _ = _bitwarden()
    opts = get_toolify_options(connector.delete_secrets)
    assert opts is not None and opts.destructive is True


# MARK: - Doppler


def _doppler() -> tuple[DopplerToolSet, MockTransport]:
    transport = MockTransport()
    return DopplerToolSet(token="t", transport=transport), transport


def test_doppler_requires_token() -> None:
    with pytest.raises(ValueError):
        DopplerToolSet(token="")


def test_doppler_endpoints() -> None:
    connector, transport = _doppler()
    for _ in range(8):
        transport.enqueue(json_response({"projects": []}))
    connector.list_projects(page=1, per_page=10)
    connector.create_project(name="p", description="d")
    connector.delete_project("p")
    connector.list_configs(project="p", environment="prd", page=1, per_page=10)
    connector.list_secrets(project="p", config="prd")
    connector.get_secret(project="p", config="prd", name="K")
    connector.update_secrets(project="p", config="prd", secrets={"K": "v"})
    connector.download_secrets(project="p", config="prd", format="env")
    with pytest.raises(ValueError):
        connector.create_project(name="")
    with pytest.raises(ValueError):
        connector.delete_project("")
    with pytest.raises(ValueError):
        connector.list_configs(project="")
    with pytest.raises(ValueError):
        connector.list_secrets(project="", config="x")
    with pytest.raises(ValueError):
        connector.list_secrets(project="p", config="")
    with pytest.raises(ValueError):
        connector.get_secret(project="", config="x", name="K")
    with pytest.raises(ValueError):
        connector.update_secrets(project="", config="x", secrets={"K": "v"})
    with pytest.raises(ValueError):
        connector.update_secrets(project="p", config="x", secrets={})
    with pytest.raises(ValueError):
        connector.download_secrets(project="", config="x")
    with pytest.raises(ValueError):
        connector.download_secrets(project="p", config="x", format="bogus")


def test_doppler_list_secrets_never_returns_values_by_default() -> None:
    connector, transport = _doppler()
    transport.enqueue(
        json_response(
            {
                "secrets": {
                    "DATABASE_URL": {
                        "raw": "postgres://prod-secret-value",
                        "computed": "postgres://prod-secret-value",
                        "note": "main db",
                        "type": {"type": "raw"},
                    },
                    "STRIPE_KEY": {
                        "raw": "sk_live_supersecret",
                        "computed": "sk_live_supersecret",
                    },
                }
            }
        )
    )
    result = connector.list_secrets(project="p", config="prd")
    keys = {s["key"] for s in result["secrets"]}
    assert keys == {"DATABASE_URL", "STRIPE_KEY"}
    # No secret values should appear anywhere in the result.
    serialized = repr(result)
    assert "postgres://prod-secret-value" not in serialized
    assert "sk_live_supersecret" not in serialized


def test_doppler_list_secrets_include_values_opt_in_returns_raw() -> None:
    connector, transport = _doppler()
    transport.enqueue(json_response({"secrets": {"K": {"raw": "v", "computed": "v"}}}))
    result = connector.list_secrets(project="p", config="prd", include_values=True)
    # With opt-in we return the raw Doppler payload.
    assert result["secrets"]["K"]["raw"] == "v"


def test_doppler_list_projects_summary() -> None:
    connector, transport = _doppler()
    transport.enqueue(
        json_response({"projects": [{"slug": "shop", "name": "Shop", "description": "x"}]})
    )
    result = connector.list_projects()
    assert result["projects"][0]["project_ref"] == "project_1"
    assert "project_slug" not in result["projects"][0]


def test_doppler_destructive_tagging() -> None:
    connector, _ = _doppler()
    opts = get_toolify_options(connector.delete_project)
    assert opts is not None and opts.destructive is True


# MARK: - Infisical


def _infisical() -> tuple[InfisicalToolSet, MockTransport]:
    transport = MockTransport()
    return (
        InfisicalToolSet(access_token="t", transport=transport),
        transport,
    )


def test_infisical_requires_token() -> None:
    with pytest.raises(ValueError):
        InfisicalToolSet(access_token="")


def test_infisical_endpoints() -> None:
    connector, transport = _infisical()
    for _ in range(7):
        transport.enqueue(json_response({"data": {}}))
    connector.list_projects(organization_id="org1")
    connector.get_project("w1")
    connector.list_secrets(workspace_id="w1", environment="dev", recursive=True)
    connector.get_secret("K", workspace_id="w1", environment="dev")
    connector.create_secret(
        "K",
        workspace_id="w1",
        environment="dev",
        secret_value="v",
        secret_comment="c",
    )
    connector.update_secret(
        "K",
        workspace_id="w1",
        environment="dev",
        secret_value="v2",
    )
    connector.delete_secret("K", workspace_id="w1", environment="dev")
    with pytest.raises(ValueError):
        connector.get_project("")
    with pytest.raises(ValueError):
        connector.list_secrets(workspace_id="", environment="d")
    with pytest.raises(ValueError):
        connector.get_secret("", workspace_id="w", environment="d")
    with pytest.raises(ValueError):
        connector.create_secret(
            "",
            workspace_id="w",
            environment="d",
            secret_value="v",
        )
    with pytest.raises(ValueError):
        connector.update_secret(
            "",
            workspace_id="w",
            environment="d",
            secret_value="v",
        )
    with pytest.raises(ValueError):
        connector.delete_secret("", workspace_id="w", environment="d")


def test_infisical_list_secrets_never_returns_values_by_default() -> None:
    connector, transport = _infisical()
    transport.enqueue(
        json_response(
            {
                "secrets": [
                    {
                        "id": "s1",
                        "secretKey": "API_KEY",
                        "secretValue": "PROD-SECRET-DO-NOT-LEAK",
                        "type": "shared",
                        "secretComment": "prod",
                        "secretPath": "/",
                        "updatedAt": "2026-05-01T00:00:00Z",
                    }
                ]
            }
        )
    )
    result = connector.list_secrets(workspace_id="w1", environment="dev")
    summary = result["secrets"][0]
    assert summary["secret_ref"] == "secret_1"
    assert summary["key"] == "API_KEY"
    assert "secretValue" not in summary
    assert "value" not in summary
    serialized = repr(result)
    assert "PROD-SECRET" not in serialized


def test_infisical_list_secrets_include_values_returns_raw() -> None:
    connector, transport = _infisical()
    transport.enqueue(json_response({"secrets": [{"secretKey": "K", "secretValue": "v"}]}))
    result = connector.list_secrets(workspace_id="w", environment="dev", include_values=True)
    assert result["secrets"][0]["secretValue"] == "v"


def test_infisical_list_projects_summary() -> None:
    connector, transport = _infisical()
    transport.enqueue(json_response({"workspaces": [{"id": "w1", "name": "App", "slug": "app"}]}))
    result = connector.list_projects(organization_id="org1")
    assert result["projects"][0]["project_ref"] == "project_1"
    assert "workspace_id" not in result["projects"][0]


def test_infisical_destructive_tagging() -> None:
    connector, _ = _infisical()
    opts = get_toolify_options(connector.delete_secret)
    assert opts is not None and opts.destructive is True


# MARK: - Snyk


def _snyk() -> tuple[SnykToolSet, MockTransport]:
    transport = MockTransport()
    return SnykToolSet(api_token="t", transport=transport), transport


def test_snyk_requires_token() -> None:
    with pytest.raises(ValueError):
        SnykToolSet(api_token="")


def test_snyk_endpoints() -> None:
    connector, transport = _snyk()
    for _ in range(8):
        transport.enqueue(json_response({"data": []}))
    connector.list_organizations(limit=10, starting_after="cur")
    connector.list_projects(org_id="org", limit=10, starting_after="cur")
    connector.get_project(org_id="org", project_id="p1")
    connector.list_issues(
        org_id="org",
        project_id="p1",
        limit=10,
        starting_after="cur",
        status=["open"],
    )
    connector.list_aggregated_issues(
        org_id="org",
        project_id="p1",
        filters={"severities": ["high"]},
    )
    connector.trigger_test(org_id="org", project_id="p1")
    connector.deactivate_project(org_id="org", project_id="p1")
    connector.list_dependencies(org_id="org", project_id="p1", page=1, per_page=10)
    assert transport.requests[0].headers["Authorization"] == "token t"
    with pytest.raises(ValueError):
        connector.list_projects(org_id="")
    with pytest.raises(ValueError):
        connector.get_project(org_id="", project_id="p")
    with pytest.raises(ValueError):
        connector.list_issues(org_id="o", project_id="")
    with pytest.raises(ValueError):
        connector.list_aggregated_issues(org_id="", project_id="p")
    with pytest.raises(ValueError):
        connector.trigger_test(org_id="o", project_id="")
    with pytest.raises(ValueError):
        connector.deactivate_project(org_id="", project_id="p")
    with pytest.raises(ValueError):
        connector.list_dependencies(org_id="")


def test_snyk_list_issues_summary_without_ids() -> None:
    connector, transport = _snyk()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "issue_abc",
                        "attributes": {
                            "title": "Prototype Pollution",
                            "effective_severity_level": "high",
                            "type": "package_vulnerability",
                            "status": "open",
                            "ignored": False,
                            "created_at": "2026-04-01T00:00:00Z",
                            "key": "SNYK-JS-LODASH-1018905",
                        },
                    }
                ]
            }
        )
    )
    result = connector.list_issues(org_id="org", project_id="p1")
    summary = result["vulns"][0]
    assert summary["vuln_ref"] == "vuln_1"
    assert summary["title"] == "Prototype Pollution"
    assert summary["severity"] == "high"
    assert "vuln_id" not in summary
    assert "key" not in summary


def test_snyk_list_issues_include_ids() -> None:
    connector, transport = _snyk()
    transport.enqueue(json_response({"data": [{"id": "issue_abc", "attributes": {"key": "k"}}]}))
    result = connector.list_issues(org_id="org", project_id="p1", include_ids=True)
    assert result["vulns"][0]["vuln_id"] == "issue_abc"
    assert result["vulns"][0]["key"] == "k"


def test_snyk_list_orgs_and_projects_summary() -> None:
    connector, transport = _snyk()
    transport.enqueue(json_response({"data": [{"id": "org_1", "attributes": {"name": "Acme"}}]}))
    transport.enqueue(
        json_response({"data": [{"id": "p1", "attributes": {"name": "Shop", "origin": "github"}}]})
    )
    orgs = connector.list_organizations()
    projects = connector.list_projects(org_id="org_1")
    assert orgs["organizations"][0]["org_ref"] == "org_1"
    assert "org_id" not in orgs["organizations"][0]
    assert projects["projects"][0]["project_ref"] == "project_1"
    assert "project_id" not in projects["projects"][0]


def test_snyk_destructive_tagging() -> None:
    connector, _ = _snyk()
    opts = get_toolify_options(connector.deactivate_project)
    assert opts is not None and opts.destructive is True


# MARK: - Twilio


def _twilio() -> tuple[TwilioToolSet, MockTransport]:
    transport = MockTransport()
    return (
        TwilioToolSet(
            account_sid="AC1",
            auth_token="t",
            transport=transport,
        ),
        transport,
    )


def test_twilio_requires_args() -> None:
    with pytest.raises(ValueError):
        TwilioToolSet(account_sid="", auth_token="t")
    with pytest.raises(ValueError):
        TwilioToolSet(account_sid="A", auth_token="")


def test_twilio_messaging_and_verify() -> None:
    connector, transport = _twilio()
    for _ in range(8):
        transport.enqueue(json_response({"sid": "M"}))
    connector.send_message(to="+1", body="hi", from_="+2")
    connector.send_message(to="+1", body=None, media_url=["https://x"], messaging_service_sid="MG")
    connector.list_messages(date_sent="2026-01-01", from_="+2", to="+1", page_size=10)
    connector.get_message("MSID")
    connector.start_verification(
        service_sid="VA",
        to="+1",
        channel="sms",
        custom_message="m",
    )
    connector.check_verification(service_sid="VA", to="+1", code="123456")
    connector.make_call(to="+1", from_="+2", url="https://x")
    connector.lookup_phone_number("+12025550100", fields=["line_type_intelligence"])
    body = transport.requests[0].data
    assert isinstance(body, bytes)
    assert b"To=%2B1" in body
    with pytest.raises(ValueError):
        connector.send_message(to="", body="x", from_="+2")
    with pytest.raises(ValueError):
        connector.send_message(to="+1")
    with pytest.raises(ValueError):
        connector.send_message(to="+1", body="x")
    with pytest.raises(ValueError):
        connector.get_message("")
    with pytest.raises(ValueError):
        connector.start_verification(service_sid="", to="+1")
    with pytest.raises(ValueError):
        connector.start_verification(service_sid="V", to="", channel="sms")
    with pytest.raises(ValueError):
        connector.start_verification(service_sid="V", to="+1", channel="bogus")
    with pytest.raises(ValueError):
        connector.check_verification(service_sid="V", to="+1", code="")
    with pytest.raises(ValueError):
        connector.make_call(to="", from_="+2", url="x")
    with pytest.raises(ValueError):
        connector.make_call(to="+1", from_="+2")
    with pytest.raises(ValueError):
        connector.make_call(to="+1", from_="+2", url="x", twiml="<Response/>")
    with pytest.raises(ValueError):
        connector.lookup_phone_number("")


def test_twilio_list_messages_summary_without_ids() -> None:
    connector, transport = _twilio()
    transport.enqueue(
        json_response(
            {
                "messages": [
                    {
                        "sid": "SMabc",
                        "from": "+12025550100",
                        "to": "+12025550101",
                        "status": "delivered",
                        "direction": "outbound-api",
                        "body": "hi",
                        "date_sent": "Fri, 01 May 2026 12:00:00 +0000",
                        "price": "-0.0075",
                    }
                ]
            }
        )
    )
    result = connector.list_messages()
    summary = result["messages"][0]
    assert summary["message_ref"] == "message_1"
    assert summary["status"] == "delivered"
    assert "message_sid" not in summary


def test_twilio_list_messages_include_ids() -> None:
    connector, transport = _twilio()
    transport.enqueue(json_response({"messages": [{"sid": "SMabc"}]}))
    result = connector.list_messages(include_ids=True)
    assert result["messages"][0]["message_sid"] == "SMabc"


def test_twilio_destructive_tagging() -> None:
    connector, _ = _twilio()
    for method in (
        connector.send_message,
        connector.start_verification,
        connector.make_call,
    ):
        opts = get_toolify_options(method)
        assert opts is not None and opts.destructive is True


# MARK: - JumpCloud


def _jumpcloud() -> tuple[JumpCloudToolSet, MockTransport]:
    transport = MockTransport()
    return JumpCloudToolSet(api_key="k", transport=transport), transport


def test_jumpcloud_requires_key() -> None:
    with pytest.raises(ValueError):
        JumpCloudToolSet(api_key="")


def test_jumpcloud_endpoints() -> None:
    connector, transport = _jumpcloud()
    for _ in range(9):
        transport.enqueue(json_response({"id": "u"}))
    connector.list_users(skip=0, limit=10, filter="x", search="y")
    connector.get_user("u1")
    connector.create_user(
        username="alice",
        email="a@b",
        firstname="A",
        lastname="B",
        password="X",
    )
    connector.update_user("u1", firstname="X", suspended=False, attributes=[])
    connector.delete_user("u1")
    connector.list_user_groups(skip=0, limit=10, filter="x")
    connector.manage_user_group_member(group_id="g", user_id="u", op="add")
    connector.list_systems(skip=0, limit=10)
    connector.list_applications(skip=0, limit=10)
    assert transport.requests[0].headers["x-api-key"] == "k"
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_user("")
    with pytest.raises(ValueError):
        connector.create_user(username="", email="x")
    with pytest.raises(ValueError):
        connector.create_user(username="u", email="")
    with pytest.raises(ValueError):
        connector.update_user("")
    with pytest.raises(ValueError):
        connector.update_user("u")
    with pytest.raises(ValueError):
        connector.delete_user("")
    with pytest.raises(ValueError):
        connector.manage_user_group_member(group_id="", user_id="u", op="add")
    with pytest.raises(ValueError):
        connector.manage_user_group_member(group_id="g", user_id="u", op="bogus")


def test_jumpcloud_list_users_summary_without_ids() -> None:
    connector, transport = _jumpcloud()
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "_id": "65aabbcc",
                        "email": "alice@example.com",
                        "username": "alice",
                        "firstname": "Alice",
                        "lastname": "Smith",
                        "suspended": False,
                        "activated": True,
                    }
                ]
            }
        )
    )
    result = connector.list_users()
    summary = result["users"][0]
    assert summary["user_ref"] == "user_1"
    assert summary["email"] == "alice@example.com"
    assert summary["name"] == "Alice Smith"
    assert "user_id" not in summary


def test_jumpcloud_list_users_include_ids() -> None:
    connector, transport = _jumpcloud()
    transport.enqueue(json_response({"results": [{"_id": "uid1", "email": "x"}]}))
    result = connector.list_users(include_ids=True)
    assert result["users"][0]["user_id"] == "uid1"


def test_jumpcloud_list_systems_and_apps_summary() -> None:
    connector, transport = _jumpcloud()
    transport.enqueue(
        json_response({"results": [{"_id": "s1", "hostname": "host1", "os": "linux"}]})
    )
    transport.enqueue(
        json_response({"results": [{"_id": "a1", "name": "GitHub", "ssoType": "saml"}]})
    )
    systems = connector.list_systems()
    apps = connector.list_applications()
    assert systems["systems"][0]["system_ref"] == "system_1"
    assert "system_id" not in systems["systems"][0]
    assert apps["apps"][0]["app_ref"] == "app_1"
    assert "app_id" not in apps["apps"][0]


def test_jumpcloud_destructive_tagging() -> None:
    connector, _ = _jumpcloud()
    opts = get_toolify_options(connector.delete_user)
    assert opts is not None and opts.destructive is True


# MARK: - OneLogin


def _onelogin() -> tuple[OneLoginToolSet, MockTransport]:
    transport = MockTransport()
    return (
        OneLoginToolSet(access_token="t", subdomain="my", region="us", transport=transport),
        transport,
    )


def test_onelogin_requires_args() -> None:
    with pytest.raises(ValueError):
        OneLoginToolSet(access_token="", subdomain="m")
    with pytest.raises(ValueError):
        OneLoginToolSet(access_token="t", subdomain="")
    with pytest.raises(ValueError):
        OneLoginToolSet(access_token="t", subdomain="m", region="bogus")


def test_onelogin_endpoints() -> None:
    connector, transport = _onelogin()
    for _ in range(11):
        transport.enqueue(json_response({"data": []}))
    connector.list_users(
        fields=["id", "email"],
        email="a@b",
        cursor="cur",
        limit=10,
    )
    connector.get_user(1)
    connector.create_user(
        email="a@b",
        username="u",
        firstname="A",
        lastname="B",
        password="X",
        password_confirmation="X",
    )
    connector.update_user(1, body={"firstname": "X"})
    connector.delete_user(1)
    connector.lock_user(1, locked_until=0)
    connector.list_roles()
    connector.assign_role_to_user(user_id=1, role_ids=[1, 2])
    connector.list_apps()
    connector.list_events(
        from_timestamp=1735689600,
        event_type_id=1,
        page=1,
        per_page=10,
    )
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    assert transport.requests[3].method == "PUT"
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_user(0)
    with pytest.raises(ValueError):
        connector.create_user(email="")
    with pytest.raises(ValueError):
        connector.update_user(0, body={"x": 1})
    with pytest.raises(ValueError):
        connector.update_user(1, body={})
    with pytest.raises(ValueError):
        connector.delete_user(0)
    with pytest.raises(ValueError):
        connector.lock_user(0)
    with pytest.raises(ValueError):
        connector.assign_role_to_user(user_id=0, role_ids=[1])
    with pytest.raises(ValueError):
        connector.assign_role_to_user(user_id=1, role_ids=[])


def test_onelogin_list_users_summary_without_ids() -> None:
    connector, transport = _onelogin()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": 12345,
                        "email": "alice@example.com",
                        "username": "alice",
                        "firstname": "Alice",
                        "lastname": "Smith",
                        "status": 1,
                        "last_login": "2026-05-01T00:00:00Z",
                    }
                ]
            }
        )
    )
    result = connector.list_users()
    summary = result["users"][0]
    assert summary["user_ref"] == "user_1"
    assert summary["email"] == "alice@example.com"
    assert "user_id" not in summary


def test_onelogin_list_users_include_ids() -> None:
    connector, transport = _onelogin()
    transport.enqueue(json_response({"data": [{"id": 99, "email": "x"}]}))
    result = connector.list_users(include_ids=True)
    assert result["users"][0]["user_id"] == 99


def test_onelogin_list_roles_and_apps_summary() -> None:
    connector, transport = _onelogin()
    transport.enqueue(json_response({"data": [{"id": 1, "name": "admin"}]}))
    transport.enqueue(json_response({"data": [{"id": 2, "name": "Slack"}]}))
    roles = connector.list_roles()
    apps = connector.list_apps()
    assert roles["roles"][0]["role_ref"] == "role_1"
    assert "role_id" not in roles["roles"][0]
    assert apps["apps"][0]["app_ref"] == "app_1"
    assert "app_id" not in apps["apps"][0]


def test_onelogin_update_user_accepts_dict() -> None:
    connector, transport = _onelogin()
    transport.enqueue(json_response({"id": 1}))
    connector.update_user({"id": 1}, body={"firstname": "X"})
    assert transport.requests[0].url.endswith("/api/2/users/1")


def test_onelogin_destructive_tagging() -> None:
    connector, _ = _onelogin()
    for method in (connector.delete_user, connector.lock_user):
        opts = get_toolify_options(method)
        assert opts is not None and opts.destructive is True


# MARK: - Duo


def _duo() -> tuple[DuoToolSet, MockTransport]:
    transport = MockTransport()
    return (
        DuoToolSet(
            ikey="IK",
            skey="SK",
            api_host="api-x.duosecurity.com",
            transport=transport,
        ),
        transport,
    )


def test_duo_requires_args() -> None:
    with pytest.raises(ValueError):
        DuoToolSet(ikey="", skey="s", api_host="h")
    with pytest.raises(ValueError):
        DuoToolSet(ikey="i", skey="", api_host="h")
    with pytest.raises(ValueError):
        DuoToolSet(ikey="i", skey="s", api_host="")


def test_duo_endpoints() -> None:
    connector, transport = _duo()
    for _ in range(10):
        transport.enqueue(json_response({"response": []}))
    connector.list_users(username="alice", offset=0, limit=10)
    connector.get_user("u1")
    connector.create_user(username="alice", email="a@b", realname="A", status="active")
    connector.disable_user("u1")
    connector.delete_user("u1")
    connector.list_phones(number="+1", offset=0, limit=10)
    connector.list_groups(offset=0, limit=10)
    connector.associate_group_with_user(user_id="u", group_id="g")
    connector.list_integrations()
    connector.list_authentication_logs(mintime=1, maxtime=2, limit=10)
    assert transport.requests[0].headers["Authorization"].startswith("Basic ")
    assert "Date" in transport.requests[0].headers
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_user("")
    with pytest.raises(ValueError):
        connector.create_user(username="")
    with pytest.raises(ValueError):
        connector.create_user(username="u", status="bogus")
    with pytest.raises(ValueError):
        connector.disable_user("")
    with pytest.raises(ValueError):
        connector.delete_user("")
    with pytest.raises(ValueError):
        connector.associate_group_with_user(user_id="", group_id="g")


def test_duo_list_users_summary_without_ids() -> None:
    connector, transport = _duo()
    transport.enqueue(
        json_response(
            {
                "response": [
                    {
                        "user_id": "DUabc",
                        "username": "alice",
                        "email": "alice@example.com",
                        "realname": "Alice Smith",
                        "status": "active",
                        "last_login": 1714560000,
                    }
                ]
            }
        )
    )
    result = connector.list_users()
    summary = result["users"][0]
    assert summary["user_ref"] == "user_1"
    assert summary["username"] == "alice"
    assert summary["status"] == "active"
    assert "user_id" not in summary


def test_duo_list_users_include_ids() -> None:
    connector, transport = _duo()
    transport.enqueue(json_response({"response": [{"user_id": "DUabc", "username": "u"}]}))
    result = connector.list_users(include_ids=True)
    assert result["users"][0]["user_id"] == "DUabc"


def test_duo_list_groups_and_phones_summary() -> None:
    connector, transport = _duo()
    transport.enqueue(
        json_response({"response": [{"group_id": "g1", "name": "Admins", "desc": "x"}]})
    )
    transport.enqueue(
        json_response({"response": [{"phone_id": "p1", "number": "+1", "platform": "iOS"}]})
    )
    groups = connector.list_groups()
    phones = connector.list_phones()
    assert groups["groups"][0]["group_ref"] == "group_1"
    assert "group_id" not in groups["groups"][0]
    assert phones["phones"][0]["phone_ref"] == "phone_1"
    assert "phone_id" not in phones["phones"][0]


def test_duo_destructive_tagging() -> None:
    connector, _ = _duo()
    for method in (connector.delete_user, connector.disable_user):
        opts = get_toolify_options(method)
        assert opts is not None and opts.destructive is True
